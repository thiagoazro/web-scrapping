import json
import tempfile
import unittest
from pathlib import Path

from anonimizador_juridico.cli import main

PECA = ("MARIA APARECIDA DOS SANTOS, CPF 529.982.247-25, propõe ação "
        "em face de CONSTRUTORA HORIZONTE LTDA, nos termos do art. 71 da CLT.\n")


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.TemporaryDirectory()
        self.base = Path(self.pasta.name)
        self.entrada = self.base / "peca.txt"
        self.entrada.write_text(PECA, encoding="utf-8")
        self.addCleanup(self.pasta.cleanup)

    def test_anonimizar_auditar_reidentificar(self):
        saida = self.base / "peca_anon.txt"
        cofre = self.base / "cofre.json"
        relatorio = self.base / "relatorio.json"

        codigo = main(["anonimizar", "-e", str(self.entrada), "-s", str(saida),
                       "-c", str(cofre), "-r", str(relatorio),
                       "--referencia", "proc-teste"])
        self.assertEqual(codigo, 0)

        anonimizada = saida.read_text(encoding="utf-8")
        self.assertNotIn("529.982.247-25", anonimizada)
        self.assertIn("art. 71 da CLT", anonimizada)

        dados = json.loads(relatorio.read_text(encoding="utf-8"))
        self.assertTrue(dados["aprovado"])
        self.assertEqual(dados["trilha"]["referencia"], "proc-teste")

        # auditoria isolada aprova o arquivo gerado
        self.assertEqual(
            main(["auditar", "-e", str(saida), "--original", str(self.entrada),
                  "-c", str(cofre), "--formato", "json"]), 0)

        # e a reidentificação devolve o documento original
        volta = self.base / "peca_volta.txt"
        self.assertEqual(
            main(["reidentificar", "-e", str(saida), "-c", str(cofre),
                  "-s", str(volta)]), 0)
        self.assertEqual(volta.read_text(encoding="utf-8"), PECA)

    def test_auditar_texto_sujo_retorna_codigo_de_erro(self):
        sujo = self.base / "sujo.txt"
        sujo.write_text("Contato do autor: joao@exemplo.com", encoding="utf-8")
        self.assertEqual(main(["auditar", "-e", str(sujo)]), 2)

    def test_reidentificar_sem_cofre_falha(self):
        self.assertEqual(main(["reidentificar", "-e", str(self.entrada),
                               "-c", str(self.base / "inexistente.json")]), 1)


if __name__ == "__main__":
    unittest.main()
