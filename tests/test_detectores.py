import unittest

from anonimizador_juridico import detectores, tipos as T


def tipos_de(texto, **kw):
    return {o.tipo for o in detectores.varrer(texto, **kw)}


def valores_de(texto, tipo, **kw):
    return [o.valor for o in detectores.varrer(texto, **kw) if o.tipo == tipo]


class TestDeteccaoEstruturada(unittest.TestCase):
    def test_documentos_validados_por_digito_verificador(self):
        texto = ("CPF 529.982.247-25, CNPJ 11.222.333/0001-81, "
                 "processo 0001234-02.2023.5.02.0011")
        self.assertEqual(tipos_de(texto), {T.CPF, T.CNPJ, T.PROCESSO_CNJ})

    def test_numero_com_dv_invalido_nao_vira_cpf(self):
        self.assertNotIn(T.CPF, tipos_de("protocolo 529.982.247-26 anexo"))

    def test_contato_e_endereco(self):
        texto = ("e-mail joao@exemplo.com.br, telefone (11) 98765-4321, "
                 "Rua das Acácias, nº 250, CEP 01234-567")
        self.assertEqual(
            tipos_de(texto) & {T.EMAIL, T.TELEFONE, T.CEP, T.ENDERECO},
            {T.EMAIL, T.TELEFONE, T.CEP, T.ENDERECO},
        )

    def test_dado_sensivel_cid(self):
        self.assertIn(T.DADO_SENSIVEL, tipos_de("afastado por lombalgia (CID M54.5)"))

    def test_data_de_nascimento_exige_contexto(self):
        self.assertIn(T.DATA_NASCIMENTO, tipos_de("nascida em 12/03/1985"))
        # data de admissão é conteúdo jurídico e deve sobreviver
        self.assertNotIn(T.DATA_NASCIMENTO, tipos_de("admitida em 01/02/2019"))

    def test_rg_exige_contexto(self):
        self.assertIn(T.RG, tipos_de("RG nº 12.345.678-9 SSP/SP"))
        self.assertNotIn(T.RG, tipos_de("o item 12.345.678-9 do inventário"))


class TestDeteccaoDeNomes(unittest.TestCase):
    def test_nome_com_marcador_de_papel(self):
        nomes = valores_de("o reclamante João Pedro Alves compareceu", T.NOME_PESSOA)
        self.assertIn("João Pedro Alves", nomes)

    def test_termos_juridicos_nao_sao_nomes(self):
        texto = ("EXCELENTÍSSIMO SENHOR DOUTOR JUIZ DA VARA DO TRABALHO\n"
                 "RECLAMAÇÃO TRABALHISTA\nDOS FATOS\nCONSOLIDAÇÃO DAS LEIS DO "
                 "TRABALHO\nTRIBUNAL SUPERIOR DO TRABALHO")
        self.assertNotIn(T.NOME_PESSOA, tipos_de(texto))

    def test_duas_testemunhas_nao_viram_um_nome_so(self):
        texto = "as testemunhas Ana Lúcia Ferreira e José Carlos de Oliveira Filho"
        nomes = valores_de(texto, T.NOME_PESSOA)
        self.assertIn("Ana Lúcia Ferreira", nomes)
        self.assertIn("José Carlos de Oliveira Filho", nomes)

    def test_razao_social_nao_vira_pessoa(self):
        ocorrencias = detectores.varrer("em face de CONSTRUTORA HORIZONTE LTDA")
        tipos = {o.tipo for o in ocorrencias}
        self.assertIn(T.NOME_EMPRESA, tipos)
        self.assertNotIn(T.NOME_PESSOA, tipos)

    def test_cidade_nao_parte_nome_de_pessoa(self):
        # "Santos" é cidade e também sobrenome: o nome completo tem de vencer.
        nomes = valores_de("MARIA APARECIDA DOS SANTOS, brasileira", T.NOME_PESSOA)
        self.assertIn("MARIA APARECIDA DOS SANTOS", nomes)

    def test_pronome_de_tratamento_nao_e_nome(self):
        self.assertNotIn(T.NOME_PESSOA, tipos_de("à presença de Vossa Excelência"))

    def test_propagacao_de_entidade_repetida(self):
        texto = ("o reclamante João Pedro Alves relatou.\n\n"
                 "Mais tarde, João Pedro Alves confirmou.")
        nomes = [o for o in detectores.varrer(texto) if o.tipo == T.NOME_PESSOA]
        self.assertEqual(len(nomes), 2)


class TestRecorteDeNomes(unittest.TestCase):
    def test_nome_nao_atravessa_paragrafo(self):
        texto = "VARA DO TRABALHO\n\nMARIA APARECIDA DOS SANTOS, brasileira"
        nomes = valores_de(texto, T.NOME_PESSOA)
        self.assertEqual(nomes, ["MARIA APARECIDA DOS SANTOS"])

    def test_nome_quebrado_pela_margem_continua_inteiro(self):
        # texto justificado quebra o nome em duas linhas
        nomes = valores_de("Assinado por Dr. Carlos Eduardo\nPereira, OAB/SP 123.456",
                           T.NOME_PESSOA)
        self.assertEqual(nomes, ["Carlos Eduardo\nPereira"])

    def test_intervalo_bate_com_o_texto(self):
        """O trecho apontado precisa ser exatamente o que está no documento:
        errar um caractere no fim deixa a última letra do nome para trás."""
        texto = ("VARA DO TRABALHO\n\nMARIA APARECIDA DOS SANTOS, brasileira, "
                 "residente em Santos")
        for ocorrencia in detectores.varrer(texto):
            self.assertEqual(texto[ocorrencia.inicio:ocorrencia.fim],
                             ocorrencia.valor)


class TestResolucaoDeSobreposicao(unittest.TestCase):
    def test_trecho_mais_especifico_vence(self):
        ocorrencias = detectores.varrer("PIS 12012345672 do autor")
        # o mesmo número passa no DV de CPF; o rótulo "PIS" no texto decide.
        self.assertEqual([o.tipo for o in ocorrencias if o.valor == "12012345672"],
                         [T.PIS])

    def test_ocorrencias_nunca_se_sobrepoem(self):
        texto = ("MARIA APARECIDA DOS SANTOS, CPF 529.982.247-25, "
                 "Rua das Acácias, nº 250, São Paulo/SP")
        ocorrencias = detectores.varrer(texto)
        for a, b in zip(ocorrencias, ocorrencias[1:]):
            self.assertLessEqual(a.fim, b.inicio)


if __name__ == "__main__":
    unittest.main()
