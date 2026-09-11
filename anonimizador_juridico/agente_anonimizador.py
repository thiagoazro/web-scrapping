"""AGENTE 1 — Anonimizador.

Responsabilidade única: transformar a peça em uma versão sem dados pessoais,
preservando o conteúdo jurídico. Ele NÃO julga o próprio trabalho — quem faz
isso é o Agente 2.

Ordem das camadas (importa muito):

1. determinística  — regex + dígito verificador. Precisão altíssima, custo zero.
2. mascaramento    — o texto é mascarado ANTES de sair da máquina.
3. semântica (LLM) — o modelo recebe o texto já mascarado e procura o que
                     sobrou: nomes, referências indiretas, singularizações.
4. pseudonimização — cada valor vira um token estável vindo do cofre.

A camada 2 antes da 3 é deliberada: o provedor do modelo nunca vê o CPF.
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Sequence

from . import detectores, tipos as T
from .cofre import Cofre
from .llm import SCHEMA_DETECCAO, ClienteClaude

SISTEMA_ANONIMIZADOR = """\
Você é um especialista em proteção de dados (LGPD) que prepara peças judiciais \
brasileiras para uso em sistemas de IA.

Você recebe um texto em que os dados estruturados JÁ FORAM substituídos por \
marcadores como [CPF_001], [NOME_002], [PROCESSO_001]. Sua tarefa é encontrar \
o que sobrou — exatamente o que expressão regular não pega:

- nomes de pessoas (partes, advogados, testemunhas, peritos, prepostos, \
familiares, terceiros citados), inclusive apelidos e nomes parciais;
- endereços, bairros, locais de trabalho e outros dados de localização;
- referências INDIRETAS que permitem reidentificar alguém pela combinação de \
atributos: "o único engenheiro surdo da filial de Bauru", "a filha mais nova \
do reclamante", cargos raros somados a datas e locais;
- dados pessoais sensíveis (art. 5º, II, LGPD): saúde, diagnósticos, CID, \
religião, filiação sindical ou partidária, origem racial, vida sexual, \
dados biométricos ou genéticos;
- identificadores diversos: matrículas, contratos, protocolos, números de \
benefício, placas, perfis em redes sociais.

NÃO marque: teses jurídicas, dispositivos legais, artigos, súmulas, nomes de \
tribunais, varas e órgãos públicos, valores de pedido, datas processuais e \
termos técnicos. Eles são o conteúdo útil da peça e precisam sobreviver.

