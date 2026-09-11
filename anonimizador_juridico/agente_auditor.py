"""AGENTE 2 — Auditor.

Responsabilidade única: dizer se a peça anonimizada ainda contém dado pessoal.
Ele não anonimiza nada e não confia na lista de ocorrências do Agente 1 —
refaz a detecção por conta própria, com limiar mais baixo (prioriza recall).

É a razão de existirem dois agentes: quem produz um texto é péssimo juiz do
próprio texto, seja humano ou modelo. O auditor é adversarial por construção.

Cinco verificações:

1. residual   — varre o texto anonimizado sozinho, como se fosse um documento
                qualquer chegando de fora ("verificação cega").
2. confronto  — com o original em mãos, confere se cada entidade detectada nele
                realmente desapareceu do resultado.
3. integridade— garante que a anonimização não destruiu o conteúdo jurídico.
4. cofre      — checa consistência dos pseudônimos e tokens órfãos.
5. semântica  — (opcional) o Claude lê SÓ o texto anonimizado e responde se
                ainda é possível identificar alguém, inclusive por combinação
                de atributos.
"""

from __future__ import annotations

import re
from typing import List, Optional, Sequence

from . import detectores, tipos as T
from .cofre import Cofre
from .llm import SCHEMA_AUDITORIA, ClienteClaude

RE_TOKEN = re.compile(r"\[[A-Z_]+_[0-9a-f]{3,}\]")

SISTEMA_AUDITOR = """\
Você é o auditor independente de proteção de dados de um escritório de \
advocacia. Recebe uma peça judicial JÁ anonimizada, em que dados pessoais \
foram trocados por marcadores como [NOME_001] e [CPF_002].

Sua pergunta é uma só: **ainda é possível identificar alguma pessoa natural a \
partir deste texto?**

Procure especificamente:
- dados pessoais que escaparam da substituição (nome, endereço, telefone, \
e-mail, documento, matrícula, placa, rede social);
- reidentificação por singularização: a combinação de cargo raro, doença, \
unidade/filial, datas e números pequenos pode apontar uma única pessoa mesmo \
sem nenhum nome ("o único operador de empilhadeira afastado por LER na \
unidade de Sorocaba em março de 2021");
- dados sensíveis remanescentes (saúde, CID, religião, sindicato, raça, \
orientação sexual, biometria);
- vazamento pelo próprio marcador: apelido, iniciais, assinatura ou trecho \
que revele quem é [NOME_001].

NÃO aponte como problema: os marcadores em si, teses jurídicas, artigos de \
lei, súmulas, nomes de tribunais, varas e órgãos públicos, valores e datas \
processuais.

Em "trecho", copie o texto EXATO do documento. Não invente trechos. \
Se nada for encontrado, devolva identificavel=false e a lista de achados vazia.
"""


