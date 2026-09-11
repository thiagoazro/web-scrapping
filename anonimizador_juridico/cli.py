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


LARGURA = 74


def _imprimir_alerta(parecer: T.Parecer) -> None:
    """O alerta de injeção vem ANTES de tudo e em bloco próprio.

    Misturado à lista de achados de dado pessoal, ele passa batido — e é o
    único achado que exige uma decisão humana imediata sobre encaminhar ou não
    o arquivo adiante.
    """
    alertas = parecer.alertas_de_seguranca
    if not alertas:
        return
    borda = "=" * LARGURA
    print(f"\n{borda}", file=sys.stderr)
    print("  !! ALERTA DE SEGURANÇA — TENTATIVA DE INJEÇÃO DE PROMPT",
          file=sys.stderr)
    print(borda, file=sys.stderr)
    print(f"  Este documento contém {len(alertas)} trecho(s) com forma de "
          "instrução dirigida\n  a sistemas de IA:\n", file=sys.stderr)
    for alerta in alertas:
        posicao = f"pos. {alerta.posicao}" if alerta.posicao is not None else "—"
        print(f"  [{alerta.gravidade.upper():7}] {alerta.tipo:22} {posicao}",
              file=sys.stderr)
        if alerta.trecho:
            print(f"            > {alerta.trecho[:96]!r}", file=sys.stderr)
    print("\n  O texto foi tratado como DADO, nunca como comando, e os dados "
          "pessoais\n  foram removidos normalmente. Mas NÃO encaminhe este "
          "arquivo a outro\n  sistema de IA antes de um humano ler os trechos "
          "acima.", file=sys.stderr)
    print(borda, file=sys.stderr)


def _imprimir_parecer(parecer: T.Parecer) -> None:
    _imprimir_alerta(parecer)
    marca = "APROVADO" if parecer.aprovado else "REPROVADO"
    print(f"\n=== PARECER DO AUDITOR: {marca} (risco {parecer.nota_risco}/100) ===",
          file=sys.stderr)
    for nome, estado in parecer.verificacoes.items():
        print(f"  [{nome}] {estado}", file=sys.stderr)
    for achado in parecer.achados:
        trecho = (T.mascarar_para_relatorio(achado.trecho) if achado.sigiloso
                  else achado.trecho[:60])
        print(f"  - {achado.gravidade.upper():8} {achado.categoria:20} "
              f"{achado.tipo:14} {trecho}  {achado.descricao}",
              file=sys.stderr)
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

    if resultado.quarentena and args.bloquear_injecao:
        _imprimir_parecer(resultado.parecer)
        print("\n[bloqueado] --bloquear-injecao está ativo e o documento está "
              "em quarentena: nada foi gravado.", file=sys.stderr)
        return 3

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


def comando_verificar(args: argparse.Namespace) -> int:
    """Varredura de segurança isolada: o documento contém instrução para IA?

    Serve para quem já anonimiza de outro jeito e só quer o porteiro antes de
    jogar o arquivo num resumidor, num RAG ou num assistente de minuta.
    """
    from . import defesas

    texto = _ler(args.entrada)
    alertas = defesas.detectar(texto)
    parecer = T.Parecer(aprovado=not alertas,
                        nota_risco=min(sum(
                            T.PESO_SEVERIDADE.get(a.gravidade, 5)
                            for a in alertas), 100),
                        achados=alertas,
                        verificacoes={"injecao": f"{len(alertas)} achado(s)"})

    if args.formato == "json":
        print(json.dumps(parecer.para_dict(), ensure_ascii=False, indent=2))
    elif alertas:
        _imprimir_alerta(parecer)
    else:
        print("[ok] nenhuma tentativa de injeção de prompt encontrada",
              file=sys.stderr)
    return 0 if not alertas else 2


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
    p_anon.add_argument("--bloquear-injecao", action="store_true",
                        help="não grava a saída se o documento contiver "
                             "tentativa de injeção de prompt (código 3)")
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

    p_ver = sub.add_parser(
        "verificar",
        help="varre o documento em busca de injeção de prompt (sem anonimizar)")
    p_ver.add_argument("-e", "--entrada", required=True)
    p_ver.add_argument("--formato", default="texto", choices=["texto", "json"])
    p_ver.set_defaults(func=comando_verificar)

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
