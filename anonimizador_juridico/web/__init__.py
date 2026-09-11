"""Interface web local do anonimizador (biblioteca padrão, sem framework)."""

from .servidor import criar_servidor, servir

__all__ = ["criar_servidor", "servir"]
