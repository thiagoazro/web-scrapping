# Anonimizador de peças judiciais — sistema de dois agentes

**Dá para fazer, sim.** Este repositório é a resposta funcionando: um agente que
anonimiza peças judiciais para uso seguro em IA, um segundo agente que confere
o serviço do primeiro, e um orquestrador que coloca os dois para conversar até
a peça estar limpa.

Roda sem instalar nada (só a biblioteca padrão do Python 3.10+). A camada com
Claude é opcional e entra por cima.

```bash
# interface web local: arrasta os arquivos e pronto
python -m anonimizador_juridico servir        # http://127.0.0.1:8765

# ou pela linha de comando
python -m anonimizador_juridico anonimizar \
    -e exemplos/peticao_exemplo.txt \
    -s peca_anonimizada.txt \
    -c cofre.json
```

---

## Um agente ou dois?

Essa é a decisão de arquitetura da qual tudo depende. **Dois.**

Um agente só *consegue* fazer as duas coisas — a implementação seria mais
curta e mais barata. O problema é que ele estaria conferindo o próprio
trabalho, e quem produz um texto é péssimo juiz dele, seja humano ou modelo.
Se o anonimizador não enxergou que "o único operador de empilhadeira afastado
por LER na unidade de Sorocaba" identifica uma pessoa, ele também não vai
enxergar isso na hora de revisar: **é o mesmo raciocínio, com os mesmos pontos
cegos, rodando duas vezes**. O "sim, está tudo certo" de um agente que se
autoavalia não carrega informação nenhuma.

Com dois agentes, a verificação é *adversarial por construção*:

| | Agente 1 — Anonimizador | Agente 2 — Auditor |
|---|---|---|
| Pergunta | "o que aqui é dado pessoal?" | "ainda dá para identificar alguém?" |
| Entrada | peça original | peça **anonimizada** (o original é opcional) |
| Viés desejado | equilíbrio (não mutilar a peça) | paranoia (limiar de detecção mais baixo) |
| Confia no outro? | não | não — refaz a detecção do zero |
| Pode aprovar? | não | sim, e é o único que pode |

O auditor nunca recebe a lista do que o anonimizador *achou que fez*. Ele
redetecta tudo sozinho, com limiar de confiança menor (0,45 contra 0,50), e
compara o resultado com o texto entregue. É por isso que ele acha erro.

E há um ganho prático em separar: o auditor funciona **sozinho**, sobre um
documento anonimizado por outra pessoa, por outro software ou por um estagiário
com Ctrl+H. Isso vale por um produto inteiro à parte.

---

## Como o sistema funciona

```
                 ┌──────────────────────────────────────────┐
   peça          │  AGENTE 1 — Anonimizador                 │
   original ───► │  1. regex + dígito verificador           │
                 │  2. mascara ANTES de sair da máquina     │
                 │  3. Claude lê o texto já mascarado       │  (opcional)
                 │  4. pseudônimos estáveis vindos do cofre │
                 └───────────────────┬──────────────────────┘
                                     │ texto anonimizado
                                     ▼
                 ┌──────────────────────────────────────────┐
                 │  AGENTE 2 — Auditor                      │
                 │  • varredura cega no resultado           │
                 │  • confronto com o original              │
                 │  • integridade (não reescreveu a peça?)  │
                 │  • consistência do cofre                 │
                 │  • Claude: dá para reidentificar?        │  (opcional)
                 └───────────────────┬──────────────────────┘
                                     │
                       aprovado? ────┴──── não ──► devolve os trechos vazados
                            │                      ao Agente 1 (nova rodada)
                           sim
                            ▼
                  texto liberado + parecer + trilha de auditoria
```

O laço de realimentação é o que transforma dois agentes em um **sistema**: os
trechos que o auditor aponta voltam ao anonimizador como entrada obrigatória, e
a peça é reprocessada (até 3 rodadas, por padrão). O que a heurística erra na
primeira passada costuma ser corrigido na segunda — sem intervenção humana.

### A ordem das camadas é uma decisão de privacidade

