"""Extração de texto dos formatos em que uma peça costuma chegar.

.txt e .docx funcionam sem dependência nenhuma (um .docx é um zip com XML
dentro). .html usa BeautifulSoup se estiver instalado e cai num limpador
próprio se não estiver. .pdf exige uma biblioteca externa — e, se o PDF for
digitalizado, exige OCR, que este projeto não faz e avisa em vez de fingir.
"""

from __future__ import annotations

import html as _html
import re
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Set

EXTENSOES_SUPORTADAS: Set[str] = {".txt", ".md", ".text", ".docx", ".html", ".htm", ".pdf"}

_NS_WORD = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class FormatoNaoSuportado(ValueError):
    pass


def extrair_texto(nome: str, conteudo: bytes) -> str:
    """Devolve o texto puro de um arquivo, escolhendo o extrator pela extensão."""
    extensao = Path(nome).suffix.lower()
    if extensao in (".txt", ".md", ".text", ""):
        return _limpar(_decodificar(conteudo))
    if extensao == ".docx":
        return _limpar(_de_docx(conteudo))
    if extensao in (".html", ".htm"):
        return _limpar(_de_html(_decodificar(conteudo)))
    if extensao == ".pdf":
        return _limpar(_de_pdf(conteudo))
    raise FormatoNaoSuportado(
        f"formato '{extensao or nome}' não suportado — "
        f"envie {', '.join(sorted(EXTENSOES_SUPORTADAS))}"
    )


# --------------------------------------------------------------------------- #

def _decodificar(conteudo: bytes) -> str:
    for codificacao in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return conteudo.decode(codificacao)
        except UnicodeDecodeError:
            continue
    return conteudo.decode("utf-8", errors="replace")


def _de_docx(conteudo: bytes) -> str:
    """Um .docx é um zip; o texto vive em word/document.xml."""
    try:
        with zipfile.ZipFile(BytesIO(conteudo)) as arquivo:
            xml = arquivo.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError) as erro:
        raise FormatoNaoSuportado(f"arquivo .docx inválido ({erro})") from None

    raiz = ET.fromstring(xml)
    linhas = []
    for paragrafo in raiz.iter(f"{_NS_WORD}p"):
        pedacos = [no.text or "" for no in paragrafo.iter(f"{_NS_WORD}t")]
        # <w:br/> e <w:tab/> viram espaço em branco significativo
        linhas.append("".join(pedacos))
    return "\n".join(linhas)


def _de_html(bruto: str) -> str:
    try:
        from bs4 import BeautifulSoup  # opcional
    except ImportError:
        semtag = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", bruto)
        semtag = re.sub(r"(?s)<br\s*/?>|</p>|</div>|</tr>", "\n", semtag)
        semtag = re.sub(r"(?s)<[^>]+>", " ", semtag)
        return _html.unescape(semtag)
    sopa = BeautifulSoup(bruto, "html.parser")
    for etiqueta in sopa(["script", "style"]):
        etiqueta.decompose()
    return sopa.get_text("\n")


def _de_pdf(conteudo: bytes) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        try:
            from PyPDF2 import PdfReader  # type: ignore
        except ImportError:
            raise FormatoNaoSuportado(
                "leitura de PDF exige `pip install pypdf`. Se o PDF for "
                "digitalizado (imagem), é preciso OCR antes — converta para "
                ".txt e envie de novo."
            ) from None

    leitor = PdfReader(BytesIO(conteudo))
    paginas = [(pagina.extract_text() or "") for pagina in leitor.pages]
    texto = "\n\n".join(paginas)
    if not texto.strip():
        raise FormatoNaoSuportado(
            "o PDF não tem camada de texto (provavelmente é digitalizado): "
            "passe um OCR antes de anonimizar"
        )
    return texto


def _limpar(texto: str) -> str:
    """Normaliza o que costuma quebrar regex em texto vindo de PDF e Word."""
    texto = unicodedata.normalize("NFC", texto)
    texto = texto.replace("\r\n", "\n").replace("\r", "\n")
    texto = texto.replace(" ", " ").replace("​", "")
    # aspas e travessões tipográficos atrapalham o casamento literal de trechos
    for origem, destino in (("‘", "'"), ("’", "'"),
                            ("“", '"'), ("”", '"')):
        texto = texto.replace(origem, destino)
    texto = re.sub(r"[ \t]+\n", "\n", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()
