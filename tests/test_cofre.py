import tempfile
import unittest
from pathlib import Path

from anonimizador_juridico import tipos as T
from anonimizador_juridico.cofre import Cofre


class TestCofre(unittest.TestCase):
    def test_grafia_identica_repete_o_mesmo_pseudonimo(self):
        cofre = Cofre()
        self.assertEqual(cofre.token_para(T.NOME_PESSOA, "João da Silva"),
                         cofre.token_para(T.NOME_PESSOA, "João da Silva"))

    def test_variacao_de_grafia_e_a_mesma_entidade_com_token_proprio(self):
        """Mesma pessoa escrita de dois jeitos: tokens distintos (para a volta
        ser exata) com a mesma base (para o cruzamento continuar possível)."""
        cofre = Cofre()
        a = cofre.token_para(T.NOME_PESSOA, "João da Silva")
        b = cofre.token_para(T.NOME_PESSOA, "JOÃO DA SILVA")
        self.assertNotEqual(a, b)
        self.assertTrue(cofre.mesma_entidade(a, b))
        self.assertEqual(Cofre.base_de(b), a)

    def test_reidentificacao_preserva_a_grafia_original(self):
        cofre = Cofre()
        um = cofre.token_para(T.LOCALIDADE, "São Paulo")
        outro = cofre.token_para(T.LOCALIDADE, "SÃO PAULO")
        texto = f"Foro de {um}; comarca de {outro}."
        self.assertEqual(cofre.reidentificar(texto),
                         "Foro de São Paulo; comarca de SÃO PAULO.")

    def test_formatacao_do_documento_nao_muda_a_entidade(self):
        cofre = Cofre()
        self.assertTrue(cofre.mesma_entidade(
            cofre.token_para(T.CPF, "529.982.247-25"),
            cofre.token_para(T.CPF, "52998224725")))
        self.assertTrue(cofre.mesma_entidade(
            cofre.token_para(T.TELEFONE, "(11) 98765-4321"),
            cofre.token_para(T.TELEFONE, "11987654321")))

    def test_valores_distintos_tokens_distintos(self):
        cofre = Cofre()
        self.assertNotEqual(cofre.token_para(T.NOME_PESSOA, "Ana"),
                            cofre.token_para(T.NOME_PESSOA, "Bruno"))

    def test_estilo_hash_e_estavel_entre_execucoes(self):
        """O mesmo CPF em dois processos diferentes vira o mesmo marcador —
        é o que permite cruzar casos sem reidentificar ninguém."""
        chave = b"chave-de-teste"
        um = Cofre(estilo="hash", chave_secreta=chave)
        outro = Cofre(estilo="hash", chave_secreta=chave)
        self.assertEqual(um.token_para(T.CPF, "529.982.247-25"),
                         outro.token_para(T.CPF, "529.982.247-25"))
        self.assertTrue(um.mesma_entidade(um.token_para(T.CPF, "52998224725"),
                                          outro.token_para(T.CPF, "529.982.247-25")))

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
