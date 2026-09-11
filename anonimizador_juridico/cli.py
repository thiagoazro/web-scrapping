"""Interface de linha de comando.

    python -m anonimizador_juridico anonimizar -e peca.txt -s peca_anon.txt -c cofre.json
    python -m anonimizador_juridico auditar   -e peca_anon.txt --original peca.txt
    python -m anonimizador_juridico reidentificar -e peca_anon.txt -c cofre.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from . import perfis as _perfis
from . import tipos as T
from .agente_anonimizador import AgenteAnonimizador
from .agente_auditor import AgenteAuditor
from .cofre import Cofre
from .extratores import extrair_texto
from .llm import ClienteClaude
from .orquestrador import VERSAO, Pipeline


def _ler(caminho: str) -> str:
    """Aceita .txt, .docx, .html e .pdf (com pypdf instalado), além de stdin."""
    if caminho == "-":
        return sys.stdin.read()
    arquivo = Path(caminho)
    if arquivo.suffix.lower() in (".txt", ".md", ".text", ""):
        return arquivo.read_text(encoding="utf-8")
    return extrair_texto(arquivo.name, arquivo.read_bytes())


def _carregar_cofre(caminho: Optional[str], senha: Optional[str]) -> Optional[Cofre]:
    if not caminho or not Path(caminho).exists():
        return None
    return Cofre.carregar(caminho, senha=senha)


def _imprimir_parecer(parecer: T.Parecer) -> None:
    marca = "APROVADO" if parecer.aprovado else "REPROVADO"
    print(f"\n=== PARECER DO AUDITOR: {marca} (risco {parecer.nota_risco}/100) ===",
          file=sys.stderr)
    for nome, estado in parecer.verificacoes.items():
        print(f"  [{nome}] {estado}", file=sys.stderr)
    for achado in parecer.achados:
        print(f"  - {achado.gravidade.upper():8} {achado.categoria:20} "
              f"{achado.tipo:14} {T.mascarar_para_relatorio(achado.trecho)}"
              f"  {achado.descricao}", file=sys.stderr)
    for rec in parecer.recomendacoes:
        print(f"  > {rec}", file=sys.stderr)


def comando_anonimizar(args: argparse.Namespace) -> int:
    texto = _ler(args.entrada)
    perfil = _perfis.obter(args.perfil)
    estilo = args.estilo if args.estilo != "perfil" else perfil.estilo_token
    cofre = _carregar_cofre(args.cofre, args.senha) or Cofre(estilo=estilo)

    cliente = None
    if args.com_llm:
        cliente = ClienteClaude(modelo=args.modelo, esforco=args.esforco)
        if not cliente.disponivel:
            print(f"[aviso] camada semântica indisponível: "
                  f"{cliente.erro_inicializacao}", file=sys.stderr)

    pipeline = perfil.construir(usar_llm=bool(args.com_llm), cofre=cofre,
                                cliente=cliente)
    if args.tipos_ignorados:
        extras = set(args.tipos_ignorados.split(","))
        pipeline.anonimizador.tipos_ignorados |= extras
        pipeline.auditor.tipos_fora_de_escopo |= extras
    if args.rodadas:
        pipeline.rodadas_max = args.rodadas

    print(f"[info] perfil: {perfil.nome}", file=sys.stderr)
    resultado = pipeline.processar(texto, referencia=args.referencia)

    if args.saida:
        Path(args.saida).write_text(resultado.texto_anonimizado, encoding="utf-8")
        print(f"[ok] texto anonimizado em {args.saida}", file=sys.stderr)
    else:
        print(resultado.texto_anonimizado)

    if args.cofre:
        cofre.salvar(args.cofre, senha=args.senha)
        print(f"[ok] cofre salvo em {args.cofre} "
              f"({len(cofre)} entradas) — guarde-o separado da peça",
              file=sys.stderr)

    if args.relatorio:
        Path(args.relatorio).write_text(
            json.dumps(resultado.para_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8")
        print(f"[ok] relatório em {args.relatorio}", file=sys.stderr)

    _imprimir_parecer(resultado.parecer)
    return 0 if resultado.aprovado else 2


def comando_auditar(args: argparse.Namespace) -> int:
    texto = _ler(args.entrada)
    original = _ler(args.original) if args.original else None
    cofre = _carregar_cofre(args.cofre, args.senha)

    cliente = ClienteClaude(modelo=args.modelo, esforco=args.esforco) \
        if args.com_llm else None
    auditor = AgenteAuditor(usar_llm=bool(args.com_llm), cliente=cliente)
    parecer = auditor.auditar(texto, texto_original=original, cofre=cofre)

    if args.formato == "json":
        print(json.dumps(parecer.para_dict(), ensure_ascii=False, indent=2))
    else:
        _imprimir_parecer(parecer)
    return 0 if parecer.aprovado else 2


def comando_reidentificar(args: argparse.Namespace) -> int:
    cofre = _carregar_cofre(args.cofre, args.senha)
    if cofre is None:
        print("[erro] cofre não encontrado — sem ele a reidentificação é "
              "impossível, e é assim que deve ser", file=sys.stderr)
        return 1
    texto = cofre.reidentificar(_ler(args.entrada))
    if args.saida:
        Path(args.saida).write_text(texto, encoding="utf-8")
    else:
        print(texto)
    print("[atenção] operação de reidentificação: registre a base legal e o "
          "responsável no seu controle de acesso", file=sys.stderr)
    return 0


def comando_servir(args: argparse.Namespace) -> int:
    from .web import servir

    servir(host=args.host, porta=args.porta, token=args.token,
           usar_llm=args.com_llm)
    return 0


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="anonimizador_juridico",
        description="Anonimização de peças judiciais com auditoria independente.",
    )
    parser.add_argument("--versao", action="version", version=VERSAO)
    sub = parser.add_subparsers(dest="comando", required=True)

    def comuns(p: argparse.ArgumentParser) -> None:
        p.add_argument("-e", "--entrada", required=True,
                       help="arquivo de entrada ('-' para stdin)")
        p.add_argument("-c", "--cofre", help="arquivo JSON do cofre de pseudônimos")
        p.add_argument("--senha", help="senha para cifrar/decifrar o cofre")
        p.add_argument("--com-llm", action="store_true",
                       help="liga a camada semântica (Claude)")
        p.add_argument("--modelo", default="claude-opus-5")
        p.add_argument("--esforco", default="high",
                       choices=["low", "medium", "high", "xhigh", "max"])

    p_anon = sub.add_parser("anonimizar", help="anonimiza e audita uma peça")
    comuns(p_anon)
    p_anon.add_argument("-s", "--saida", help="arquivo de saída (padrão: stdout)")
    p_anon.add_argument("-r", "--relatorio", help="arquivo JSON com o relatório completo")
    p_anon.add_argument("--rodadas", type=int, default=0,
                        help="máximo de rodadas anonimizar->auditar (0 = o do perfil)")
    p_anon.add_argument("--estilo", default="perfil",
                        choices=["perfil", "sequencial", "hash"],
                        help="formato do pseudônimo ([NOME_001] ou [NOME_3f9c1a])")
    p_anon.add_argument("--tipos-ignorados", default="",
                        help="tipos a NÃO anonimizar, separados por vírgula "
                             "(ex.: NOME_EMPRESA,PROCESSO_CNJ)")
    p_anon.add_argument("--referencia", default="",
                        help="identificação do caso para a trilha de auditoria")
    p_anon.add_argument("--perfil", default="padrao",
                        choices=sorted(_perfis.PERFIS),
                        help="perfil de anonimização (ver README)")
    p_anon.set_defaults(func=comando_anonimizar)

    p_aud = sub.add_parser("auditar", help="audita um texto já anonimizado")
    comuns(p_aud)
    p_aud.add_argument("--original", help="documento original, para o confronto")
    p_aud.add_argument("--formato", default="texto", choices=["texto", "json"])
    p_aud.set_defaults(func=comando_auditar)

    p_rei = sub.add_parser("reidentificar",
                           help="desfaz a pseudonimização usando o cofre")
    comuns(p_rei)
    p_rei.add_argument("-s", "--saida")
    p_rei.set_defaults(func=comando_reidentificar)

    p_web = sub.add_parser("servir", help="abre a interface web local")
    p_web.add_argument("--host", default="127.0.0.1",
                       help="padrão 127.0.0.1 (só esta máquina)")
    p_web.add_argument("--porta", type=int, default=8765)
    p_web.add_argument("--token", help="exige este token nas chamadas de API")
    p_web.add_argument("--com-llm", action="store_true",
                       help="deixa a camada semântica ligada por padrão")
    p_web.set_defaults(func=comando_servir)
    return parser


def main(argv=None) -> int:
    args = construir_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
