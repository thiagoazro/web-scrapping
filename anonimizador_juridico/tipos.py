"""Tipos, enums e estruturas de dados compartilhadas pelos dois agentes."""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

# --------------------------------------------------------------------------- #
# Catálogo de tipos de dado pessoal relevantes em peças judiciais brasileiras
# --------------------------------------------------------------------------- #

CPF = "CPF"
CNPJ = "CNPJ"
RG = "RG"
CNH = "CNH"
PIS = "PIS"
TITULO_ELEITOR = "TITULO_ELEITOR"
CTPS = "CTPS"
PROCESSO_CNJ = "PROCESSO_CNJ"
OAB = "OAB"
EMAIL = "EMAIL"
TELEFONE = "TELEFONE"
CEP = "CEP"
ENDERECO = "ENDERECO"
LOCALIDADE = "LOCALIDADE"
NOME_PESSOA = "NOME_PESSOA"
NOME_EMPRESA = "NOME_EMPRESA"
DATA_NASCIMENTO = "DATA_NASCIMENTO"
CARTAO = "CARTAO"
CONTA_BANCARIA = "CONTA_BANCARIA"
CHAVE_PIX = "CHAVE_PIX"
PLACA_VEICULO = "PLACA_VEICULO"
IP = "IP"
MATRICULA = "MATRICULA"
DADO_SENSIVEL = "DADO_SENSIVEL"  # saúde, religião, orientação sexual, etc. (art. 5º, II LGPD)

TIPOS = (
    CPF, CNPJ, RG, CNH, PIS, TITULO_ELEITOR, CTPS, PROCESSO_CNJ, OAB, EMAIL,
    TELEFONE, CEP, ENDERECO, LOCALIDADE, NOME_PESSOA, NOME_EMPRESA, DATA_NASCIMENTO,
    CARTAO, CONTA_BANCARIA, CHAVE_PIX, PLACA_VEICULO, IP, MATRICULA,
    DADO_SENSIVEL,
)

# Gravidade do vazamento de cada tipo (usada no cálculo de risco do auditor).
CRITICA, ALTA, MEDIA, BAIXA = "critica", "alta", "media", "baixa"

SEVERIDADE: Dict[str, str] = {
    CPF: CRITICA, RG: CRITICA, CNH: CRITICA, PIS: CRITICA,
    TITULO_ELEITOR: CRITICA, CARTAO: CRITICA, CONTA_BANCARIA: CRITICA,
    CHAVE_PIX: CRITICA, DADO_SENSIVEL: CRITICA, CTPS: CRITICA,
    NOME_PESSOA: ALTA, EMAIL: ALTA, TELEFONE: ALTA, ENDERECO: ALTA,
    DATA_NASCIMENTO: ALTA,
    CEP: MEDIA, OAB: MEDIA, LOCALIDADE: MEDIA, PROCESSO_CNJ: MEDIA, PLACA_VEICULO: MEDIA,
    CNPJ: MEDIA, MATRICULA: MEDIA,
    NOME_EMPRESA: BAIXA, IP: BAIXA,
}

PESO_SEVERIDADE = {CRITICA: 40, ALTA: 20, MEDIA: 8, BAIXA: 3}

# Prefixo do pseudônimo gerado para cada tipo.
PREFIXO_TOKEN: Dict[str, str] = {
    CPF: "CPF", CNPJ: "CNPJ", RG: "RG", CNH: "CNH", PIS: "PIS",
    TITULO_ELEITOR: "TITULO", CTPS: "CTPS", PROCESSO_CNJ: "PROCESSO",
    OAB: "OAB", EMAIL: "EMAIL", TELEFONE: "TELEFONE", CEP: "CEP",
    ENDERECO: "ENDERECO", LOCALIDADE: "LOCAL", NOME_PESSOA: "NOME", NOME_EMPRESA: "EMPRESA",
    DATA_NASCIMENTO: "NASCIMENTO", CARTAO: "CARTAO",
    CONTA_BANCARIA: "CONTA", CHAVE_PIX: "PIX", PLACA_VEICULO: "PLACA",
    IP: "IP", MATRICULA: "MATRICULA", DADO_SENSIVEL: "SENSIVEL",
}


def severidade_de(tipo: str) -> str:
    return SEVERIDADE.get(tipo, MEDIA)


def normalizar(valor: str) -> str:
    """Forma canônica de um valor, para que variações grafem o mesmo pseudônimo.

    "João  da Silva", "JOÃO DA SILVA" e "joao da silva" viram a mesma chave;
    "123.456.789-09" e "12345678909" também.
    """
    texto = unicodedata.normalize("NFKD", valor)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = " ".join(texto.split()).strip().lower()
    return texto


def mascarar_para_relatorio(valor: str, visivel: int = 1) -> str:
    """Versão ofuscada de um valor, para que o relatório de auditoria não vaze
    exatamente o dado pessoal que ele está denunciando."""
    if not valor:
        return ""
    cabeca = valor[:visivel]
    return f"{cabeca}{'*' * max(len(valor) - visivel, 1)}"


