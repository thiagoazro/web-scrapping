import base64
import json
import threading
import unittest
import urllib.error
import urllib.request

from anonimizador_juridico.web.servidor import criar_servidor

PECA = ("MARIA APARECIDA DOS SANTOS, CPF 529.982.247-25, propõe ação "
        "nos termos do art. 71 da CLT.\n")


class BaseWeb(unittest.TestCase):
    token = None

    def setUp(self):
        self.servidor = criar_servidor("127.0.0.1", 0, token=self.token)
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.servidor.server_port}"
        self.addCleanup(self.servidor.server_close)
        self.addCleanup(self.servidor.shutdown)

    def pedir(self, rota, corpo=None, cabecalhos=None):
        dados = json.dumps(corpo).encode() if corpo is not None else None
        pedido = urllib.request.Request(
            self.base + rota, data=dados,
            headers={"Content-Type": "application/json", **(cabecalhos or {})})
        with urllib.request.urlopen(pedido) as resposta:
            return json.load(resposta)

    @staticmethod
    def arquivo(nome, texto):
        return {"nome": nome,
                "conteudo": base64.b64encode(texto.encode("utf-8")).decode()}


class TestServidor(BaseWeb):
    def test_pagina_inicial(self):
        with urllib.request.urlopen(self.base + "/") as resposta:
            corpo = resposta.read().decode()
        self.assertIn("Anonimizador de peças judiciais", corpo)

    def test_estado_lista_perfis_e_situacao_do_llm(self):
        estado = self.pedir("/api/estado")
        self.assertIn("padrao", [p["chave"] for p in estado["perfis"]])
        self.assertIn("disponivel", estado["llm"])
        self.assertIn(".docx", estado["formatos"])

    def test_anonimizar_arquivo(self):
        resposta = self.pedir("/api/anonimizar",
                              {"arquivos": [self.arquivo("peca.txt", PECA)]})
        documento = resposta["documentos"][0]
        self.assertTrue(documento["aprovado"])
        self.assertNotIn("529.982.247-25", documento["texto_anonimizado"])
        self.assertIn("art. 71 da CLT", documento["texto_anonimizado"])
        self.assertTrue(resposta["sessao"])

    def test_lote_compartilha_o_mesmo_pseudonimo(self):
        """Duas peças do mesmo processo, enviadas juntas: a mesma pessoa
        precisa receber o mesmo marcador nas duas."""
        resposta = self.pedir("/api/anonimizar", {"arquivos": [
            self.arquivo("inicial.txt", "O reclamante João Pedro Alves alega."),
            self.arquivo("replica.txt", "Conforme João Pedro Alves relatou."),
        ]})
        um, outro = resposta["documentos"]
        marcador = um["texto_anonimizado"].split("reclamante ")[1].split(" ")[0]
        self.assertIn(marcador, outro["texto_anonimizado"])

    def test_sessao_continua_entre_envios(self):
        primeira = self.pedir("/api/anonimizar",
                              {"texto": "O reclamante João Pedro Alves alega."})
        segunda = self.pedir("/api/anonimizar", {
            "sessao": primeira["sessao"],
            "texto": "Depois, João Pedro Alves confirmou.",
        })
        self.assertEqual(primeira["sessao"], segunda["sessao"])
        self.assertIn("[NOME_001]", segunda["documentos"][0]["texto_anonimizado"])

    def test_reidentificar_e_encerrar(self):
        resposta = self.pedir("/api/anonimizar", {"texto": PECA})
        sessao = resposta["sessao"]
        anonimizado = resposta["documentos"][0]["texto_anonimizado"]

        volta = self.pedir("/api/reidentificar",
                           {"sessao": sessao, "texto": anonimizado})
        self.assertEqual(volta["texto"], PECA.strip())

        self.assertTrue(self.pedir("/api/encerrar", {"sessao": sessao})["encerrada"])
        with self.assertRaises(urllib.error.HTTPError) as erro:
            self.pedir("/api/reidentificar", {"sessao": sessao, "texto": anonimizado})
        self.assertEqual(erro.exception.code, 404)

    def test_baixar_cofre(self):
        sessao = self.pedir("/api/anonimizar", {"texto": PECA})["sessao"]
        with urllib.request.urlopen(f"{self.base}/api/cofre?sessao={sessao}") as r:
            self.assertIn("attachment", r.headers["Content-Disposition"])
            cofre = json.load(r)
        self.assertTrue(cofre["entradas"])

    def test_auditar_texto_ja_anonimizado(self):
        resposta = self.pedir("/api/auditar",
                              {"texto": "Contato do autor: joao@exemplo.com"})
        self.assertFalse(resposta["documentos"][0]["aprovado"])

    def test_arquivo_invalido_nao_derruba_o_lote(self):
        resposta = self.pedir("/api/anonimizar", {"arquivos": [
            self.arquivo("peca.txt", PECA),
            {"nome": "planilha.zip", "conteudo": base64.b64encode(b"x").decode()},
        ]})
        bons = [d for d in resposta["documentos"] if not d.get("erro")]
        ruins = [d for d in resposta["documentos"] if d.get("erro")]
        self.assertEqual(len(bons), 1)
        self.assertEqual(len(ruins), 1)
        self.assertIn("não suportado", ruins[0]["erro"])

    def test_perfil_aplicado_pela_interface(self):
        texto = "Processo nº 0001234-02.2023.5.02.0011, autor João Pedro Alves."
        resposta = self.pedir("/api/anonimizar",
                              {"texto": texto, "perfil": "jurisprudencia"})
        saida = resposta["documentos"][0]["texto_anonimizado"]
        self.assertIn("0001234-02.2023.5.02.0011", saida)
        self.assertNotIn("João Pedro Alves", saida)

    def test_requisicao_sem_documento(self):
        with self.assertRaises(urllib.error.HTTPError) as erro:
            self.pedir("/api/anonimizar", {"texto": "   "})
        self.assertEqual(erro.exception.code, 400)

    def test_rota_inexistente(self):
        with self.assertRaises(urllib.error.HTTPError) as erro:
            self.pedir("/api/nao-existe", {})
        self.assertEqual(erro.exception.code, 404)


class TestServidorComToken(BaseWeb):
    token = "segredo-de-teste"

    def test_api_exige_token(self):
        with self.assertRaises(urllib.error.HTTPError) as erro:
            self.pedir("/api/estado")
        self.assertEqual(erro.exception.code, 401)

    def test_token_correto_libera(self):
        estado = self.pedir("/api/estado", cabecalhos={"X-Token": self.token})
        self.assertTrue(estado["perfis"])

    def test_pagina_inicial_continua_publica(self):
        with urllib.request.urlopen(self.base + "/") as resposta:
            self.assertEqual(resposta.status, 200)


if __name__ == "__main__":
    unittest.main()
