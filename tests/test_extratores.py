import io
import unittest
import zipfile

from anonimizador_juridico.extratores import FormatoNaoSuportado, extrair_texto

NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def docx(paragrafos):
    memoria = io.BytesIO()
    corpo = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragrafos)
    with zipfile.ZipFile(memoria, "w") as arquivo:
        arquivo.writestr(
            "word/document.xml",
            f'<?xml version="1.0"?><w:document {NS}><w:body>{corpo}</w:body></w:document>')
    return memoria.getvalue()


class TestExtratores(unittest.TestCase):
    def test_txt_utf8_e_latin1(self):
        self.assertEqual(extrair_texto("a.txt", "Ação".encode("utf-8")), "Ação")
        self.assertEqual(extrair_texto("a.txt", "Ação".encode("latin-1")), "Ação")

    def test_docx_sem_dependencia(self):
        texto = extrair_texto("peca.docx",
                              docx(["MARIA DOS SANTOS, CPF 529.982.247-25",
                                    "nos termos do art. 71 da CLT."]))
        self.assertIn("529.982.247-25", texto)
        self.assertIn("art. 71 da CLT", texto)

    def test_docx_invalido(self):
        with self.assertRaises(FormatoNaoSuportado):
            extrair_texto("peca.docx", b"isto nao e um zip")

    def test_html_remove_script_e_tags(self):
        texto = extrair_texto(
            "p.html", b"<html><body><p>Autor: Jo&atilde;o</p><script>x=1</script></body></html>")
        self.assertIn("João", texto)
        self.assertNotIn("x=1", texto)

    def test_formato_desconhecido(self):
        with self.assertRaises(FormatoNaoSuportado):
            extrair_texto("peca.zip", b"qualquer coisa")

    def test_normalizacao_nao_quebra_a_deteccao(self):
        # aspas tipográficas e espaço fino vindos de PDF/Word
        texto = extrair_texto("a.txt", "o “autor” João".encode("utf-8"))
        self.assertIn('"autor"', texto)
        self.assertIn("João", texto)


class TestPerfis(unittest.TestCase):
    def test_perfil_de_jurisprudencia_preserva_o_processo(self):
        from anonimizador_juridico import perfis

        texto = ("Processo nº 0001234-02.2023.5.02.0011. O reclamante "
                 "João Pedro Alves, CPF 529.982.247-25, de São Paulo.")
        resultado = perfis.obter("jurisprudencia").construir().processar(texto)
        self.assertIn("0001234-02.2023.5.02.0011", resultado.texto_anonimizado)
        self.assertIn("São Paulo", resultado.texto_anonimizado)
        self.assertNotIn("João Pedro Alves", resultado.texto_anonimizado)
        self.assertNotIn("529.982.247-25", resultado.texto_anonimizado)

    def test_auditor_nao_conta_como_risco_o_que_o_perfil_preserva(self):
        from anonimizador_juridico import perfis

        texto = "Processo nº 0001234-02.2023.5.02.0011, comarca de São Paulo."
        resultado = perfis.obter("jurisprudencia").construir().processar(texto)
        self.assertTrue(resultado.aprovado)
        self.assertIn("escopo", resultado.parecer.verificacoes)

    def test_perfil_de_treinamento_usa_pseudonimo_em_hash(self):
        from anonimizador_juridico import perfis

        resultado = perfis.obter("treinamento").construir().processar(
            "O reclamante João Pedro Alves compareceu.")
        self.assertRegex(resultado.texto_anonimizado, r"\[NOME_[0-9a-f]{6}\]")

    def test_perfil_desconhecido_cai_no_padrao(self):
        from anonimizador_juridico import perfis

        self.assertEqual(perfis.obter("inexistente").chave, "padrao")


if __name__ == "__main__":
    unittest.main()