def impressao_digital(texto: str) -> str:
    """SHA-256 do texto: serve como identificador do documento na trilha de
    auditoria sem que o conteúdo precise ser guardado."""
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# Estruturas de dados
# --------------------------------------------------------------------------- #

@dataclass
class Ocorrencia:
    """Um dado pessoal localizado no texto."""

    tipo: str
    valor: str
    inicio: int
    fim: int
    confianca: float = 1.0
    origem: str = "regra"          # "regra" | "llm" | "propagacao" | "auditor"
    motivo: str = ""

    @property
    def severidade(self) -> str:
        return severidade_de(self.tipo)

    def sobrepoe(self, outra: "Ocorrencia") -> bool:
        return self.inicio < outra.fim and outra.inicio < self.fim

    def para_dict(self, ocultar_valor: bool = True) -> Dict[str, Any]:
        d = asdict(self)
        if ocultar_valor:
            d["valor"] = mascarar_para_relatorio(self.valor)
        d["severidade"] = self.severidade
        return d


@dataclass
class Achado:
    """Um problema apontado pelo agente auditor."""

    categoria: str        # residual | nao_tratado | vazamento_literal | ...
    tipo: str
    gravidade: str
    descricao: str
    trecho: str = ""
    posicao: Optional[int] = None
    origem: str = "regra"
    #: Achado de dado pessoal tem o trecho mascarado no relatório — denunciar
    #: um CPF repetindo o CPF seria absurdo. Já um texto de injeção precisa
    #: aparecer inteiro: quem revisa tem de ler o que o atacante escreveu.
    sigiloso: bool = True

    def para_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if self.sigiloso:
            d["trecho"] = mascarar_para_relatorio(self.trecho)
        return d


@dataclass
class ResultadoAnonimizacao:
    texto_anonimizado: str
    ocorrencias: List[Ocorrencia] = field(default_factory=list)
    texto_original_hash: str = ""
    usou_llm: bool = False
    avisos: List[str] = field(default_factory=list)

    @property
    def total_por_tipo(self) -> Dict[str, int]:
        contagem: Dict[str, int] = {}
        for oc in self.ocorrencias:
            contagem[oc.tipo] = contagem.get(oc.tipo, 0) + 1
        return dict(sorted(contagem.items()))

    def para_dict(self) -> Dict[str, Any]:
        return {
            "hash_original": self.texto_original_hash,
            "usou_llm": self.usou_llm,
            "total_ocorrencias": len(self.ocorrencias),
            "total_por_tipo": self.total_por_tipo,
            "ocorrencias": [o.para_dict() for o in self.ocorrencias],
            "avisos": self.avisos,
        }


@dataclass
class Parecer:
    """Saída do agente auditor."""

    aprovado: bool
    nota_risco: int                      # 0 (limpo) a 100 (vazamento grave)
    achados: List[Achado] = field(default_factory=list)
    recomendacoes: List[str] = field(default_factory=list)
    usou_llm: bool = False
    verificacoes: Dict[str, str] = field(default_factory=dict)

    @property
    def achados_bloqueantes(self) -> List[Achado]:
        return [a for a in self.achados if a.gravidade in (CRITICA, ALTA)]

    @property
    def alertas_de_seguranca(self) -> List[Achado]:
        """Tentativas de manipular sistemas de IA encontradas no documento."""
        return [a for a in self.achados if a.categoria == "tentativa_de_injecao"]

    @property
    def quarentena(self) -> bool:
        """Verdadeiro quando o documento não deve seguir para outro sistema de
        IA sem revisão humana."""
        return bool(self.alertas_de_seguranca)

    def para_dict(self) -> Dict[str, Any]:
        return {
            "aprovado": self.aprovado,
            "nota_risco": self.nota_risco,
            "usou_llm": self.usou_llm,
            "verificacoes": self.verificacoes,
            "total_achados": len(self.achados),
            "achados": [a.para_dict() for a in self.achados],
            "recomendacoes": self.recomendacoes,
            # Campo de primeiro nível: quem integra não precisa vasculhar a
            # lista de achados para saber que o documento está em quarentena.
            "quarentena": self.quarentena,
            "alertas_de_seguranca": [a.para_dict()
                                     for a in self.alertas_de_seguranca],
        }


@dataclass
class ResultadoPipeline:
    texto_anonimizado: str
    parecer: Parecer
    anonimizacao: ResultadoAnonimizacao
    rodadas: int = 1
    historico: List[Dict[str, Any]] = field(default_factory=list)
    trilha: Dict[str, Any] = field(default_factory=dict)

    @property
    def aprovado(self) -> bool:
        return self.parecer.aprovado

    @property
    def quarentena(self) -> bool:
        return self.parecer.quarentena

    def para_dict(self) -> Dict[str, Any]:
        return {
            "aprovado": self.aprovado,
            "quarentena": self.quarentena,
            "rodadas": self.rodadas,
            "anonimizacao": self.anonimizacao.para_dict(),
            "parecer": self.parecer.para_dict(),
            "historico": self.historico,
            "trilha": self.trilha,
        }
