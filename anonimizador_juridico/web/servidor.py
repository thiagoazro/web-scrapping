"""Servidor HTTP da interface — `python -m anonimizador_juridico servir`.

Escrito sobre `http.server` da biblioteca padrão de propósito: um escritório
consegue rodar isto num notebook, sem instalar framework, sem Docker e, acima
de tudo, **sem mandar peça judicial para fora**. Por padrão escuta apenas em
127.0.0.1 — a máquina só fala com ela mesma.

Decisões de segurança que valem por documentação:

* o cofre de pseudônimos vive só na memória do processo; fechar o servidor
  apaga a possibilidade de reidentificar. Quem precisa guardar, baixa o arquivo
  conscientemente.
* o texto original nunca é gravado em disco pelo servidor.
* `--token` protege a instância quando ela precisa sair do localhost.
"""

from __future__ import annotations

import base64
import binascii
import hmac
import json
import secrets
import threading
import time
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from .. import perfis as _perfis
from .. import tipos as T
from ..agente_auditor import AgenteAuditor
from ..cofre import Cofre
from ..extratores import EXTENSOES_SUPORTADAS, FormatoNaoSuportado, extrair_texto
from ..llm import ClienteClaude
from ..orquestrador import VERSAO

TAMANHO_MAXIMO = 25 * 1024 * 1024          # 25 MB por requisição
VALIDADE_SESSAO = 60 * 60 * 4              # 4 horas
PAGINA = Path(__file__).with_name("static") / "index.html"


@dataclass
class Sessao:
    """Uma sessão de trabalho: um cofre compartilhado por vários documentos.

    É o que faz a mesma pessoa receber o mesmo pseudônimo em todas as peças do
    mesmo processo enviadas juntas.
    """

    identificador: str
    cofre: Cofre
    perfil: str
    criada_em: float = field(default_factory=time.time)
    documentos: List[Dict[str, Any]] = field(default_factory=list)


class Repositorio:
    """Sessões em memória, com expiração. Nada toca o disco."""

    def __init__(self, validade: int = VALIDADE_SESSAO) -> None:
        self._sessoes: Dict[str, Sessao] = {}
        self._trava = threading.Lock()
        self.validade = validade

    def abrir(self, perfil: str, estilo: str) -> Sessao:
        self._expirar()
        sessao = Sessao(identificador=secrets.token_urlsafe(12),
                        cofre=Cofre(estilo=estilo), perfil=perfil)
        with self._trava:
            self._sessoes[sessao.identificador] = sessao
        return sessao

    def obter(self, identificador: Optional[str]) -> Optional[Sessao]:
        self._expirar()
        with self._trava:
            return self._sessoes.get(identificador or "")

    def descartar(self, identificador: str) -> bool:
        with self._trava:
            return self._sessoes.pop(identificador, None) is not None

    def _expirar(self) -> None:
        limite = time.time() - self.validade
        with self._trava:
            for chave in [k for k, s in self._sessoes.items()
                          if s.criada_em < limite]:
                del self._sessoes[chave]


