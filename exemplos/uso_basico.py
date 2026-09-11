"""Três formas de usar o sistema. Rode: python exemplos/uso_basico.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from anonimizador_juridico import AgenteAnonimizador, AgenteAuditor, Pipeline

PECA = Path(__file__).with_name("peticao_exemplo.txt").read_text(encoding="utf-8")


def exemplo_1_pipeline_completo():
    """O caminho normal: os dois agentes, com realimentação automática."""
    pipeline = Pipeline()
    resultado = pipeline.processar(PECA, referencia="0001234-02.2023.5.02.0011")

    print(resultado.texto_anonimizado[:400], "...\n")
    print("aprovado:", resultado.aprovado,
          "| risco:", resultado.parecer.nota_risco,
          "| rodadas:", resultado.rodadas)
    print("entidades tratadas:", resultado.anonimizacao.total_por_tipo)

    # O cofre é o que permite voltar atrás — guarde-o separado da peça.
    pipeline.cofre.salvar("/tmp/cofre_exemplo.json")


def exemplo_2_agentes_separados():
    """Os agentes são independentes: dá para usar só um deles."""
    anonimizador = AgenteAnonimizador()
    anonimizado = anonimizador.anonimizar(PECA)

    # O auditor também roda "às cegas", sobre um texto anonimizado por
    # terceiros, sem ver o original e sem cofre nenhum.
    parecer = AgenteAuditor().auditar(anonimizado.texto_anonimizado)
    print("achados na verificação cega:", len(parecer.achados))


def exemplo_3_com_claude():
    """Com a camada semântica ligada (exige `pip install anthropic` e a
    variável ANTHROPIC_API_KEY). Sem credencial, o sistema avisa e segue
    apenas com a camada determinística."""
    resultado = Pipeline.com_llm(esforco="high").processar(PECA)
    print("camada semântica usada:", resultado.anonimizacao.usou_llm,
          "| avisos:", resultado.anonimizacao.avisos)


if __name__ == "__main__":
    exemplo_1_pipeline_completo()
    print("\n" + "-" * 70 + "\n")
    exemplo_2_agentes_separados()
    print("\n" + "-" * 70 + "\n")
    exemplo_3_com_claude()
