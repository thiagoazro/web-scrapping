"""Perfis prontos de anonimização.

Cada tipo de uso pede um ajuste diferente. Publicar um modelo de petição no
site do escritório não é a mesma coisa que alimentar um índice de
jurisprudência interno, que não é a mesma coisa que montar base para treinar
modelo. Em vez de obrigar quem usa a escolher limiar de confiança e lista de
tipos, o sistema entrega quatro configurações nomeadas — e a interface só
mostra o nome.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from . import tipos as T
from .agente_anonimizador import AgenteAnonimizador
from .agente_auditor import AgenteAuditor
from .cofre import Cofre
from .llm import ClienteClaude
from .orquestrador import Pipeline


@dataclass(frozen=True)
class Perfil:
    chave: str
    nome: str
    descricao: str
    quando_usar: str
    tipos_ignorados: Set[str] = field(default_factory=set)
    confianca_anonimizador: float = 0.5
    confianca_auditor: float = 0.45
    estilo_token: str = "sequencial"
    rodadas: int = 3

    def construir(
        self,
        usar_llm: bool = False,
        cofre: Optional[Cofre] = None,
        cliente: Optional[ClienteClaude] = None,
        modelo: Optional[str] = None,
        esforco: str = "high",
    ) -> Pipeline:
        """Monta o pipeline já configurado com este perfil."""
        if usar_llm and cliente is None:
            cliente = ClienteClaude(**({"modelo": modelo} if modelo else {}),
                                    esforco=esforco)
        return Pipeline(
            anonimizador=AgenteAnonimizador(
                cofre=cofre if cofre is not None else Cofre(estilo=self.estilo_token),
                confianca_minima=self.confianca_anonimizador,
                tipos_ignorados=self.tipos_ignorados,
                usar_llm=usar_llm,
                cliente=cliente,
            ),
            auditor=AgenteAuditor(
                confianca_minima=self.confianca_auditor,
                tipos_fora_de_escopo=self.tipos_ignorados,
                usar_llm=usar_llm,
                cliente=cliente,
            ),
            rodadas_max=self.rodadas,
        )

    def para_dict(self) -> Dict:
        return {
            "chave": self.chave,
            "nome": self.nome,
            "descricao": self.descricao,
            "quando_usar": self.quando_usar,
            "tipos_preservados": sorted(self.tipos_ignorados),
            "estilo_token": self.estilo_token,
        }


PERFIS: Dict[str, Perfil] = {
    "padrao": Perfil(
        chave="padrao",
        nome="Padrão",
        descricao=(
            "Remove todo dado pessoal detectável, preservando conteúdo "
            "jurídico, valores e datas processuais."
        ),
        quando_usar="Uso geral: enviar a peça para uma IA analisar ou resumir.",
    ),
    "estrito": Perfil(
        chave="estrito",
        nome="Estrito (LGPD máxima)",
        descricao=(
            "Limiar de detecção mais baixo nos dois agentes e mais rodadas de "
            "correção. Anonimiza mais, erra mais para o lado seguro."
        ),
        quando_usar=(
            "Dado que sai da sua infraestrutura, publicação externa ou "
            "compartilhamento com terceiros."
        ),
        confianca_anonimizador=0.45,
        confianca_auditor=0.4,
        rodadas=4,
    ),
    "jurisprudencia": Perfil(
        chave="jurisprudencia",
        nome="Pesquisa de jurisprudência",
        descricao=(
            "Preserva número do processo, comarca e razão social — o que "
            "permite localizar e citar a decisão — e remove as pessoas físicas."
        ),
        quando_usar=(
            "Índice interno de decisões, banco de teses, busca de precedentes."
        ),
        tipos_ignorados={T.PROCESSO_CNJ, T.LOCALIDADE, T.NOME_EMPRESA, T.OAB},
    ),
    "treinamento": Perfil(
        chave="treinamento",
        nome="Base para treinar/indexar IA",
        descricao=(
            "Remove tudo, inclusive processo e localidade, com pseudônimo em "
            "hash: o mesmo CPF vira o mesmo marcador em processos diferentes, "
            "o que permite cruzar casos sem reidentificar ninguém."
        ),
        quando_usar="Montar corpus, fine-tuning, RAG sobre acervo próprio.",
        confianca_anonimizador=0.45,
        confianca_auditor=0.4,
        estilo_token="hash",
        rodadas=4,
    ),
}

PERFIL_PADRAO = "padrao"


def obter(chave: Optional[str]) -> Perfil:
    return PERFIS.get(chave or PERFIL_PADRAO, PERFIS[PERFIL_PADRAO])


def listar() -> List[Dict]:
    return [perfil.para_dict() for perfil in PERFIS.values()]
