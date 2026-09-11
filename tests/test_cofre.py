import tempfile
import unittest
from pathlib import Path

from anonimizador_juridico import tipos as T
from anonimizador_juridico.cofre import Cofre


class TestCofre(unittest.TestCase):
    def test_mesmo_valor_mesmo_pseudonimo(self):
        cofre = Cofre()
        a = cofre.token_para(T.NOME_PESSOA, "João da Silva")
        b = cofre.token_para(T.NOME_PESSOA, "JOÃO DA SILVA")  # variação gráfica
        self.assertEqual(a, b)

    def test_formatacao_do_documento_nao_gera_token_novo(self):
        cofre = Cofre()
        self.assertEqual(cofre.token_para(T.CPF, "529.982.247-25"),
                         cofre.token_para(T.CPF, "52998224725"))
        self.assertEqual(cofre.token_para(T.TELEFONE, "(11) 98765-4321"),
                         cofre.token_para(T.TELEFONE, "11987654321"))

    def test_valores_distintos_tokens_distintos(self):
        cofre = Cofre()
        self.assertNotEqual(cofre.token_para(T.NOME_PESSOA, "Ana"),
                            cofre.token_para(T.NOME_PESSOA, "Bruno"))

    def test_estilo_hash_e_estavel_entre_execucoes(self):
        chave = b"chave-de-teste"
        um = Cofre(estilo="hash", chave_secreta=chave)
        outro = Cofre(estilo="hash", chave_secreta=chave)
        self.assertEqual(um.token_para(T.CPF, "529.982.247-25"),
                         outro.token_para(T.CPF, "52998224725"))

    def test_chaves_diferentes_geram_pseudonimos_diferentes(self):
        a = Cofre(estilo="hash", chave_secreta=b"chave-a")
        b = Cofre(estilo="hash", chave_secreta=b"chave-b")
        self.assertNotEqual(a.token_para(T.CPF, "529.982.247-25"),
                            b.token_para(T.CPF, "529.982.247-25"))

    def test_ida_e_volta_em_disco(self):
        cofre = Cofre()
        token = cofre.token_para(T.NOME_PESSOA, "Maria Aparecida")
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "cofre.json"
            cofre.salvar(caminho)
            recarregado = Cofre.carregar(caminho)
        self.assertEqual(recarregado.valor_de(token), "Maria Aparecida")

    def test_reidentificacao(self):
        cofre = Cofre()
        cofre.token_para(T.NOME_PESSOA, "Maria Aparecida")
        cofre.token_para(T.CPF, "529.982.247-25")
        texto = "A autora [NOME_001], CPF [CPF_001], requer."
        self.assertEqual(cofre.reidentificar(texto),
                         "A autora Maria Aparecida, CPF 529.982.247-25, requer.")

    def test_sem_cofre_nao_ha_reidentificacao(self):
        # Cofre novo não conhece tokens de outra execução: o texto fica intacto.
        texto = "A autora [NOME_001] requer."
        self.assertEqual(Cofre().reidentificar(texto), texto)


if __name__ == "__main__":
    unittest.main()
