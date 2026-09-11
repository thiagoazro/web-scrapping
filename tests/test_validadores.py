import unittest

from anonimizador_juridico import validadores as v


class TestValidadores(unittest.TestCase):
    def test_cpf(self):
        self.assertTrue(v.valida_cpf("529.982.247-25"))
        self.assertTrue(v.valida_cpf("52998224725"))
        self.assertFalse(v.valida_cpf("529.982.247-26"))   # DV errado
        self.assertFalse(v.valida_cpf("111.111.111-11"))   # repetido
        self.assertFalse(v.valida_cpf("1234"))

    def test_cnpj(self):
        self.assertTrue(v.valida_cnpj("11.222.333/0001-81"))
        self.assertFalse(v.valida_cnpj("11.222.333/0001-82"))
        self.assertFalse(v.valida_cnpj("00.000.000/0000-00"))

    def test_pis(self):
        self.assertTrue(v.valida_pis("120.12345.67-2"))
        self.assertFalse(v.valida_pis("120.12345.67-9"))

    def test_processo_cnj(self):
        self.assertTrue(v.valida_processo_cnj("0001234-02.2023.5.02.0011"))
        self.assertFalse(v.valida_processo_cnj("0001234-99.2023.5.02.0011"))
        self.assertFalse(v.valida_processo_cnj("123"))

    def test_cartao_luhn(self):
        self.assertTrue(v.valida_luhn("4111 1111 1111 1111"))
        self.assertFalse(v.valida_luhn("4111 1111 1111 1112"))

    def test_titulo_eleitor(self):
        self.assertTrue(v.valida_titulo_eleitor("1234 5678 0191"))
        self.assertFalse(v.valida_titulo_eleitor("1234 5678 0199"))

    def test_cnh(self):
        self.assertTrue(v.valida_cnh("43518999133"))
        self.assertFalse(v.valida_cnh("43518999134"))


if __name__ == "__main__":
    unittest.main()
