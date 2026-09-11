"""Camada determinística de detecção de dados pessoais.

Regex + validadores de documento + heurísticas de nome treinadas no vocabulário
de peças judiciais brasileiras. Não depende de rede, não custa token e é
reprodutível — por isso roda *antes* de qualquer modelo de linguagem.
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from . import tipos as T
from .validadores import VALIDADORES, apenas_digitos

# --------------------------------------------------------------------------- #
# Regras estruturadas
# --------------------------------------------------------------------------- #


class Regra:
    """Um padrão + validação opcional + contexto opcional exigido."""

    def __init__(
        self,
        tipo: str,
        padrao: str,
        confianca: float = 0.95,
        validador: Optional[str] = None,
        contexto: Optional[str] = None,
        janela_contexto: int = 70,
        prioridade: int = 50,
        flags: int = 0,
    ) -> None:
        self.tipo = tipo
        self.regex = re.compile(padrao, flags)
        self.confianca = confianca
        self.validador = validador
        self.contexto = re.compile(contexto, re.IGNORECASE) if contexto else None
        self.janela_contexto = janela_contexto
        self.prioridade = prioridade

    def contexto_ok(self, texto: str, inicio: int) -> bool:
        if self.contexto is None:
            return True
        trecho = texto[max(0, inicio - self.janela_contexto): inicio]
        return bool(self.contexto.search(trecho))

    def valido(self, valor: str) -> bool:
        if self.validador is None:
            return True
        return VALIDADORES[self.validador](valor)


# Prioridade menor = vence a disputa por sobreposição.
REGRAS: List[Regra] = [
    # --- identificadores processuais ---------------------------------------
    Regra(T.PROCESSO_CNJ, r"\b\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}\b",
          validador="PROCESSO_CNJ", prioridade=5),
    Regra(T.PROCESSO_CNJ, r"\b\d{20}\b", validador="PROCESSO_CNJ", prioridade=6),

    # --- documentos com dígito verificador ---------------------------------
    Regra(T.CNPJ, r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b",
          validador="CNPJ", prioridade=10),
    Regra(T.CNPJ, r"\b\d{14}\b", validador="CNPJ", prioridade=11),
    Regra(T.CPF, r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b", validador="CPF", prioridade=10),
    Regra(T.CPF, r"\b\d{11}\b", validador="CPF", prioridade=12),
    Regra(T.CARTAO, r"\b(?:\d{4}[ .-]){3}\d{4}\b", validador="CARTAO", prioridade=13),
    Regra(T.TITULO_ELEITOR, r"\b\d{4}[ .]?\d{4}[ .]?\d{4}\b",
          validador="TITULO_ELEITOR", confianca=0.8,
          contexto=r"t[ií]tulo|eleitor", prioridade=14),
    Regra(T.PIS, r"\b\d{3}\.\d{5}\.\d{2}-\d\b", validador="PIS", prioridade=15),
    # Prioridade abaixo do CPF "nu" (12): um número de 11 dígitos rotulado como
    # PIS/CNH no próprio texto é classificação mais específica do que o mero
    # fato de o dígito verificador também fechar como CPF.
    Regra(T.PIS, r"\b\d{11}\b", validador="PIS", confianca=0.85,
          contexto=r"pis|pasep|nit", prioridade=8),
    Regra(T.CNH, r"\b\d{11}\b", validador="CNH", confianca=0.85,
          contexto=r"cnh|habilita[çc][ãa]o|carteira de motorista", prioridade=9),

    # --- documentos sem DV confiável: exigem contexto -----------------------
    Regra(T.RG, r"\b\d{1,2}\.?\d{3}\.?\d{3}-?[0-9Xx]\b", confianca=0.8,
          contexto=r"\brg\b|identidade|c[ée]dula|ssp|detran", prioridade=20),
    Regra(T.CTPS, r"\b\d{5,8}[\s/-]*(?:s[ée]rie\s*)?\d{3,5}?\b", confianca=0.8,
          contexto=r"ctps|carteira de trabalho", prioridade=21),
    Regra(T.MATRICULA, r"\b\d{4,12}\b", confianca=0.7,
          contexto=r"matr[íi]cula|registro funcional|prontu[áa]rio", prioridade=22),
    Regra(T.CONTA_BANCARIA,
          r"\b\d{1,5}-?\d?\s*/\s*\d{4,12}-?\d?\b|\b\d{4,12}-\d\b", confianca=0.8,
          contexto=r"ag[êe]ncia|conta corrente|conta poupan[çc]a|banco|c/c",
          prioridade=23),
    Regra(T.CHAVE_PIX,
          r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b",
          confianca=0.9, prioridade=24),

    # --- contato ------------------------------------------------------------
    Regra(T.EMAIL, r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b", confianca=0.98, prioridade=30),
    Regra(T.TELEFONE,
          r"(?:\+55\s?)?(?:\(\d{2}\)\s?|\b\d{2}\s)?(?:9\s?)?\d{4}[-.\s]?\d{4}\b",
          confianca=0.85, prioridade=31),
    Regra(T.CEP, r"\b\d{5}-\d{3}\b", confianca=0.9, prioridade=32),
    Regra(T.CEP, r"\b\d{8}\b", confianca=0.8, contexto=r"cep", prioridade=33),

    # --- localização e veículo ---------------------------------------------
    Regra(T.ENDERECO,
          r"\b(?:Rua|R\.|Avenida|Av\.|Alameda|Al\.|Travessa|Tv\.|Pra[çc]a|"
          r"Rodovia|Estrada|Quadra|Conjunto)\s+[^\n,;]{3,60}"
          r"(?:\s*,\s*n?[º°.]?\s*\d+[A-Za-z]?)?(?:\s*,\s*(?:ap|apto|apart|bloco|casa)[^\n,;]{1,20})?",
          confianca=0.85, prioridade=34, flags=re.IGNORECASE),
    Regra(T.PLACA_VEICULO, r"\b[A-Z]{3}-?\d[A-Z0-9]\d{2}\b", confianca=0.85,
          prioridade=35),
    Regra(T.IP, r"\b(?:\d{1,3}\.){3}\d{1,3}\b", confianca=0.9, prioridade=36),

    # --- OAB ----------------------------------------------------------------
    Regra(T.OAB, r"\bOAB\s*[/:]?\s*[A-Z]{2}\s*[nº°.\s-]*\d{1,3}\.?\d{3}\b",
          confianca=0.9, prioridade=37, flags=re.IGNORECASE),
    Regra(T.OAB, r"\b\d{1,3}\.?\d{3}\s*[/-]?\s*OAB\s*[/-]?\s*[A-Z]{2}\b",
          confianca=0.9, prioridade=38, flags=re.IGNORECASE),

    # --- registros profissionais (CRM, CREA, CRC, COREN...) -----------------
    Regra(T.MATRICULA,
          r"\b(?:CRM|CREA|CRC|CRO|CRP|COREN|CRA|CRF|CRB|CRESS|CAU)\s*[/:-]?\s*"
          r"[A-Z]{2}\s*[nº°.\s-]*\d{3,7}\b",
          confianca=0.9, prioridade=39),

    # --- dado pessoal sensível: código de diagnóstico (art. 5º, II, LGPD) ----
    Regra(T.DADO_SENSIVEL,
          r"\bCID[\s-]*(?:10)?\s*[:nº°]*\s*[A-Z]\d{2}(?:\.\d)?\b",
          confianca=0.95, prioridade=26, flags=re.IGNORECASE),

    # --- datas de nascimento (só com contexto) ------------------------------
    Regra(T.DATA_NASCIMENTO,
          r"\b\d{1,2}[/.-]\d{1,2}[/.-]\d{4}\b", confianca=0.9,
          contexto=r"nascid[oa]|nascimento|\bdn\b|natalício", prioridade=40),
    Regra(T.DATA_NASCIMENTO,
          r"\b\d{1,2}\s+de\s+\w+\s+de\s+\d{4}\b", confianca=0.85,
          contexto=r"nascid[oa]|nascimento|\bdn\b", prioridade=41,
          flags=re.IGNORECASE),

    # --- empresa ------------------------------------------------------------
    # Razão social: só encadeia palavras iniciadas em maiúscula, para não
    # engolir o texto corrido que antecede o nome da empresa.
    Regra(T.NOME_EMPRESA,
          r"\b(?:[A-ZÁÉÍÓÚÂÊÔÃÕÇ][\wÁÉÍÓÚÂÊÔÃÕÇáéíóúâêôãõç&.\-]*\s+){1,6}"
          r"(?:LTDA|Ltda|S/A|S\.A\.|S\.?A\b|EIRELI|EPP|MEI)\.?",
          confianca=0.8, prioridade=45),
]

# --------------------------------------------------------------------------- #
# Heurística de nomes de pessoa
# --------------------------------------------------------------------------- #

CONECTIVOS = {"de", "da", "do", "das", "dos", "e", "del", "di", "van", "von", "d'"}

# Marcadores de papel processual: se aparecerem perto do candidato, a confiança
# sobe — é assim que uma peça apresenta as partes.
MARCADORES_PAPEL = re.compile(
    # O \b inicial é essencial: sem ele, "ent<re> " casaria com o papel "réu".
    r"\b(?:reclamante|reclamad[oa]|requerente|requerid[oa]|autor(?:a)?|r[ée][ou]?|"
    r"exequente|execut[ao]d[oa]|embargante|embargad[oa]|agravante|agravad[oa]|"
    r"apelante|apelad[oa]|impetrante|impetrad[oa]|litisconsorte|"
    r"advogad[oa]|procurador(?:a)?|patrono|perit[oa]|testemunha|preposto|"
    r"depoente|s[óo]cio|representante legal|herdeir[oa]|inventariante|"
    r"nome|sr\.?|sra\.?|senhor(?:a)?|dr\.?|dra\.?|doutor(?:a)?|"
    r"em face de|contra|promovid[oa] por)\s*[:\-—,]?\s*$",
    re.IGNORECASE,
)

# Termos institucionais/jurídicos que aparecem em CAIXA ALTA ou Title Case e
# NÃO são nomes de pessoa. Evitam o falso positivo mais comum do sistema.
TERMOS_INSTITUCIONAIS = {
    "poder judiciario", "justica do trabalho", "justica federal",
    "justica estadual", "tribunal", "tribunal regional do trabalho",
    "tribunal de justica", "tribunal superior do trabalho",
    "supremo tribunal federal", "superior tribunal de justica",
    "vara do trabalho", "vara civel", "vara criminal", "vara de familia",
    "juizado especial", "ministerio publico", "defensoria publica",
    "procuradoria", "uniao federal", "fazenda nacional", "fazenda publica",
    "instituto nacional do seguro social", "caixa economica federal",
    "banco central", "receita federal", "consolidacao das leis do trabalho",
    "codigo de processo civil", "codigo civil", "codigo penal",
    "constituicao federal", "consolidacao das leis", "lei geral de protecao",
    "excelentissimo senhor doutor juiz", "meritissimo juiz",
    "colenda turma", "egregio tribunal", "dos fatos", "do direito",
    "dos pedidos", "do cabimento", "da tempestividade", "das preliminares",
    "do merito", "dos danos morais", "das razoes", "da conclusao",
    "nesses termos", "pede deferimento", "termos em que", "sumula",
    "recurso ordinario", "recurso de revista", "agravo de instrumento",
    "peticao inicial", "contestacao", "reclamacao trabalhista",
    "hora extra", "horas extras", "aviso previo", "fundo de garantia",
    "danos morais", "dano moral", "honorarios advocaticios",
    "honorarios sucumbenciais", "justica gratuita", "sentenca",
    "acordao", "despacho", "certidao", "mandado de seguranca",
    "habeas corpus", "recursos humanos", "diario oficial",
    "documento assinado digitalmente", "assinado eletronicamente",
    "vossa excelencia", "vossas excelencias", "vossa senhoria",
    "vossa magnificencia", "egregia corte", "colenda camara",
}

# Se o candidato começa com um destes, é instituição/empresa, não pessoa.
PREFIXOS_INSTITUCIONAIS = {
    "banco", "caixa", "instituto", "fundacao", "associacao", "sindicato",
    "cooperativa", "companhia", "empresa", "industria", "comercio",
    "construtora", "transportadora", "distribuidora", "supermercado",
    "hospital", "clinica", "laboratorio", "universidade", "faculdade",
    "colegio", "escola", "prefeitura", "municipio", "estado", "secretaria",
    "departamento", "delegacia", "ministerio", "procuradoria", "defensoria",
    "tribunal", "vara", "juizado", "condominio", "conselho", "agencia",
    "servico", "central", "grupo", "rede", "unidade", "posto",
}

PALAVRAS_NAO_NOME = {
    "excelentissimo", "excelentissima", "meritissimo", "meritissima",
    "doutor", "doutora", "senhor", "senhora", "juiz", "juiza",
    "desembargador", "desembargadora", "ministro", "ministra",
    "reclamante", "reclamada", "reclamado", "requerente", "requerido",
    "requerida", "autor", "autora", "reu", "re", "exequente", "executado",
    "advogado", "advogada", "processo", "artigo", "artigos", "inciso",
    "paragrafo", "lei", "decreto", "sumula", "clt", "cpc", "cf",
    "trabalho", "justica", "tribunal", "vara", "comarca", "estado",
    "municipio", "empresa", "banco", "instituto", "sociedade",
    "limitada", "ltda", "sa", "eireli", "me", "epp",
    "janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho",
    "agosto", "setembro", "outubro", "novembro", "dezembro",
    "anexo", "anexos", "doc", "docs", "fls", "id", "cpf", "cnpj", "rg",
    "termo", "termos", "pede", "deferimento", "data", "assunto",
    "valor", "causa", "total", "geral", "unico", "primeira", "segunda",
}

# Palavras comuns que começam frase em português e, por estarem em maiúscula,
# grudam no nome seguinte ("Conforme João Pedro Alves" viraria um nome só e,
# pior, um nome diferente do mesmo João citado noutro parágrafo).
PALAVRAS_INICIAIS_COMUNS = {
    "conforme", "segundo", "depois", "quando", "ainda", "assim", "portanto",
    "contudo", "entretanto", "todavia", "porem", "porque", "embora", "apesar",
    "durante", "mediante", "sobre", "sob", "ante", "apos", "antes", "desde",
    "entre", "para", "pelo", "pela", "como", "caso", "diante", "nesse",
    "neste", "nesta", "nessa", "esse", "este", "esta", "essa", "aquele",
    "aquela", "outro", "outra", "mesmo", "mesma", "tal", "tais", "cabe",
    "trata", "cumpre", "resta", "inclusive", "tambem", "ademais", "outrossim",
    "finalmente", "primeiramente", "ocorre", "note", "veja", "ressalte",
    "importa", "verifica", "observa", "considerando", "tendo", "havendo",
    "sendo", "dado", "dada", "posteriormente", "anteriormente", "logo",
    "alem", "quanto", "quando", "onde", "sempre", "nunca", "jamais",
}

_PAL = r"[A-ZÁÉÍÓÚÂÊÔÃÕÀÇ][a-záéíóúâêôãõàçü]+"
_CON = r"(?:de|da|do|das|dos|del|di)"

RE_NOME_TITULO = re.compile(
    rf"\b{_PAL}(?:\s+(?:{_CON}\s+)?{_PAL}){{1,5}}\b"
)
RE_NOME_CAIXA_ALTA = re.compile(
    r"\b[A-ZÁÉÍÓÚÂÊÔÃÕÀÇ]{2,}(?:\s+(?:DE|DA|DO|DAS|DOS)\s+|\s+)"
    r"[A-ZÁÉÍÓÚÂÊÔÃÕÀÇ]{2,}(?:(?:\s+(?:DE|DA|DO|DAS|DOS))?\s+"
    r"[A-ZÁÉÍÓÚÂÊÔÃÕÀÇ]{2,}){0,4}\b"
)


def _candidato_e_institucional(valor: str) -> bool:
    chave = T.normalizar(valor)
    if chave in TERMOS_INSTITUCIONAIS:
        return True
    for termo in TERMOS_INSTITUCIONAIS:
        if termo in chave or chave in termo:
            return True
    palavras = [p for p in chave.split() if p not in CONECTIVOS]
    if not palavras:
        return True
    # Se toda palavra do candidato é vocabulário jurídico, não é nome.
    if all(p in PALAVRAS_NAO_NOME for p in palavras):
        return True
    # Se a primeira palavra é um título/cargo, o nome real vem depois.
    return len(palavras) < 2


def _aparar(valor: str, inicio: int) -> Tuple[str, int]:
    """Remove do começo e do fim do candidato as palavras que não fazem parte
    de nome nenhum, devolvendo o trecho e o novo deslocamento."""
    palavras = valor.split()
    descartaveis = PALAVRAS_INICIAIS_COMUNS | PALAVRAS_NAO_NOME
    while palavras and T.normalizar(palavras[0]) in descartaveis:
        inicio += len(palavras[0]) + 1
        palavras.pop(0)
    while palavras and T.normalizar(palavras[-1]) in (descartaveis | CONECTIVOS):
        palavras.pop()
    return " ".join(palavras), inicio


def detectar_nomes(texto: str, confianca_minima: float = 0.5) -> List[T.Ocorrencia]:
    """Localiza nomes de pessoa por forma + contexto de papel processual."""
    achados: List[T.Ocorrencia] = []
    vistos: set = set()

    for regex, base in ((RE_NOME_CAIXA_ALTA, 0.62), (RE_NOME_TITULO, 0.55)):
        for m in regex.finditer(texto):
            valor, inicio = _aparar(m.group(0).strip(), m.start())
            if len(valor.split()) < 2:
                continue
            fim = inicio + len(valor)
            if _candidato_e_institucional(valor):
                continue
            chave = T.normalizar(valor)
            if chave in LOCAIS_NORMALIZADOS:
                # "São Paulo", "Santa Catarina": topônimo, não pessoa.
                achados.append(T.Ocorrencia(
                    tipo=T.LOCALIDADE, valor=valor,
                    inicio=inicio, fim=fim, confianca=0.9,
                    origem="regra", motivo="município ou unidade federativa",
                ))
                continue
            primeira = chave.split()[0]
            if primeira in PREFIXOS_INSTITUCIONAIS:
                # "Banco do Brasil", "Construtora Horizonte": pessoa jurídica.
                achados.append(T.Ocorrencia(
                    tipo=T.NOME_EMPRESA, valor=valor,
                    inicio=inicio, fim=fim, confianca=0.7,
                    origem="regra", motivo="razão social iniciada por termo institucional",
                ))
                continue
            antes = texto[max(0, inicio - 40): inicio]
            confianca = base
            motivo = "forma de nome próprio"
            if MARCADORES_PAPEL.search(antes):
                confianca = 0.93
                motivo = "precedido de marcador de papel processual"
            elif re.search(r"\b(?:CPF|RG|inscrit[oa]|portador[a]?)\b",
                           texto[fim: fim + 60], re.IGNORECASE):
                confianca = 0.9
                motivo = "seguido de documento de identificação"
            if confianca < confianca_minima:
                continue
            chave = (inicio, fim)
            if chave in vistos:
                continue
            vistos.add(chave)
            achados.append(T.Ocorrencia(
                tipo=T.NOME_PESSOA, valor=valor, inicio=inicio, fim=fim,
                confianca=confianca, origem="regra", motivo=motivo,
            ))
    return achados


# --------------------------------------------------------------------------- #
# Varredura e resolução de conflitos
# --------------------------------------------------------------------------- #

# NOME_PESSOA e LOCALIDADE compartilham a prioridade de propósito: assim o
# desempate é pelo tamanho do trecho, e "MARIA APARECIDA DOS SANTOS" vence
# "Santos" (cidade) em vez de ser partida ao meio.
_PRIORIDADE_EXTRA = {T.LOCALIDADE: 58, T.NOME_EMPRESA: 45, T.NOME_PESSOA: 58}


def _prioridade(oc: T.Ocorrencia) -> Tuple[int, int, float]:
    padrao = {r.tipo: r.prioridade for r in REGRAS}
    prio = padrao.get(oc.tipo, _PRIORIDADE_EXTRA.get(oc.tipo, 60))
    return (prio, -(oc.fim - oc.inicio), -oc.confianca)


def resolver_sobreposicoes(ocorrencias: Sequence[T.Ocorrencia]) -> List[T.Ocorrencia]:
    """Quando dois padrões pegam o mesmo trecho, vence o mais específico
    (menor prioridade), depois o mais longo, depois o mais confiante."""
    ordenadas = sorted(ocorrencias, key=_prioridade)
    mantidas: List[T.Ocorrencia] = []
    for oc in ordenadas:
        if any(oc.sobrepoe(m) for m in mantidas):
            continue
        mantidas.append(oc)
    return sorted(mantidas, key=lambda o: o.inicio)


def propagar(texto: str, ocorrencias: Sequence[T.Ocorrencia]) -> List[T.Ocorrencia]:
    """Se "João da Silva" foi identificado uma vez, toda outra ocorrência
    literal dele no documento também é dado pessoal — mesmo onde a heurística
    não teria disparado sozinha."""
    extras: List[T.Ocorrencia] = []
    por_valor: Dict[str, T.Ocorrencia] = {}
    for oc in ocorrencias:
        if len(oc.valor.strip()) >= 4:
            por_valor.setdefault(oc.valor, oc)
    for valor, modelo in por_valor.items():
        for m in re.finditer(re.escape(valor), texto):
            if any(o.inicio == m.start() and o.fim == m.end() for o in ocorrencias):
                continue
            extras.append(T.Ocorrencia(
                tipo=modelo.tipo, valor=valor, inicio=m.start(), fim=m.end(),
                confianca=modelo.confianca, origem="propagacao",
                motivo="repetição literal de entidade já identificada",
            ))
    return extras


def varrer(
    texto: str,
    confianca_minima: float = 0.5,
    tipos_ignorados: Iterable[str] = (),
    detectar_nome: bool = True,
) -> List[T.Ocorrencia]:
    """Varredura determinística completa do texto."""
    ignorados = set(tipos_ignorados)
    brutas: List[T.Ocorrencia] = []

    for regra in REGRAS:
        if regra.tipo in ignorados:
            continue
        for m in regra.regex.finditer(texto):
            valor = m.group(0).strip()
            if not valor:
                continue
            if not regra.contexto_ok(texto, m.start()):
                continue
            if not regra.valido(valor):
                continue
            if regra.confianca < confianca_minima:
                continue
            brutas.append(T.Ocorrencia(
                tipo=regra.tipo, valor=valor,
                inicio=m.start(), fim=m.start() + len(valor),
                confianca=regra.confianca, origem="regra",
                motivo=f"padrão {regra.tipo}"
                       + (" validado por dígito verificador" if regra.validador else ""),
            ))

    if detectar_nome and T.NOME_PESSOA not in ignorados:
        brutas.extend(detectar_nomes(texto, confianca_minima))

    if T.LOCALIDADE not in ignorados:
        brutas.extend(detectar_localidades(texto))

    # Filtro final: `tipos_ignorados` vale para qualquer origem de detecção,
    # inclusive as reclassificações feitas dentro da heurística de nomes.
    brutas = [oc for oc in brutas if oc.tipo not in ignorados]

    resolvidas = resolver_sobreposicoes(brutas)
    extras = [oc for oc in propagar(texto, resolvidas) if oc.tipo not in ignorados]
    return resolver_sobreposicoes(list(resolvidas) + extras)


# --------------------------------------------------------------------------- #
# Localidades (quase-identificadores)
# --------------------------------------------------------------------------- #
#
# Cidade e bairro raramente identificam alguém sozinhos, mas somados a cargo,
# data e empresa singularizam uma pessoa com facilidade. Ficam no conjunto
# padrão; para preservá-los, use `tipos_ignorados={"LOCALIDADE"}`.

CIDADES = [
    "São Paulo", "Rio de Janeiro", "Brasília", "Salvador", "Fortaleza",
    "Belo Horizonte", "Manaus", "Curitiba", "Recife", "Goiânia", "Belém",
    "Porto Alegre", "Guarulhos", "Campinas", "São Luís", "Maceió",
    "Campo Grande", "Natal", "Teresina", "João Pessoa", "Santo André",
    "Osasco", "Ribeirão Preto", "Uberlândia", "Sorocaba", "Contagem",
    "Aracaju", "Feira de Santana", "Cuiabá", "Joinville", "Juiz de Fora",
    "Londrina", "Niterói", "Florianópolis", "Vitória", "Macapá",
    "Porto Velho", "Rio Branco", "Boa Vista", "Palmas", "Santos",
    "Bauru", "Piracicaba", "Diadema", "Mauá", "Jundiaí", "Canoas",
    "Petrópolis", "Caxias do Sul", "Anápolis", "São Bernardo do Campo",
    "São José dos Campos", "São Gonçalo", "Duque de Caxias", "Nova Iguaçu",
]

ESTADOS = [
    "Acre", "Alagoas", "Amapá", "Amazonas", "Bahia", "Ceará",
    "Espírito Santo", "Goiás", "Maranhão", "Mato Grosso",
    "Mato Grosso do Sul", "Minas Gerais", "Pará", "Paraíba", "Paraná",
    "Pernambuco", "Piauí", "Rio Grande do Norte", "Rio Grande do Sul",
    "Rondônia", "Roraima", "Santa Catarina", "Sergipe", "Tocantins",
]

_LOCAIS = sorted(CIDADES + ESTADOS, key=len, reverse=True)
LOCAIS_NORMALIZADOS = {T.normalizar(local) for local in _LOCAIS}

RE_LOCALIDADE = re.compile(
    r"\b(?:" + "|".join(re.escape(local) for local in _LOCAIS) + r")\b"
    r"(?:\s*/\s*[A-Z]{2}\b)?",
    re.IGNORECASE,
)

# Bairros e logradouros nomeados: "Vila Mariana", "Jardim das Flores".
RE_BAIRRO = re.compile(
    r"\b(?:Vila|Jardim|Parque|Bairro|Chácara|Distrito|Conjunto Habitacional|"
    r"Núcleo|Setor|Loteamento)\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ][\wÁÉÍÓÚÂÊÔÃÕÇáéíóúâêôãõç]+"
    r"(?:\s+(?:de|da|do|das|dos)\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ][\wáéíóúâêôãõç]+)?"
)


def detectar_localidades(texto: str) -> List[T.Ocorrencia]:
    achados: List[T.Ocorrencia] = []
    for regex, confianca, motivo in (
        (RE_LOCALIDADE, 0.9, "município ou unidade federativa"),
        (RE_BAIRRO, 0.8, "bairro ou logradouro nomeado"),
    ):
        for m in regex.finditer(texto):
            achados.append(T.Ocorrencia(
                tipo=T.LOCALIDADE, valor=m.group(0).strip(),
                inicio=m.start(), fim=m.start() + len(m.group(0).strip()),
                confianca=confianca, origem="regra", motivo=motivo,
            ))
    return achados
