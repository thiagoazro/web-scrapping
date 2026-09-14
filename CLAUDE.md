# Anonimizador de peças judiciais — contexto para o Claude Code

Sistema de anonimização de peças judiciais brasileiras com **dois agentes
independentes** e um orquestrador. Leia o `README.md` para o raciocínio
completo; este arquivo é o mínimo para trabalhar no código sem quebrar as
decisões que sustentam o projeto.

## Comandos

```bash
python3 -m unittest discover -s tests -t .        # suíte completa (offline)
python3 -m anonimizador_juridico servir           # interface web em :8765
python3 -m anonimizador_juridico anonimizar -e peca.txt -s saida.txt -c cofre.json
python3 -m anonimizador_juridico verificar -e peca.txt   # só varredura de injeção
python3 exemplos/uso_basico.py                    # três formas de uso
```

Python 3.10+. **O núcleo não tem dependência externa** — `anthropic` e
`cryptography` são opcionais e o sistema degrada com aviso quando faltam.
Não introduza dependência no núcleo sem necessidade real: rodar sem instalar
nada é o que permite a instalação em escritório e departamento jurídico.

## Arquitetura

```
tipos.py       catálogo de dados pessoais, gravidade, estruturas de resultado
validadores.py CPF, CNPJ, PIS, CNH, título, processo CNJ, Luhn
detectores.py  regex + heurística de nomes + localidades
cofre.py       pseudônimos estáveis, variantes de grafia, persistência, cifragem
extratores.py  .txt, .docx (sem dependência), .html, .pdf (pypdf opcional)
defesas.py     injeção de prompt: higienização, padrões, canário
llm.py         cliente Claude opcional + contratos JSON
agente_anonimizador.py   AGENTE 1 — anonimiza, não julga o próprio trabalho
agente_auditor.py        AGENTE 2 — refaz a detecção do zero, é quem aprova
orquestrador.py          laço anonimizar → auditar → corrigir
perfis.py      configurações prontas que ajustam os dois agentes juntos
cli.py         linha de comando
web/           interface local (http.server + uma página, sem framework)
```

## Regras que não devem ser afrouxadas

1. **A camada determinística roda antes e sozinha decide o que é documento.**
   Dígito verificador é prova; modelo de linguagem é palpite. Essa ordem também
   é a defesa contra injeção de prompt — regex não obedece a instrução.
2. **O texto é mascarado antes de qualquer chamada de rede.** O provedor do
   modelo nunca recebe CPF real.
3. **O auditor não confia na lista do anonimizador.** Ele redetecta do zero,
   com limiar mais baixo. Não passe as ocorrências de um para o outro.
4. **O modelo nunca reescreve a peça.** A verificação de integridade existe
   para barrar isso (todo trecho preservado tem de existir no original, na
   mesma ordem).
5. **Falhar fechado.** Verificação pedida e não executada reprova
   (`verificacao_incompleta`); canário ausente descarta a resposta semântica
   inteira. Silêncio nunca vira aprovação.
6. **O relatório não repete o dado que denuncia.** Achado de dado pessoal sai
   mascarado; texto de injeção sai em claro (quem revisa precisa lê-lo).

## Convenções

- Código, identificadores, mensagens e commits em **português**.
- Comentário explica *por que*, não *o quê* — e vários deles registram um
  defeito real já corrigido (deslocamento de trecho, nome atravessando
  parágrafo, variante de grafia no cofre). Não os remova ao refatorar.
- Todo teste roda **offline**: a camada de LLM é exercitada com o dublê
  `ClienteFalso` em `tests/test_agentes.py`, que ecoa o canário como um modelo
  íntegro faria (`subvertido=True` simula o modelo manipulado).
- Novo tipo de dado pessoal entra em `tipos.py` + uma `Regra` em
  `detectores.py`; o auditor passa a cobrá-lo automaticamente.
- Falso positivo recorrente (termo jurídico virando nome) entra em
  `TERMOS_INSTITUCIONAIS` ou `PALAVRAS_NAO_NOME`.

## Onde o projeto vai

`PLATAFORMA.md` tem o roteiro técnico (fases 00 a 03) e as decisões de
arquitetura a preservar na evolução para multicliente.