O dado estruturado é mascarado **antes** de qualquer chamada de rede. O provedor
do modelo recebe `[CPF_001]`, nunca `529.982.247-25`. Você reduz a superfície de
exposição justamente do dado mais sensível, e ainda economiza token.

### Por que não deixar o modelo fazer tudo

| Camada | Pega o quê | Precisão | Custo |
|---|---|---|---|
| Determinística (regex + DV) | CPF, CNPJ, PIS, CNH, título, processo CNJ, OAB, CID, e-mail, telefone, CEP, endereço, placa, PIX, conta | altíssima — o dígito verificador **prova** que aquilo é um CPF | zero |
| Heurística de nomes | nomes por forma + papel processual ("o reclamante X", "Dr. Y") | boa | zero |
| Semântica (Claude) | referências indiretas, singularização, dados de saúde escritos por extenso, apelidos | boa, não determinística | token + latência |

Modelo de linguagem não é bom em decorar 11 dígitos: ele erra um número no meio,
inventa um dígito, ou deixa passar o terceiro CPF da página. Regex com validador
não erra nunca — e não erra do mesmo jeito nas duas vezes que você rodar. Por
outro lado, nenhuma regex do mundo vai entender que "a filha mais nova do
reclamante, que trabalhava no mesmo setor" identifica uma pessoa. As duas
camadas são complementares, e a ordem importa.

---

## Interface web

```bash
python -m anonimizador_juridico servir
```

Abre em `http://127.0.0.1:8765`: arraste `.txt`, `.docx`, `.html` ou `.pdf`
(ou cole o texto), escolha o perfil, clique. Sai o texto anonimizado com os
marcadores destacados, o parecer do auditor achado por achado, e os botões de
baixar o `.txt` limpo e o relatório `.json`.

Não é um site: é um servidor que roda **na máquina do escritório**, escrito só
com a biblioteca padrão — sem framework, sem banco, sem Docker. Três decisões
de segurança que valem por documentação:

* escuta apenas em `127.0.0.1` por padrão — a máquina só fala com ela mesma, e
  a peça judicial não atravessa a rede;
* o **cofre vive só na memória** do processo: fechar o servidor apaga a
  possibilidade de reidentificar. Quem precisa guardar, baixa o arquivo com
  consciência do que está guardando;
* o servidor não grava o documento original em disco em momento algum.

Para colocar na rede interna: `--host 0.0.0.0 --token <segredo>` e, de
preferência, um proxy com TLS na frente.

**Documentos em lote compartilham o mesmo cofre**: envie a inicial, a
contestação e a réplica juntas e a mesma pessoa recebe `[NOME_001]` nas três.
É o que torna o conjunto utilizável por uma IA que precisa acompanhar quem é
quem ao longo do processo.

---

## Perfis prontos

Cada uso pede um ajuste diferente, então o sistema traz quatro configurações
nomeadas — na interface, só o nome aparece:

| Perfil | O que faz | Quando usar |
|---|---|---|
| **Padrão** | remove todo dado pessoal, preserva conteúdo jurídico, valores e datas processuais | enviar a peça para uma IA analisar ou resumir |
| **Estrito (LGPD máxima)** | limiar mais baixo nos dois agentes, mais rodadas de correção | dado que sai da sua infraestrutura |
| **Pesquisa de jurisprudência** | preserva número do processo, comarca, razão social e OAB; remove as pessoas físicas | índice interno de decisões, banco de teses |
| **Base para treinar/indexar IA** | remove tudo, com pseudônimo em hash estável entre documentos | corpus, fine-tuning, RAG sobre acervo próprio |

O perfil configura **os dois agentes**: o que ele manda preservar não vira
achado do auditor — aparece no parecer como "preservado por decisão do perfil",
para a escolha ficar registrada em vez de virar risco silencioso.

---

## Uso

### Linha de comando

