"""O sistema: o orquestrador que coloca os dois agentes para trabalhar juntos.

    texto  ->  [Agente 1: anonimiza]  ->  [Agente 2: audita]  ->  aprovado?
                      ^                                             |
                      |_______ realimenta os trechos vazados ________|

O laço é o ponto central do desenho. A auditoria não serve só para carimbar
"reprovado": os trechos que ela aponta voltam ao anonimizador como entrada
obrigatória, e a peça é reprocessada. Na prática, o que a heurística erra na
primeira rodada costuma ser corrigido na segunda.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

from . import tipos as T
from .agente_anonimizador import AgenteAnonimizador
from .agente_auditor import AgenteAuditor
from .cofre import Cofre
from .llm import ClienteClaude

VERSAO = "1.0.0"


@dataclass
class Pipeline:
    """Sistema de anonimização com verificação independente.

    Uso mínimo:

        pipeline = Pipeline()
        resultado = pipeline.processar(texto_da_peca)
        resultado.texto_anonimizado   # pronto para ir à IA
        resultado.parecer.aprovado    # o que o auditor achou disso

    Para ligar a camada semântica (exige `pip install anthropic` e credencial):

        pipeline = Pipeline.com_llm()
    """

    anonimizador: AgenteAnonimizador = None
    auditor: AgenteAuditor = None
    rodadas_max: int = 3
    parar_no_primeiro_aprovado: bool = True

    def __post_init__(self) -> None:
        if self.anonimizador is None:
            self.anonimizador = AgenteAnonimizador()
        if self.auditor is None:
            self.auditor = AgenteAuditor()

    # ------------------------------------------------------------------ #

    @classmethod
    def com_llm(
        cls,
        modelo: Optional[str] = None,
        esforco: str = "high",
        rodadas_max: int = 3,
        **kwargs,
    ) -> "Pipeline":
        """Pipeline com as duas camadas semânticas ligadas.

        Os dois agentes compartilham o mesmo cliente HTTP, mas fazem chamadas
        independentes, com prompts e papéis diferentes — o auditor nunca vê o
        que o anonimizador "achou que fez".
        """
        cliente = ClienteClaude(**({"modelo": modelo} if modelo else {}),
                               esforco=esforco)
        return cls(
            anonimizador=AgenteAnonimizador(usar_llm=True, cliente=cliente,
                                            cofre=kwargs.pop("cofre", None)),
            auditor=AgenteAuditor(usar_llm=True, cliente=cliente),
            rodadas_max=rodadas_max,
            **kwargs,
        )

    @property
    def cofre(self) -> Cofre:
        return self.anonimizador.cofre

    # ------------------------------------------------------------------ #

    def processar(self, texto: str, referencia: str = "") -> T.ResultadoPipeline:
        inicio = time.time()
        historico: List[Dict] = []
        trechos_forcados: List[str] = []
        tipos_forcados: Dict[str, str] = {}

        anonimizacao = None
        parecer = None

        for rodada in range(1, max(self.rodadas_max, 1) + 1):
            anonimizacao = self.anonimizador.anonimizar(
                texto,
                trechos_forcados=trechos_forcados,
                tipos_forcados=tipos_forcados,
            )
            parecer = self.auditor.auditar(
                anonimizacao.texto_anonimizado,
                texto_original=texto,
                cofre=self.anonimizador.cofre,
            )
            historico.append({
                "rodada": rodada,
                "ocorrencias_tratadas": len(anonimizacao.ocorrencias),
                "por_tipo": anonimizacao.total_por_tipo,
                "aprovado": parecer.aprovado,
                "nota_risco": parecer.nota_risco,
                "achados": len(parecer.achados),
                "avisos": anonimizacao.avisos,
            })

            if parecer.aprovado and self.parar_no_primeiro_aprovado:
                break

            novos = self._trechos_para_reprocessar(parecer, trechos_forcados)
            if not novos:
                # Nada de novo a corrigir: insistir só gastaria tempo e token.
                break
            for trecho, tipo in novos.items():
                trechos_forcados.append(trecho)
                tipos_forcados[trecho] = tipo

        trilha = {
            "versao_sistema": VERSAO,
            "referencia": referencia,
            "momento_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "hash_documento_original": anonimizacao.texto_original_hash,
            "hash_documento_anonimizado": T.impressao_digital(
                anonimizacao.texto_anonimizado),
            "agentes": [self.anonimizador.nome, self.auditor.nome],
            "camada_semantica": {
                "anonimizador": self.anonimizador.usar_llm,
                "auditor": self.auditor.usar_llm,
            },
            "entidades_tratadas": anonimizacao.total_por_tipo,
            "itens_no_cofre": len(self.anonimizador.cofre),
            "duracao_segundos": round(time.time() - inicio, 3),
        }

        return T.ResultadoPipeline(
            texto_anonimizado=anonimizacao.texto_anonimizado,
            parecer=parecer,
            anonimizacao=anonimizacao,
            rodadas=len(historico),
            historico=historico,
            trilha=trilha,
        )

    # ------------------------------------------------------------------ #

    @staticmethod
    def _trechos_para_reprocessar(
        parecer: T.Parecer, ja_forcados: List[str]
    ) -> Dict[str, str]:
        """Converte achados do auditor em ordens de serviço para o anonimizador."""
        alvos: Dict[str, str] = {}
        corrigiveis = {"residual", "vazamento_literal", "semantico"}
        for achado in parecer.achados:
            if achado.categoria not in corrigiveis:
                continue
            trecho = (achado.trecho or "").strip()
            if len(trecho) < 3 or trecho in ja_forcados:
                continue
            tipo = achado.tipo if achado.tipo in T.TIPOS else T.DADO_SENSIVEL
            alvos[trecho] = tipo
        return alvos
