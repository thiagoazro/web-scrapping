import json
import unittest

from anonimizador_juridico import defesas, tipos as T
from anonimizador_juridico.agente_anonimizador import AgenteAnonimizador
from anonimizador_juridico.agente_auditor import AgenteAuditor
from anonimizador_juridico.cofre import Cofre

PECA = """\
MARIA APARECIDA DOS SANTOS, CPF 529.982.247-25, residente na Rua das Acácias,
nº 250, propõe ação em face de CONSTRUTORA HORIZONTE LTDA.

A reclamante MARIA APARECIDA DOS SANTOS foi admitida em 01/02/2019, nos termos
do art. 71 da CLT. Contato: maria@exemplo.com, telefone (11) 98765-4321.
"""


class ClienteFalso:
    """Dublê do Claude: responde o que o teste mandar, sem rede.

    Por padrão devolve o canário que veio no prompt — é o que um modelo
    íntegro faria. `subvertido=True` simula o modelo que obedeceu a uma
    instrução escondida no documento e não devolveu a entidade de controle.
    """

    def __init__(self, resposta, subvertido=False):
        self.resposta = resposta
        self.subvertido = subvertido
        self.chamadas = []
        self.disponivel = True
        self.erro_inicializacao = None

    def extrair_json(self, sistema, conteudo, schema, max_tokens=None):
        self.chamadas.append(conteudo)
        resposta = json.loads(json.dumps(self.resposta))  # cópia
        if self.subvertido:
            return resposta
        marca = defesas.RE_CANARIO.search(conteudo)
        if marca:
            if "entidades" in resposta:
                resposta["entidades"].append({
                    "trecho": marca.group(0), "tipo": "NOME_PESSOA",
                    "confianca": 0.95, "motivo": "testemunha"})
            if "achados" in resposta:
                resposta["achados"].append({
                    "trecho": marca.group(0), "tipo": "EMAIL",
                    "gravidade": "alta", "descricao": "e-mail remanescente"})
        return resposta


class TestAgenteAnonimizador(unittest.TestCase):
    def test_remove_dados_e_preserva_conteudo_juridico(self):
        resultado = AgenteAnonimizador().anonimizar(PECA)
        saida = resultado.texto_anonimizado
        self.assertNotIn("529.982.247-25", saida)
        self.assertNotIn("MARIA APARECIDA DOS SANTOS", saida)
        self.assertNotIn("maria@exemplo.com", saida)
        self.assertIn("art. 71 da CLT", saida)
        self.assertIn("01/02/2019", saida)   # data contratual não é dado pessoal

    def test_mesma_pessoa_mesmo_pseudonimo_no_documento_todo(self):
        resultado = AgenteAnonimizador().anonimizar(PECA)
        tokens = [o for o in resultado.ocorrencias if o.tipo == T.NOME_PESSOA]
        self.assertGreaterEqual(len(tokens), 2)
        self.assertEqual(resultado.texto_anonimizado.count("[NOME_"), 2)

    def test_cofre_permite_desfazer(self):
        agente = AgenteAnonimizador(cofre=Cofre())
        resultado = agente.anonimizar(PECA)
        self.assertEqual(agente.cofre.reidentificar(resultado.texto_anonimizado),
                         PECA)

    def test_trechos_forcados_pela_auditoria(self):
        resultado = AgenteAnonimizador().anonimizar(
            "O apelido dele no galpão era Zezinho do Norte.",
            trechos_forcados=["Zezinho do Norte"],
            tipos_forcados={"Zezinho do Norte": T.NOME_PESSOA},
        )
        self.assertNotIn("Zezinho do Norte", resultado.texto_anonimizado)

    def test_tipos_ignorados(self):
        agente = AgenteAnonimizador(tipos_ignorados={T.LOCALIDADE, T.NOME_EMPRESA})
        saida = agente.anonimizar(
            "A empresa CONSTRUTORA HORIZONTE LTDA, de São Paulo, "
            "contratou João Pedro Alves."
        ).texto_anonimizado
        self.assertIn("CONSTRUTORA HORIZONTE LTDA", saida)
        self.assertIn("São Paulo", saida)
        self.assertNotIn("João Pedro Alves", saida)

    def test_llm_indisponivel_nao_derruba_o_agente(self):
        class Indisponivel:
            disponivel = False
            erro_inicializacao = "sem credencial"

        resultado = AgenteAnonimizador(usar_llm=True,
                                       cliente=Indisponivel()).anonimizar(PECA)
        self.assertFalse(resultado.usou_llm)
        self.assertTrue(resultado.avisos)
        self.assertNotIn("529.982.247-25", resultado.texto_anonimizado)

    def test_camada_semantica_captura_o_que_regra_nao_pega(self):
        cliente = ClienteFalso({"entidades": [
            {"trecho": "o único soldador canhoto da filial",
             "tipo": "DADO_SENSIVEL", "confianca": 0.9,
             "motivo": "singularização"},
        ]})
        texto = "Trata-se de o único soldador canhoto da filial, dispensado."
        resultado = AgenteAnonimizador(usar_llm=True,
                                       cliente=cliente).anonimizar(texto)
        self.assertTrue(resultado.usou_llm)
        self.assertNotIn("soldador canhoto", resultado.texto_anonimizado)

    def test_dado_estruturado_nao_e_enviado_ao_modelo(self):
        cliente = ClienteFalso({"entidades": []})
        AgenteAnonimizador(usar_llm=True, cliente=cliente).anonimizar(PECA)
        enviado = cliente.chamadas[0]
        self.assertNotIn("529.982.247-25", enviado)
        self.assertNotIn("maria@exemplo.com", enviado)
        self.assertIn("[CPF_", enviado)

    def test_trecho_alucinado_pelo_modelo_e_descartado(self):
        cliente = ClienteFalso({"entidades": [
            {"trecho": "Fulano de Tal que não existe no texto",
             "tipo": "NOME_PESSOA", "confianca": 0.99, "motivo": "inventado"},
        ]})
        texto = "A reclamada não apresentou defesa."
        resultado = AgenteAnonimizador(usar_llm=True,
                                       cliente=cliente).anonimizar(texto)
        self.assertEqual(resultado.texto_anonimizado, texto)