```bash
# anonimizar + auditar (sai 0 se aprovado, 2 se reprovado — dá para usar em CI)
python -m anonimizador_juridico anonimizar -e peca.txt -s peca_anon.txt \
    -c cofre.json -r relatorio.json --perfil estrito \
    --referencia "0001234-02.2023.5.02.0011"

# com a camada semântica (exige `pip install anthropic` + ANTHROPIC_API_KEY)
python -m anonimizador_juridico anonimizar -e peca.txt -s peca_anon.txt --com-llm

# auditar um texto anonimizado por outra pessoa/ferramenta
python -m anonimizador_juridico auditar -e peca_anon.txt --formato json

# auditoria completa, com o original em mãos
python -m anonimizador_juridico auditar -e peca_anon.txt --original peca.txt -c cofre.json

# desfazer (só com o cofre — registre a base legal antes)
python -m anonimizador_juridico reidentificar -e peca_anon.txt -c cofre.json
```

Aceita `.txt`, `.docx`, `.html` e `.pdf` (este último com `pip install pypdf`;
PDF digitalizado precisa de OCR antes, e o sistema avisa em vez de fingir que
leu). Outras opções: `--perfil`, `--tipos-ignorados NOME_EMPRESA,LOCALIDADE`,
`--estilo hash`, `--senha` (cofre cifrado), `--rodadas N`.

### Em Python

```python
from anonimizador_juridico import Pipeline

pipeline = Pipeline()                       # só camada determinística
resultado = pipeline.processar(texto_da_peca, referencia="proc-123")

resultado.texto_anonimizado                 # pronto para ir à IA
resultado.aprovado                          # o auditor liberou?
resultado.parecer.nota_risco                # 0 a 100
resultado.parecer.achados                   # o que ainda está errado
resultado.trilha                            # hashes, contagens, timestamp

pipeline.cofre.salvar("cofre.json", senha="...")   # guarde separado da peça
```

Com as duas camadas semânticas ligadas:

```python
pipeline = Pipeline.com_llm(esforco="high")   # usa claude-opus-5
```

Sem credencial ou sem o pacote `anthropic`, o sistema **não quebra**: registra o
aviso em `resultado.anonimizacao.avisos` e entrega o resultado determinístico.
Mas o parecer **reprova** a peça com o achado `verificacao_incompleta` — uma
verificação que você pediu e não rodou nunca vira aprovação silenciosa. Quem não
vai usar a camada semântica simplesmente não a liga (`Pipeline()`), e aí o
parecer sai limpo.

### Os agentes isolados

```python
from anonimizador_juridico import AgenteAnonimizador, AgenteAuditor

anonimizado = AgenteAnonimizador().anonimizar(texto)
parecer = AgenteAuditor().auditar(anonimizado.texto_anonimizado)   # verificação cega
```

---

## Pseudônimo, não tarja preta

Cada dado vira um marcador estável: `[NOME_001]`, `[CPF_002]`. Isso preserva o
que faz a peça ser útil para a IA — se `[NOME_001]` aparece em oito parágrafos,
o modelo continua entendendo que é a mesma pessoa; uma tarja preta destruiria
essa relação.

Quando a mesma pessoa aparece escrita de dois jeitos ("SÃO PAULO" e
"São Paulo", CPF com e sem pontuação), o sistema gera `[LOCAL_002]` e
`[LOCAL_002b]`: tokens distintos, para o caminho de volta ser exato letra por
letra, com a mesma base, para o cruzamento continuar enxergando uma entidade
só (`Cofre.base_de` e `Cofre.mesma_entidade`).

O **cofre** guarda o mapa `pseudônimo → valor real`. Ele é a diferença entre
anonimização (irreversível) e pseudonimização (reversível pelo controlador —
art. 12 da LGPD). Com `--estilo hash` e a variável `ANONIMIZADOR_CHAVE`
definida, o mesmo CPF gera o mesmo pseudônimo em processos diferentes, o que
permite cruzar 500 processos sem reidentificar ninguém.

> **O arquivo do cofre é tão sensível quanto a peça original.** Guarde-o em
> outro lugar, cifrado (`--senha`), com acesso registrado. Sem ele, o texto
> anonimizado é irreversível — e é assim que deve ser para quem só vai usar o
> texto na IA.

---

## O que o auditor verifica

