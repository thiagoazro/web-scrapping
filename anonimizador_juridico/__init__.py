"""Anonimizador de peças judiciais com verificação independente.

Dois agentes com papéis separados e um orquestrador que fecha o laço entre eles:

* `AgenteAnonimizador` — remove/pseudonimiza os dados pessoais.
* `AgenteAuditor`      — confere, de forma adversarial, se sobrou algo.
* `Pipeline`           — chama os dois e reprocessa até a peça passar.

Exemplo:

    from anonimizador_juridico import Pipeline

    resultado = Pipeline().processar(texto_da_peca)
    print(resultado.texto_anonimizado)
    print(resultado.parecer.aprovado, resultado.parecer.nota_risco)
"""

from .agente_anonimizador import AgenteAnonimizador
from .agente_auditor import AgenteAuditor
from .cofre import Cofre
from .llm import ClienteClaude
from .orquestrador import VERSAO, Pipeline
from .tipos import Achado, Ocorrencia, Parecer, ResultadoAnonimizacao, ResultadoPipeline

__version__ = VERSAO

__all__ = [
    "AgenteAnonimizador", "AgenteAuditor", "Pipeline", "Cofre", "ClienteClaude",
    "Ocorrencia", "Achado", "Parecer", "ResultadoAnonimizacao",
    "ResultadoPipeline", "VERSAO",
]