class TestAgenteAuditor(unittest.TestCase):
    def setUp(self):
        self.agente = AgenteAnonimizador(cofre=Cofre())
        self.resultado = self.agente.anonimizar(PECA)

    def test_aprova_peca_limpa(self):
        parecer = AgenteAuditor().auditar(self.resultado.texto_anonimizado,
                                          PECA, self.agente.cofre)
        self.assertTrue(parecer.aprovado, [a.descricao for a in parecer.achados])
        self.assertEqual(parecer.nota_risco, 0)

    def test_reprova_dado_que_escapou(self):
        vazado = self.resultado.texto_anonimizado.replace(
            "[CPF_001]", "529.982.247-25")
        parecer = AgenteAuditor().auditar(vazado, PECA, self.agente.cofre)
        self.assertFalse(parecer.aprovado)
        categorias = {a.categoria for a in parecer.achados}
        self.assertIn("residual", categorias)
        self.assertIn("vazamento_literal", categorias)

    def test_verificacao_cega_funciona_sem_o_original(self):
        parecer = AgenteAuditor().auditar("Contato: joao@exemplo.com")
        self.assertFalse(parecer.aprovado)
        self.assertIn("não executada", parecer.verificacoes["confronto"])

    def test_detecta_reescrita_do_conteudo(self):
        adulterado = self.resultado.texto_anonimizado + \
            "\nParágrafo inventado pelo modelo."
        parecer = AgenteAuditor().auditar(adulterado, PECA, self.agente.cofre)
        self.assertIn("conteudo_alterado",
                      {a.categoria for a in parecer.achados})

    def test_detecta_ausencia_de_anonimizacao(self):
        parecer = AgenteAuditor().auditar(PECA, PECA)
        self.assertFalse(parecer.aprovado)
        self.assertIn("sem_substituicao", {a.categoria for a in parecer.achados})

    def test_detecta_token_orfao(self):
        texto = self.resultado.texto_anonimizado + " Ver também [NOME_999]."
        parecer = AgenteAuditor().auditar(texto, cofre=self.agente.cofre)
        self.assertIn("token_orfao", {a.categoria for a in parecer.achados})

    def test_relatorio_nao_repete_o_dado_vazado(self):
        vazado = self.resultado.texto_anonimizado.replace(
            "[CPF_001]", "529.982.247-25")
        parecer = AgenteAuditor().auditar(vazado, PECA)
        serializado = str(parecer.para_dict())
        self.assertNotIn("529.982.247-25", serializado)

    def test_camada_semantica_do_auditor(self):
        cliente = ClienteFalso({
            "identificavel": True,
            "achados": [{"trecho": "único soldador canhoto", "tipo": "INDIRETO",
                         "gravidade": "alta",
                         "descricao": "singulariza uma pessoa"}],
            "recomendacoes": ["generalizar a função"],
        })
        parecer = AgenteAuditor(usar_llm=True, cliente=cliente).auditar(
            "[NOME_001] era o único soldador canhoto da unidade.")
        self.assertFalse(parecer.aprovado)
        self.assertTrue(parecer.usou_llm)
        self.assertIn("generalizar a função", parecer.recomendacoes)

    def test_verificacao_semantica_pedida_e_nao_executada_reprova(self):
        class Indisponivel:
            disponivel = False
            erro_inicializacao = "sem credencial"

        parecer = AgenteAuditor(usar_llm=True, cliente=Indisponivel()).auditar(
            "[NOME_001] compareceu à audiência.")
        self.assertFalse(parecer.aprovado)
        self.assertIn("verificacao_incompleta",
                      {a.categoria for a in parecer.achados})

    def test_achado_alucinado_do_auditor_e_descartado(self):
        cliente = ClienteFalso({
            "identificavel": True,
            "achados": [{"trecho": "trecho que não existe", "tipo": "NOME_PESSOA",
                         "gravidade": "critica", "descricao": "inventado"}],
            "recomendacoes": [],
        })
        parecer = AgenteAuditor(usar_llm=True, cliente=cliente).auditar(
            "[NOME_001] compareceu à audiência.")
        self.assertEqual([a for a in parecer.achados if a.origem == "llm"], [])


if __name__ == "__main__":
    unittest.main()