| Verificação | O que pega |
|---|---|
| `residual` | dado pessoal detectável no texto entregue (sem olhar o original) |
| `confronto` | entidade que existia no original e continua literalmente na saída |
| `integridade` | conteúdo jurídico reescrito, resumido ou inventado; excesso de anonimização |
| `cofre` | marcador órfão, colisão de pseudônimo (dois nomes no mesmo token) |
| `semantica` | reidentificação indireta, singularização, dado sensível por extenso |

A verificação de integridade merece destaque: ela confere que todo trecho
preservado existe no original **na mesma ordem**. É o que impede um anonimizador
baseado em LLM de "resumir" a petição e devolver uma peça juridicamente
diferente — falha grave que passaria despercebida numa revisão rápida.

O parecer sai com nota de risco (0–100), achados por gravidade e recomendações.
E os achados são reportados **mascarados**: o relatório de auditoria não repete
o CPF que ele está denunciando.

---

## Limites (leia antes de colocar em produção)

1. **Nenhum anonimizador é perfeito.** Este entrega duas camadas independentes
   e um laço de correção; não entrega garantia. Para dados que vão sair da sua
   infraestrutura, mantenha revisão humana por amostragem.
2. **A heurística de nomes é heurística.** Nome sem marcador de papel e sem
   documento ao lado sai com confiança 0,55. O auditor foi calibrado mais
   agressivo justamente para compensar isso.
3. **Reidentificação por combinação é o risco mais subestimado.** Cargo raro +
   cidade + mês da dispensa às vezes identifica uma pessoa sem citar um nome.
   Só a camada semântica ataca isso — se você não ligar o Claude, esse risco
   simplesmente **não foi avaliado**, e o parecer diz isso explicitamente.
4. **Entrada é texto.** PDF digitalizado precisa de OCR antes; o sistema não
   olha assinaturas em imagem, metadados de arquivo nem carimbos.
5. **LGPD não é só técnica.** Base legal, contrato com o operador, prazo de
   retenção do cofre e registro de acesso continuam sendo decisão jurídica, não
   de software. A trilha de auditoria (`resultado.trilha`) existe para alimentar
   esse controle, com hash do documento em vez do conteúdo.

---

## Estrutura

```
anonimizador_juridico/
├── tipos.py                 # catálogo de dados pessoais, gravidade, estruturas
├── validadores.py           # CPF, CNPJ, PIS, CNH, título, processo CNJ, Luhn
├── detectores.py            # regex + heurística de nomes + localidades
├── cofre.py                 # pseudônimos estáveis, persistência, cifragem
├── extratores.py            # .txt, .docx (sem dependência), .html, .pdf
├── llm.py                   # cliente Claude (opcional) + contratos JSON
├── agente_anonimizador.py   # AGENTE 1
├── agente_auditor.py        # AGENTE 2
├── orquestrador.py          # o sistema: laço anonimizar → auditar → corrigir
├── perfis.py                # configurações prontas por tipo de uso
├── cli.py                   # linha de comando
└── web/                     # interface local (http.server + uma página)
    ├── servidor.py
    └── static/index.html
```

## Testes

```bash
python -m unittest discover -s tests -t .
```

85 testes, todos offline — a camada de LLM é exercitada com um dublê, inclusive
os casos em que o modelo **alucina um trecho que não existe no documento** (o
sistema descarta) e em que a credencial está ausente. A interface web é testada
de verdade: sobe um servidor em porta efêmera e exercita upload, lote com cofre
compartilhado, reidentificação, token de acesso e arquivo em formato inválido.

## Como estender

- Novo tipo de dado: acrescente a constante em `tipos.py` e uma `Regra` em
  `detectores.py` — o auditor passa a cobrar o tipo novo automaticamente.
- Falso positivo recorrente (um termo jurídico virando nome): inclua-o em
  `TERMOS_INSTITUCIONAIS`.
- Outro domínio (contratos, prontuários, RH): o desenho dos dois agentes é o
  mesmo; troca-se o vocabulário em `detectores.py` e os prompts em
  `agente_anonimizador.py` / `agente_auditor.py`.