Regras de saída, obrigatórias:
1. Em "trecho", copie o texto EXATAMENTE como aparece no documento — mesma \
grafia, mesma acentuação, mesmas maiúsculas. Não normalize, não parafraseie.
2. Nunca invente um trecho que não esteja no texto.
3. Um objeto por ocorrência distinta; use o menor trecho que isola o dado.
4. "tipo" deve ser um destes: {tipos}.
5. "confianca" de 0 a 1: use acima de 0,8 só quando tiver certeza.
6. Na dúvida entre marcar e não marcar, MARQUE. Excesso de anonimização é um \
defeito corrigível; vazamento de dado pessoal, não.
"""


class AgenteAnonimizador:
    """Agente 1 do sistema."""

    nome = "agente-anonimizador"

    def __init__(
        self,
        cofre: Optional[Cofre] = None,
        confianca_minima: float = 0.5,
        tipos_ignorados: Iterable[str] = (),
        usar_llm: bool = False,
        cliente: Optional[ClienteClaude] = None,
        max_caracteres_llm: int = 120_000,
    ) -> None:
        self.cofre = cofre if cofre is not None else Cofre()
        self.confianca_minima = confianca_minima
        self.tipos_ignorados = set(tipos_ignorados)
        self.usar_llm = usar_llm
        self.cliente = cliente
        self.max_caracteres_llm = max_caracteres_llm

    # ------------------------------------------------------------------ #

    def anonimizar(
        self,
        texto: str,
        trechos_forcados: Sequence[str] = (),
        tipos_forcados: Optional[Dict[str, str]] = None,
    ) -> T.ResultadoAnonimizacao:
        """Devolve o texto pseudonimizado e o inventário do que foi tratado.

        `trechos_forcados` existe para o retrabalho: quando o auditor aponta um
        vazamento, o orquestrador devolve o trecho literal aqui e ele é
        mascarado sem depender de heurística.
        """
        avisos: List[str] = []

        # 1. camada determinística
        ocorrencias = detectores.varrer(
            texto,
            confianca_minima=self.confianca_minima,
            tipos_ignorados=self.tipos_ignorados,
        )

        # 2. trechos exigidos por quem chamou (realimentação da auditoria)
        ocorrencias.extend(
            self._ocorrencias_de_trechos(texto, trechos_forcados, tipos_forcados or {})
        )
        ocorrencias = detectores.resolver_sobreposicoes(ocorrencias)

        # 3. camada semântica sobre o texto JÁ mascarado
        usou_llm = False
        if self.usar_llm:
            parcial = self._aplicar(texto, ocorrencias)
            try:
                novas = self._detectar_com_llm(texto, parcial.texto_anonimizado)
                ocorrencias = detectores.resolver_sobreposicoes(
                    list(ocorrencias) + novas
                )
                usou_llm = True
            except Exception as erro:
                avisos.append(
                    f"camada semântica ignorada ({type(erro).__name__}: {erro}); "
                    "o resultado contém apenas a detecção determinística"
                )

        # 4. propagação final e substituição
        ocorrencias = detectores.resolver_sobreposicoes(
            list(ocorrencias) + detectores.propagar(texto, ocorrencias)
        )
        resultado = self._aplicar(texto, ocorrencias)
        resultado.usou_llm = usou_llm
        resultado.avisos = avisos
        resultado.texto_original_hash = T.impressao_digital(texto)
        return resultado

    # ------------------------------------------------------------------ #

    def _aplicar(
        self, texto: str, ocorrencias: Sequence[T.Ocorrencia]
    ) -> T.ResultadoAnonimizacao:
        """Substitui de trás para frente, para os offsets não escorregarem."""
        saida = texto
        for oc in sorted(ocorrencias, key=lambda o: o.inicio, reverse=True):
            token = self.cofre.token_para(oc.tipo, oc.valor)
            saida = saida[:oc.inicio] + token + saida[oc.fim:]
        return T.ResultadoAnonimizacao(
            texto_anonimizado=saida,
            ocorrencias=sorted(ocorrencias, key=lambda o: o.inicio),
        )

    def _ocorrencias_de_trechos(
        self,
        texto: str,
        trechos: Sequence[str],
        tipos: Dict[str, str],
    ) -> List[T.Ocorrencia]:
        achados: List[T.Ocorrencia] = []
        for trecho in trechos:
            trecho = (trecho or "").strip()
            if len(trecho) < 3:
                continue
            tipo = tipos.get(trecho, T.DADO_SENSIVEL)
            for m in re.finditer(re.escape(trecho), texto):
                achados.append(T.Ocorrencia(
                    tipo=tipo, valor=trecho, inicio=m.start(), fim=m.end(),
                    confianca=1.0, origem="auditor",
                    motivo="trecho exigido pela auditoria",
                ))
        return achados

    def _detectar_com_llm(self, original: str, mascarado: str) -> List[T.Ocorrencia]:
        cliente = self.cliente or ClienteClaude()
        self.cliente = cliente
        if not cliente.disponivel:
            raise RuntimeError(cliente.erro_inicializacao or "cliente indisponível")
        if len(mascarado) > self.max_caracteres_llm:
            raise RuntimeError(
                f"texto com {len(mascarado)} caracteres excede o limite "
                f"de {self.max_caracteres_llm}; divida a peça em blocos"
            )

        dados = cliente.extrair_json(
            sistema=SISTEMA_ANONIMIZADOR.format(tipos=", ".join(T.TIPOS)),
            conteudo=f"<peca>\n{mascarado}\n</peca>",
            schema=SCHEMA_DETECCAO,
        )
        return self._converter(original, dados.get("entidades", []))

    def _converter(self, original: str, entidades: Sequence[dict]) -> List[T.Ocorrencia]:
        """Converte a saída do modelo em ocorrências — descartando qualquer
        trecho que não exista literalmente no documento (anti-alucinação)."""
        convertidas: List[T.Ocorrencia] = []
        for item in entidades:
            trecho = (item.get("trecho") or "").strip()
            if len(trecho) < 3:
                continue
            tipo = (item.get("tipo") or "").strip().upper()
            if tipo not in T.TIPOS:
                tipo = T.DADO_SENSIVEL
            if tipo in self.tipos_ignorados:
                continue
            try:
                confianca = float(item.get("confianca", 0.7))
            except (TypeError, ValueError):
                confianca = 0.7
            if confianca < self.confianca_minima:
                continue
            for m in re.finditer(re.escape(trecho), original):
                convertidas.append(T.Ocorrencia(
                    tipo=tipo, valor=trecho, inicio=m.start(), fim=m.end(),
                    confianca=confianca, origem="llm",
                    motivo=item.get("motivo", "detecção semântica"),
                ))
        return convertidas