class AgenteAuditor:
    """Agente 2 do sistema."""

    nome = "agente-auditor"

    def __init__(
        self,
        confianca_minima: float = 0.45,
        usar_llm: bool = False,
        cliente: Optional[ClienteClaude] = None,
        fator_perda_aceitavel: float = 1.6,
        max_caracteres_llm: int = 120_000,
    ) -> None:
        # Limiar mais baixo que o do anonimizador: o auditor prefere apontar
        # um falso positivo a deixar passar um dado real.
        self.confianca_minima = confianca_minima
        self.usar_llm = usar_llm
        self.cliente = cliente
        # Quanto a mais que o detectado pode ser removido antes de
        # soar como excesso de anonimização.
        self.fator_perda_aceitavel = fator_perda_aceitavel
        self.max_caracteres_llm = max_caracteres_llm

    # ------------------------------------------------------------------ #

    def auditar(
        self,
        texto_anonimizado: str,
        texto_original: Optional[str] = None,
        cofre: Optional[Cofre] = None,
    ) -> T.Parecer:
        achados: List[T.Achado] = []
        verificacoes = {}
        usou_llm = False
        recomendacoes: List[str] = []

        # 1. verificação cega
        residuais = self._residuais(texto_anonimizado)
        achados.extend(residuais)
        verificacoes["residual"] = f"{len(residuais)} achado(s)"

        # 2. confronto com o original
        if texto_original is not None:
            confronto = self._confronto(texto_original, texto_anonimizado)
            achados.extend(confronto)
            verificacoes["confronto"] = f"{len(confronto)} achado(s)"

            integridade = self._integridade(texto_original, texto_anonimizado)
            achados.extend(integridade)
            verificacoes["integridade"] = f"{len(integridade)} achado(s)"
        else:
            verificacoes["confronto"] = "não executada (texto original não fornecido)"
            verificacoes["integridade"] = "não executada (texto original não fornecido)"

        # 3. cofre
        if cofre is not None:
            cofre_achados = self._checar_cofre(texto_anonimizado, cofre)
            achados.extend(cofre_achados)
            verificacoes["cofre"] = f"{len(cofre_achados)} achado(s)"
        else:
            verificacoes["cofre"] = "não executada (cofre não fornecido)"

        # 4. camada semântica
        if self.usar_llm:
            try:
                semanticos, recomendacoes = self._auditar_com_llm(texto_anonimizado)
                achados.extend(semanticos)
                usou_llm = True
                verificacoes["semantica"] = f"{len(semanticos)} achado(s)"
            except Exception as erro:
                verificacoes["semantica"] = f"falhou ({type(erro).__name__}: {erro})"
                # Verificação pedida e não executada não pode virar aprovação
                # silenciosa: o achado abaixo bloqueia o parecer de propósito.
                achados.append(T.Achado(
                    categoria="verificacao_incompleta",
                    tipo="PROCESSO",
                    gravidade=T.ALTA,
                    descricao=(
                        "a verificação semântica foi solicitada mas não rodou "
                        f"({type(erro).__name__}: {erro}); o risco de "
                        "reidentificação indireta NÃO foi avaliado"
                    ),
                    origem="regra",
                ))
                recomendacoes.append(
                    "Instale/configure o acesso ao Claude e reexecute, ou "
                    "assuma formalmente o risco não avaliado antes de liberar "
                    "a peça."
                )
        else:
            verificacoes["semantica"] = "desativada"

        achados = self._deduplicar(achados)
        nota = self._nota_risco(achados)
        bloqueantes = [a for a in achados if a.gravidade in (T.CRITICA, T.ALTA)]
        recomendacoes.extend(self._recomendacoes(achados))

        return T.Parecer(
            aprovado=not bloqueantes,
            nota_risco=nota,
            achados=achados,
            recomendacoes=recomendacoes,
            usou_llm=usou_llm,
            verificacoes=verificacoes,
        )

    # ------------------------------------------------------------------ #
    # Verificações
    # ------------------------------------------------------------------ #

    def _residuais(self, texto: str) -> List[T.Achado]:
        achados = []
        for oc in detectores.varrer(texto, confianca_minima=self.confianca_minima):
            if RE_TOKEN.fullmatch(oc.valor.strip()):
                continue
            achados.append(T.Achado(
                categoria="residual",
                tipo=oc.tipo,
                gravidade=oc.severidade,
                descricao=(
                    f"{oc.tipo} ainda presente no texto anonimizado "
                    f"(confiança {oc.confianca:.2f}; {oc.motivo})"
                ),
                trecho=oc.valor,
                posicao=oc.inicio,
                origem="regra",
            ))
        return achados

    def _confronto(self, original: str, anonimizado: str) -> List[T.Achado]:
        """Detecção independente no original: o que foi achado lá não pode
        continuar literalmente aqui."""
        achados = []
        for oc in detectores.varrer(original, confianca_minima=self.confianca_minima):
            if len(oc.valor.strip()) < 3:
                continue
            if oc.valor in anonimizado:
                achados.append(T.Achado(
                    categoria="vazamento_literal",
                    tipo=oc.tipo,
                    gravidade=oc.severidade,
                    descricao=(
                        f"{oc.tipo} identificado no documento original permanece "
                        "literalmente no texto anonimizado"
                    ),
                    trecho=oc.valor,
                    posicao=anonimizado.find(oc.valor),
                    origem="regra",
                ))
        return achados

    def _integridade(self, original: str, anonimizado: str) -> List[T.Achado]:
        """Anonimizar não pode significar mutilar nem reescrever a peça.

        Duas perguntas: sobrou conteúdo demais de fora (reescrita) e saiu
        conteúdo demais (excesso de anonimização)?
        """
        achados = []
        tokens = RE_TOKEN.findall(anonimizado)
        segmentos = RE_TOKEN.split(anonimizado)
        sem_tokens = "".join(segmentos)

        # (a) todo trecho preservado precisa existir no original, na ordem.
        # É isto que pega um anonimizador que "resumiu" ou parafraseou a peça —
        # risco real quando se deixa um modelo reescrever o texto livremente.
        cursor = 0
        for segmento in segmentos:
            if not segmento.strip():
                continue
            posicao = original.find(segmento, cursor)
            if posicao < 0:
                achados.append(T.Achado(
                    categoria="conteudo_alterado",
                    tipo="INTEGRIDADE",
                    gravidade=T.ALTA,
                    descricao=(
                        "trecho presente na saída não existe no documento "
                        "original na mesma ordem: o conteúdo jurídico foi "
                        "reescrito, não apenas anonimizado"
                    ),
                    trecho=segmento.strip()[:80],
                    origem="regra",
                ))
                break
            cursor = posicao + len(segmento)

        # (b) excesso de anonimização, medido contra a própria detecção do
        # auditor no original — e não contra um percentual fixo do documento.
        perdido = len(original) - len(sem_tokens)
        esperado = sum(
            len(oc.valor) for oc in
            detectores.varrer(original, confianca_minima=self.confianca_minima)
        )
        if perdido > esperado * self.fator_perda_aceitavel + 40:
            achados.append(T.Achado(
                categoria="perda_de_conteudo",
                tipo="INTEGRIDADE",
                gravidade=T.MEDIA,
                descricao=(
                    f"{perdido} caracteres removidos, mas só {esperado} eram "
                    "dado pessoal detectável: provável excesso de anonimização "
                    "(termo jurídico confundido com nome próprio, por exemplo)"
                ),
                origem="regra",
            ))

        if not tokens and original.strip():
            achados.append(T.Achado(
                categoria="sem_substituicao",
                tipo="INTEGRIDADE",
                gravidade=T.ALTA,
                descricao=(
                    "nenhum marcador de pseudônimo foi encontrado na saída: ou a "
                    "peça não continha dado pessoal, ou a anonimização não rodou"
                ),
                origem="regra",
            ))
        return achados

    def _checar_cofre(self, anonimizado: str, cofre: Cofre) -> List[T.Achado]:
        achados = []
        entradas = cofre.entradas
        no_texto = set(RE_TOKEN.findall(anonimizado))

        for token in sorted(no_texto - set(entradas)):
            achados.append(T.Achado(
                categoria="token_orfao",
                tipo="COFRE",
                gravidade=T.MEDIA,
                descricao=(
                    f"o marcador {token} aparece no texto mas não existe no "
                    "cofre: a reidentificação autorizada falharia"
                ),
                trecho=token,
                origem="regra",
            ))

        valores_por_token = {}
        for token, entrada in entradas.items():
            valores_por_token.setdefault(token, set()).add(T.normalizar(entrada.valor))
        for token, valores in valores_por_token.items():
            if len(valores) > 1:
                achados.append(T.Achado(
                    categoria="colisao_de_pseudonimo",
                    tipo="COFRE",
                    gravidade=T.ALTA,
                    descricao=(
                        f"o marcador {token} aponta para {len(valores)} valores "
                        "diferentes: o texto anonimizado mistura duas pessoas"
                    ),
                    trecho=token,
                    origem="regra",
                ))
        return achados

    def _auditar_com_llm(self, anonimizado: str):
        cliente = self.cliente or ClienteClaude()
        self.cliente = cliente
        if not cliente.disponivel:
            raise RuntimeError(cliente.erro_inicializacao or "cliente indisponível")
        if len(anonimizado) > self.max_caracteres_llm:
            raise RuntimeError(
                f"texto com {len(anonimizado)} caracteres excede o limite de "
                f"{self.max_caracteres_llm}; audite a peça em blocos"
            )

        dados = cliente.extrair_json(
            sistema=SISTEMA_AUDITOR,
            conteudo=f"<peca_anonimizada>\n{anonimizado}\n</peca_anonimizada>",
            schema=SCHEMA_AUDITORIA,
        )
        achados = []
        for item in dados.get("achados", []):
            trecho = (item.get("trecho") or "").strip()
            # Anti-alucinação: o trecho precisa existir mesmo no documento.
            if trecho and trecho not in anonimizado:
                continue
            gravidade = item.get("gravidade", T.MEDIA)
            if gravidade not in (T.CRITICA, T.ALTA, T.MEDIA, T.BAIXA):
                gravidade = T.MEDIA
            achados.append(T.Achado(
                categoria="semantico",
                tipo=(item.get("tipo") or "INDIRETO").upper(),
                gravidade=gravidade,
                descricao=item.get("descricao", ""),
                trecho=trecho,
                posicao=anonimizado.find(trecho) if trecho else None,
                origem="llm",
            ))
        return achados, list(dados.get("recomendacoes", []))

    # ------------------------------------------------------------------ #

    @staticmethod
    def _deduplicar(achados: Sequence[T.Achado]) -> List[T.Achado]:
        vistos = set()
        saida = []
        ordem = {T.CRITICA: 0, T.ALTA: 1, T.MEDIA: 2, T.BAIXA: 3}
        for achado in sorted(achados, key=lambda a: (ordem.get(a.gravidade, 9),
                                                     a.categoria, a.trecho)):
            chave = (achado.tipo, achado.trecho, achado.categoria)
            if chave in vistos:
                continue
            vistos.add(chave)
            saida.append(achado)
        return saida

    @staticmethod
    def _nota_risco(achados: Sequence[T.Achado]) -> int:
        nota = sum(T.PESO_SEVERIDADE.get(a.gravidade, 5) for a in achados)
        return min(nota, 100)

    @staticmethod
    def _recomendacoes(achados: Sequence[T.Achado]) -> List[str]:
        recomendacoes = []
        categorias = {a.categoria for a in achados}
        if "vazamento_literal" in categorias or "residual" in categorias:
            recomendacoes.append(
                "Reprocesse a peça com os trechos apontados forçados no "
                "anonimizador (o orquestrador faz isso automaticamente)."
            )
        if "perda_de_conteudo" in categorias:
            recomendacoes.append(
                "Revise se algum termo jurídico foi confundido com nome próprio; "
                "considere incluí-lo na lista de termos institucionais."
            )
        if "colisao_de_pseudonimo" in categorias or "token_orfao" in categorias:
            recomendacoes.append(
                "Regenere o cofre a partir do documento original antes de "
                "distribuir o texto anonimizado."
            )
        if not achados:
            recomendacoes.append(
                "Nenhum dado pessoal remanescente foi identificado. Mantenha o "
                "cofre em local separado e cifrado."
            )
        return recomendacoes
