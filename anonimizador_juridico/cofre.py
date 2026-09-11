"""Cofre de pseudônimos: a ponte entre o texto anonimizado e o dado real.

Guarda o mapa `pseudônimo -> valor original`. Sem ele a anonimização é
irreversível (o que às vezes é exatamente o que se quer); com ele, é
*pseudonimização* reversível pelo controlador — a distinção do art. 12 da LGPD.

ATENÇÃO: o arquivo do cofre é tão sensível quanto o documento original.
Guarde-o separado do texto anonimizado e, de preferência, cifrado (`senha=`).
"""

from __future__ import annotations

import base64
import hmac
import json
import os
import secrets
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Dict, Optional

from . import tipos as T

VARIAVEL_CHAVE = "ANONIMIZADOR_CHAVE"


@dataclass
class Entrada:
    token: str
    tipo: str
    valor: str
    digest: str
    ocorrencias: int = 0


@dataclass
class Cofre:
    """Mapa bidirecional entre valores reais e pseudônimos.

    `estilo="sequencial"` gera `[NOME_001]` (legível).
    `estilo="hash"` gera `[NOME_3f9c1a]` — estável entre execuções e entre
    documentos diferentes, o que permite cruzar processos sem reidentificar.
    """

    estilo: str = "sequencial"
    chave_secreta: bytes = field(default_factory=lambda: _chave_do_ambiente())
    _por_digest: Dict[str, Entrada] = field(default_factory=dict)
    _por_token: Dict[str, Entrada] = field(default_factory=dict)
    _contador: Dict[str, int] = field(default_factory=dict)

    # -- identidade ---------------------------------------------------------

    #: Tipos em que a pontuação é irrelevante: "529.982.247-25" e
    #: "52998224725" são o mesmo CPF e precisam do mesmo pseudônimo.
    TIPOS_NUMERICOS = frozenset({
        T.CPF, T.CNPJ, T.RG, T.CNH, T.PIS, T.TITULO_ELEITOR, T.CTPS,
        T.PROCESSO_CNJ, T.CEP, T.TELEFONE, T.CARTAO, T.CONTA_BANCARIA,
        T.MATRICULA,
    })

    def _canonico(self, tipo: str, valor: str) -> str:
        if tipo in self.TIPOS_NUMERICOS:
            digitos = "".join(c for c in valor if c.isdigit())
            if digitos:
                return digitos
        return T.normalizar(valor)

    def digest(self, tipo: str, valor: str) -> str:
        chave = f"{tipo}|{self._canonico(tipo, valor)}".encode("utf-8")
        return hmac.new(self.chave_secreta, chave, sha256).hexdigest()

    def token_para(self, tipo: str, valor: str) -> str:
        """Devolve (criando se preciso) o pseudônimo estável deste valor."""
        dig = self.digest(tipo, valor)
        entrada = self._por_digest.get(dig)
        if entrada is None:
            prefixo = T.PREFIXO_TOKEN.get(tipo, tipo)
            if self.estilo == "hash":
                token = f"[{prefixo}_{dig[:6]}]"
            else:
                self._contador[tipo] = self._contador.get(tipo, 0) + 1
                token = f"[{prefixo}_{self._contador[tipo]:03d}]"
            entrada = Entrada(token=token, tipo=tipo, valor=valor, digest=dig)
            self._por_digest[dig] = entrada
            self._por_token[token] = entrada
        entrada.ocorrencias += 1
        return entrada.token

    def valor_de(self, token: str) -> Optional[str]:
        entrada = self._por_token.get(token)
        return entrada.valor if entrada else None

    def __len__(self) -> int:
        return len(self._por_token)

    @property
    def entradas(self) -> Dict[str, Entrada]:
        return dict(self._por_token)

    # -- reidentificação ----------------------------------------------------

    def reidentificar(self, texto: str) -> str:
        """Operação inversa. Só deve ser executada por quem tem base legal
        para ver o dado original — registre sempre o motivo no seu log."""
        for token, entrada in sorted(self._por_token.items(),
                                     key=lambda kv: -len(kv[0])):
            texto = texto.replace(token, entrada.valor)
        return texto

    # -- persistência -------------------------------------------------------

    def para_json(self) -> str:
        payload = {
            "versao": 1,
            "estilo": self.estilo,
            "chave_secreta": base64.b64encode(self.chave_secreta).decode(),
            "contador": self._contador,
            "entradas": [
                {"token": e.token, "tipo": e.tipo, "valor": e.valor,
                 "digest": e.digest, "ocorrencias": e.ocorrencias}
                for e in self._por_token.values()
            ],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    @classmethod
    def de_json(cls, bruto: str) -> "Cofre":
        payload = json.loads(bruto)
        cofre = cls(
            estilo=payload.get("estilo", "sequencial"),
            chave_secreta=base64.b64decode(payload["chave_secreta"]),
        )
        cofre._contador = {k: int(v) for k, v in payload.get("contador", {}).items()}
        for item in payload.get("entradas", []):
            entrada = Entrada(**item)
            cofre._por_digest[entrada.digest] = entrada
            cofre._por_token[entrada.token] = entrada
        return cofre

    def salvar(self, caminho: os.PathLike | str, senha: Optional[str] = None) -> Path:
        destino = Path(caminho)
        bruto = self.para_json()
        if senha:
            conteudo = _cifrar(bruto, senha)
        else:
            conteudo = bruto.encode("utf-8")
        destino.write_bytes(conteudo)
        try:
            destino.chmod(0o600)  # o cofre não é para leitura geral
        except OSError:  # sistemas de arquivos sem suporte a permissões POSIX
            pass
        return destino

    @classmethod
    def carregar(cls, caminho: os.PathLike | str,
                 senha: Optional[str] = None) -> "Cofre":
        conteudo = Path(caminho).read_bytes()
        if senha:
            return cls.de_json(_decifrar(conteudo, senha))
        return cls.de_json(conteudo.decode("utf-8"))


def _chave_do_ambiente() -> bytes:
    """Usa ANONIMIZADOR_CHAVE quando definida — é o que faz o mesmo CPF virar
    o mesmo pseudônimo em execuções e documentos diferentes."""
    bruto = os.environ.get(VARIAVEL_CHAVE)
    if bruto:
        return bruto.encode("utf-8")
    return secrets.token_bytes(32)


# --------------------------------------------------------------------------- #
# Cifragem opcional do cofre (usa `cryptography` se instalada)
# --------------------------------------------------------------------------- #

_PREFIXO_CIFRADO = b"ANONv1:"


def _fernet(senha: str, sal: bytes):
    try:
        from cryptography.fernet import Fernet
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    except BaseException as erro:  # o pacote pode estar ausente ou quebrado
        raise RuntimeError(
            "Cifragem do cofre exige o pacote `cryptography` em funcionamento "
            f"(`pip install --upgrade cryptography`). Detalhe: {erro}"
        ) from None

    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=sal,
                     iterations=480_000)
    return Fernet(base64.urlsafe_b64encode(kdf.derive(senha.encode("utf-8"))))


def _cifrar(texto: str, senha: str) -> bytes:
    sal = secrets.token_bytes(16)
    return _PREFIXO_CIFRADO + base64.b64encode(sal) + b":" + \
        _fernet(senha, sal).encrypt(texto.encode("utf-8"))


def _decifrar(conteudo: bytes, senha: str) -> str:
    if not conteudo.startswith(_PREFIXO_CIFRADO):
        raise ValueError("Arquivo de cofre não está cifrado (não passe --senha).")
    corpo = conteudo[len(_PREFIXO_CIFRADO):]
    sal_b64, _, cifrado = corpo.partition(b":")
    sal = base64.b64decode(sal_b64)
    return _fernet(senha, sal).decrypt(cifrado).decode("utf-8")
