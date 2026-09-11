import unittest

from anonimizador_juridico import Pipeline, tipos as T
from anonimizador_juridico.agente_anonimizador import AgenteAnonimizador
from anonimizador_juridico.agente_auditor import AgenteAuditor

PECA = """\
MARIA APARECIDA DOS SANTOS, CPF 529.982.247-25, propõe ação em face de
CONSTRUTORA HORIZONTE LTDA, CNPJ 11.222.333/0001-81.

Segundo o relato, houve conversa entre Pedro Henrique Souza e o gestor do
setor, nos termos do art. 71 da CLT.
"""


class TestPipeline(unittest.TestCase):
    def test_fluxo_feliz(self):
        resultado = Pipeline().processar(PECA, referencia="0001234-02")
        self.assertTrue(resultado.aprovado)
        self.assertNotIn("529.982.247-25", resultado.texto_anonimizado)
        self.assertIn("art. 71 da CLT", resultado.texto_anonimizado)

    def test_auditoria_realimenta_o_anonimizador(self):
        """O anonimizador conservador deixa passar um nome de baixa confiança;
        o auditor (limiar menor) aponta, e a segunda rodada corrige."""
        pipeline = Pipeline(
            anonimizador=AgenteAnonimizador(confianca_minima=0.9),
            auditor=AgenteAuditor(confianca_minima=0.45),
            rodadas_max=3,
        )
        resultado = pipeline.processar(PECA)

        self.assertGreaterEqual(resultado.rodadas, 2)
        self.assertFalse(resultado.historico[0]["aprovado"])
        self.assertNotIn("Pedro Henrique Souza", resultado.texto_anonimizado)
        self.assertTrue(resultado.aprovado)

    def test_para_quando_nao_ha_mais_o_que_corrigir(self):
        # Auditor que reprova sempre, sem apontar trecho corrigível: o laço
        # precisa parar em vez de girar até o limite de rodadas.
        class AuditorTeimoso(AgenteAuditor):
            def auditar(self, texto_anonimizado, texto_original=None, cofre=None):
                return T.Parecer(
                    aprovado=False, nota_risco=50,
                    achados=[T.Achado(categoria="perda_de_conteudo",
                                      tipo="INTEGRIDADE", gravidade=T.ALTA,
                                      descricao="reprova sempre")],
                )

        resultado = Pipeline(auditor=AuditorTeimoso(), rodadas_max=5).processar(PECA)
        self.assertEqual(resultado.rodadas, 1)
        self.assertFalse(resultado.aprovado)

    def test_trilha_de_auditoria(self):
        resultado = Pipeline().processar(PECA, referencia="proc-1")
        trilha = resultado.trilha
        self.assertEqual(trilha["referencia"], "proc-1")
        self.assertEqual(len(trilha["hash_documento_original"]), 64)
        self.assertNotEqual(trilha["hash_documento_original"],
                            trilha["hash_documento_anonimizado"])
        self.assertIn("agente-anonimizador", trilha["agentes"])
        self.assertIn("agente-auditor", trilha["agentes"])

    def test_relatorio_serializavel_sem_dado_pessoal(self):
        import json

        resultado = Pipeline().processar(PECA)
        bruto = json.dumps(resultado.para_dict(), ensure_ascii=False)
        self.assertNotIn("529.982.247-25", bruto)
        self.assertNotIn("MARIA APARECIDA DOS SANTOS", bruto)

    def test_reidentificacao_pelo_cofre_do_pipeline(self):
        pipeline = Pipeline()
        resultado = pipeline.processar(PECA)
        self.assertEqual(pipeline.cofre.reidentificar(resultado.texto_anonimizado),
                         PECA)


if __name__ == "__main__":
    unittest.main()
