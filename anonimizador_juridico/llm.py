"""Camada semântica: chamada ao Claude para o que regex não alcança.

Regex acha CPF. Só um modelo de linguagem acha "a filha mais nova do
reclamante, que trabalhava no mesmo setor" — referência indireta que
reidentifica uma pessoa sem citar um único número.

Toda a camada é opcional: sem `anthropic` instalado ou sem credencial, os
agentes continuam funcionando apenas com a camada determinística e registram
um aviso no relatório.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

MODELO_PADRAO = os.environ.get("ANONIMIZADOR_MODELO", "claude-opus-5")
BETA_FALLBACK = "server-side-fallback-2026-07-01"


class RespostaRecusada(RuntimeError):
    """O modelo recusou a requisição (stop_reason == 'refusal')."""


class ClienteClaude:
    """Envelope fino sobre o SDK oficial, com saída estruturada em JSON."""

    def __init__(
        self,
        modelo: str = MODELO_PADRAO,
        api_key: Optional[str] = None,
        esforco: str = "high",
        max_tokens: int = 16000,
        timeout: float = 600.0,
    ) -> None:
        self.modelo = modelo
        self.esforco = esforco
        self.max_tokens = max_tokens
        self.erro_inicializacao: Optional[str] = None
        self._cliente = None
        try:
            import anthropic
        except ImportError:
            self.erro_inicializacao = (
                "pacote `anthropic` não instalado (pip install anthropic)"
            )
            return
        try:
            self._anthropic = anthropic
            self._cliente = anthropic.Anthropic(api_key=api_key, timeout=timeout)
        except Exception as erro:  # credencial ausente, por exemplo
            self.erro_inicializacao = f"não foi possível criar o cliente: {erro}"

    @property
    def disponivel(self) -> bool:
        return self._cliente is not None

    # ---------------------------------------------------------------- #

    def extrair_json(
        self,
        sistema: str,
        conteudo: str,
        schema: Dict[str, Any],
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Uma requisição, uma resposta JSON validada contra `schema`."""
        if not self.disponivel:
            raise RuntimeError(f"Claude indisponível: {self.erro_inicializacao}")

        parametros: Dict[str, Any] = dict(
            model=self.modelo,
            max_tokens=max_tokens or self.max_tokens,
            system=[{"type": "text", "text": sistema,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": conteudo}],
            thinking={"type": "adaptive"},
            output_config={
                "effort": self.esforco,
                "format": {"type": "json_schema", "schema": schema},
            },
        )

        try:
            # `fallbacks` reencaminha a requisição automaticamente se um
            # classificador de segurança recusar — peça judicial tem conteúdo
            # sensível e uma recusa pararia o pipeline no meio.
            resposta = self._cliente.beta.messages.create(
                betas=[BETA_FALLBACK], fallbacks="default", **parametros
            )
        except Exception:
            resposta = self._cliente.messages.create(**parametros)

        if getattr(resposta, "stop_reason", None) == "refusal":
            detalhe = getattr(resposta, "stop_details", None)
            raise RespostaRecusada(
                f"o modelo recusou a requisição ({getattr(detalhe, 'category', '?')})"
            )

        texto = "".join(
            bloco.text for bloco in resposta.content
            if getattr(bloco, "type", None) == "text"
        ).strip()
        if not texto:
            raise RuntimeError("resposta vazia do modelo")
        return json.loads(texto)


# --------------------------------------------------------------------------- #
# Contratos de saída (JSON Schema) usados pelos dois agentes
# --------------------------------------------------------------------------- #

SCHEMA_DETECCAO: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "entidades": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "trecho": {
                        "type": "string",
                        "description": "o texto EXATO como aparece no documento",
                    },
                    "tipo": {"type": "string"},
                    "confianca": {"type": "number"},
                    "motivo": {"type": "string"},
                },
                "required": ["trecho", "tipo", "confianca", "motivo"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["entidades"],
    "additionalProperties": False,
}

SCHEMA_AUDITORIA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "identificavel": {"type": "boolean"},
        "achados": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "trecho": {"type": "string"},
                    "tipo": {"type": "string"},
                    "gravidade": {
                        "type": "string",
                        "enum": ["critica", "alta", "media", "baixa"],
                    },
                    "descricao": {"type": "string"},
                },
                "required": ["trecho", "tipo", "gravidade", "descricao"],
                "additionalProperties": False,
            },
        },
        "recomendacoes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["identificavel", "achados", "recomendacoes"],
    "additionalProperties": False,
}