class Manipulador(BaseHTTPRequestHandler):
    server_version = f"AnonimizadorJuridico/{VERSAO}"
    repositorio: Repositorio
    token: Optional[str] = None
    usar_llm_padrao: bool = False

    # -- infraestrutura ------------------------------------------------- #

    def log_message(self, formato: str, *args) -> None:
        # Log sem corpo de requisição: peça judicial não vai para o terminal.
        print(f"[web] {self.address_string()} {formato % args}")

    def _responder(self, dados: Any, status: int = HTTPStatus.OK) -> None:
        corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(corpo)

    def _erro(self, mensagem: str, status: int = HTTPStatus.BAD_REQUEST) -> None:
        self._responder({"erro": mensagem}, status)

    def _autorizado(self) -> bool:
        if not self.token:
            return True
        enviado = self.headers.get("X-Token") or \
            parse_qs(urlparse(self.path).query).get("token", [""])[0]
        return hmac.compare_digest(enviado, self.token)

    def _corpo_json(self) -> Dict[str, Any]:
        tamanho = int(self.headers.get("Content-Length") or 0)
        if tamanho > TAMANHO_MAXIMO:
            raise ValueError(
                f"requisição de {tamanho // 1024 // 1024} MB excede o limite de "
                f"{TAMANHO_MAXIMO // 1024 // 1024} MB"
            )
        if tamanho <= 0:
            return {}
        return json.loads(self.rfile.read(tamanho).decode("utf-8"))

    # -- rotas ----------------------------------------------------------- #

    def do_GET(self) -> None:  # noqa: N802 (nome exigido pela BaseHTTPRequestHandler)
        rota = urlparse(self.path).path
        if rota in ("/", "/index.html"):
            return self._pagina()
        if not self._autorizado():
            return self._erro("token inválido", HTTPStatus.UNAUTHORIZED)
        if rota == "/api/estado":
            return self._estado()
        if rota == "/api/cofre":
            return self._baixar_cofre()
        return self._erro("rota não encontrada", HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        if not self._autorizado():
            return self._erro("token inválido", HTTPStatus.UNAUTHORIZED)
        rota = urlparse(self.path).path
        try:
            corpo = self._corpo_json()
        except ValueError as erro:
            return self._erro(str(erro), HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        except json.JSONDecodeError:
            return self._erro("corpo da requisição não é JSON válido")

        try:
            if rota == "/api/anonimizar":
                return self._anonimizar(corpo)
            if rota == "/api/auditar":
                return self._auditar(corpo)
            if rota == "/api/reidentificar":
                return self._reidentificar(corpo)
            if rota == "/api/encerrar":
                return self._encerrar(corpo)
        except Exception as erro:  # nunca derruba o servidor por um documento
            return self._erro(f"{type(erro).__name__}: {erro}",
                              HTTPStatus.INTERNAL_SERVER_ERROR)
        return self._erro("rota não encontrada", HTTPStatus.NOT_FOUND)

    # -- implementações --------------------------------------------------- #

    def _pagina(self) -> None:
        try:
            corpo = PAGINA.read_bytes()
        except OSError:
            return self._erro("página não encontrada", HTTPStatus.NOT_FOUND)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def _estado(self) -> None:
        cliente = ClienteClaude()
        self._responder({
            "versao": VERSAO,
            "perfis": _perfis.listar(),
            "formatos": sorted(EXTENSOES_SUPORTADAS),
            "llm": {
                "disponivel": cliente.disponivel,
                "motivo": cliente.erro_inicializacao,
                "padrao": self.usar_llm_padrao,
            },
        })

    def _anonimizar(self, corpo: Dict[str, Any]) -> None:
        documentos = self._reunir_documentos(corpo)
        if not documentos:
            return self._erro("nenhum documento enviado")

        perfil = _perfis.obter(corpo.get("perfil"))
        usar_llm = bool(corpo.get("usar_llm", self.usar_llm_padrao))

        sessao = self.repositorio.obter(corpo.get("sessao"))
        if sessao is None:
            sessao = self.repositorio.abrir(perfil.chave, perfil.estilo_token)

        # Um pipeline por lote, com o cofre da sessão: documentos enviados
        # juntos compartilham os mesmos pseudônimos.
        pipeline = perfil.construir(usar_llm=usar_llm, cofre=sessao.cofre)

        saida = []
        for nome, texto, erro in documentos:
            if erro:
                saida.append({"nome": nome, "erro": erro})
                continue
            resultado = pipeline.processar(texto, referencia=nome)
            registro = {
                "nome": nome,
                "aprovado": resultado.aprovado,
                "nota_risco": resultado.parecer.nota_risco,
                "rodadas": resultado.rodadas,
                "caracteres": len(texto),
                "texto_anonimizado": resultado.texto_anonimizado,
                "relatorio": resultado.para_dict(),
            }
            sessao.documentos.append({"nome": nome,
                                      "hash": resultado.trilha["hash_documento_original"]})
            saida.append(registro)

        self._responder({
            "sessao": sessao.identificador,
            "perfil": perfil.para_dict(),
            "usou_llm": any(d.get("relatorio", {})
                            .get("anonimizacao", {}).get("usou_llm")
                            for d in saida),
            "itens_no_cofre": len(sessao.cofre),
            "documentos": saida,
        })

    def _auditar(self, corpo: Dict[str, Any]) -> None:
        documentos = self._reunir_documentos(corpo)
        if not documentos:
            return self._erro("nenhum documento enviado")
        perfil = _perfis.obter(corpo.get("perfil"))
        auditor = AgenteAuditor(
            confianca_minima=perfil.confianca_auditor,
            tipos_fora_de_escopo=perfil.tipos_ignorados,
            usar_llm=bool(corpo.get("usar_llm", False)),
        )
        sessao = self.repositorio.obter(corpo.get("sessao"))
        saida = []
        for nome, texto, erro in documentos:
            if erro:
                saida.append({"nome": nome, "erro": erro})
                continue
            parecer = auditor.auditar(texto,
                                      cofre=sessao.cofre if sessao else None)
            saida.append({"nome": nome, "aprovado": parecer.aprovado,
                          "nota_risco": parecer.nota_risco,
                          "relatorio": {"parecer": parecer.para_dict()}})
        self._responder({"documentos": saida, "perfil": perfil.para_dict()})

    def _reidentificar(self, corpo: Dict[str, Any]) -> None:
        sessao = self.repositorio.obter(corpo.get("sessao"))
        if sessao is None:
            return self._erro(
                "sessão não encontrada — sem o cofre não há reidentificação, "
                "e é assim que deve ser", HTTPStatus.NOT_FOUND)
        texto = corpo.get("texto") or ""
        self._responder({"texto": sessao.cofre.reidentificar(texto),
                         "aviso": "registre a base legal e o responsável por "
                                  "esta reidentificação"})

    def _encerrar(self, corpo: Dict[str, Any]) -> None:
        identificador = corpo.get("sessao") or ""
        apagada = self.repositorio.descartar(identificador)
        self._responder({"encerrada": apagada,
                         "aviso": "o cofre foi apagado da memória; o texto "
                                  "anonimizado tornou-se irreversível"})

    def _baixar_cofre(self) -> None:
        consulta = parse_qs(urlparse(self.path).query)
        sessao = self.repositorio.obter(consulta.get("sessao", [""])[0])
        if sessao is None:
            return self._erro("sessão não encontrada", HTTPStatus.NOT_FOUND)
        corpo = sessao.cofre.para_json().encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Disposition",
                         f'attachment; filename="cofre_{sessao.identificador}.json"')
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    # -- entrada ---------------------------------------------------------- #

    @staticmethod
    def _reunir_documentos(corpo: Dict[str, Any]):
        """Aceita texto colado e/ou arquivos em base64. Devolve trincas
        (nome, texto, erro) — um arquivo problemático não aborta o lote."""
        documentos = []
        texto_colado = (corpo.get("texto") or "").strip()
        if texto_colado:
            documentos.append((corpo.get("nome") or "texto-colado", texto_colado, None))

        for arquivo in corpo.get("arquivos") or []:
            nome = arquivo.get("nome") or "documento"
            try:
                bruto = base64.b64decode(arquivo.get("conteudo") or "", validate=True)
            except (binascii.Error, ValueError):
                documentos.append((nome, "", "conteúdo do arquivo inválido"))
                continue
            try:
                texto = extrair_texto(nome, bruto)
            except FormatoNaoSuportado as erro:
                documentos.append((nome, "", str(erro)))
                continue
            if not texto.strip():
                documentos.append((nome, "", "arquivo sem texto legível"))
                continue
            documentos.append((nome, texto, None))
        return documentos


def criar_servidor(host: str = "127.0.0.1", porta: int = 8765,
                   token: Optional[str] = None,
                   usar_llm: bool = False) -> ThreadingHTTPServer:
    classe = type("ManipuladorConfigurado", (Manipulador,), {
        "repositorio": Repositorio(),
        "token": token,
        "usar_llm_padrao": usar_llm,
    })
    return ThreadingHTTPServer((host, porta), classe)


def servir(host: str = "127.0.0.1", porta: int = 8765,
           token: Optional[str] = None, usar_llm: bool = False) -> None:
    servidor = criar_servidor(host, porta, token, usar_llm)
    endereco = f"http://{host}:{servidor.server_port}"
    print(f"Anonimizador jurídico {VERSAO} em {endereco}")
    if host not in ("127.0.0.1", "localhost"):
        print("[atenção] o servidor está exposto na rede. Use --token e, de "
              "preferência, um proxy com TLS na frente.")
    if token:
        print(f"[info] token exigido; abra {endereco}/?token={token}")
    print("[info] o cofre fica só na memória: encerrar o processo torna os "
          "textos anonimizados irreversíveis.")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nencerrando e apagando os cofres em memória…")
    finally:
        servidor.server_close()
