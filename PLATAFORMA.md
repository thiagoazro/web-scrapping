# Do repositório à plataforma — roteiro técnico

Versão apresentável (para compartilhar com sócios/time):
<https://claude.ai/code/artifact/7fd1ca61-c875-4370-b0d3-113f73ceeacb>

Este arquivo é o resumo executável do mesmo plano: o que precisa ser
construído, em que ordem, e quais decisões do código já foram tomadas
pensando nisso.

## O que o código de hoje já resolve (não refaça)

| Necessidade da plataforma | O que já existe |
|---|---|
| Isolamento entre clientes | `Cofre(chave_secreta=...)` / variável `ANONIMIZADOR_CHAVE` — o pseudônimo é HMAC com a chave do cliente; chaves diferentes nunca colidem |
| Anonimização irreversível | é o padrão: sem salvar o cofre, não há volta |
| Trilha de auditoria | `resultado.trilha` — hash do documento, contagem por tipo, versões, timestamp; nunca conteúdo |
| Configuração por tipo de uso | `perfis.py` — configura os dois agentes de uma vez |
| Consistência entre documentos | um `Cofre` compartilhado por lote/sessão; `--estilo hash` mantém o pseudônimo estável entre processos |
| Entrada hostil | `defesas.py` — higienização, detecção de injeção e canário |
| Falha honesta | verificação pedida e não executada reprova (`verificacao_incompleta`) |

## Fases

### Fase 00 — validar com peça real (2 semanas, custo zero)
Nada a construir. Rodar `python -m anonimizador_juridico servir` com acervo
real e revisão por amostragem; medir a taxa de peças que passam sem correção
manual, por perfil. Esse número guia todo o resto.

### Fase 01 — produto de um escritório (4 a 6 semanas)
- [ ] **OCR** em `extratores.py` (Tesseract local, sem enviar imagem para fora);
      o gancho já existe em `_de_pdf`.
- [ ] **Contas e sessão** no servidor web (hoje há só `--token` compartilhado).
- [ ] **Fila** para lote grande: extrair o processamento de `_anonimizar` para
      um worker; a API devolve id de tarefa e o cliente acompanha o status.
- [ ] **Persistência do histórico**: executar/parecer/trilha em banco
      (SQLite basta nesta fase). O documento continua efêmero.

### Fase 02 — multicliente (6 a 10 semanas)
- [ ] Chave HMAC por cliente vinda de um cofre de chaves, não de variável de
      ambiente.
- [ ] Cofre cifrado em repouso com chave do cliente (`Cofre.salvar(senha=)` já
      faz envelope com PBKDF2+Fernet; trocar por KMS quando houver).
- [ ] Log imutável de reidentificação (quem, quando, base legal).
- [ ] Cotas, limites e painel de uso.
- [ ] Retenção configurável + apagamento comprovável.
- [ ] Documentos do negócio: contrato de operador, política de privacidade,
      plano de resposta a incidente.

### Fase 03 — encaixe no fluxo (contínuo)
- [ ] Integração PJe/Projudi e sistema de gestão do escritório.
- [ ] API pública + webhook de conclusão.
- [ ] Versão instalada empacotada (o núcleo sem dependência é o que torna isso
      barato — não introduza dependência pesada sem necessidade real).

## Regras de arquitetura a preservar

1. **O documento original nunca é persistido** além da janela de
   processamento.
2. **Cofre, trilha e documento ficam em armazenamentos separados.** Quem
   compromete um não obtém o outro.
3. **A camada semântica continua opcional e isolada atrás de `llm.py`.** O
   produto precisa entregar valor com ela desligada — é a defesa contra
   dependência de fornecedor e a resposta para cliente que proíbe envio
   externo.
4. **Nada de deixar o modelo reescrever a peça.** A verificação de integridade
   existe para barrar isso; não afrouxe.
5. **Novo tipo de dado entra por `tipos.py` + `detectores.py`**, e o auditor
   passa a cobrá-lo automaticamente.

## Custo de operação (estimativa)

Petição de ~10 páginas, duas chamadas (uma por agente):

| Modo | Por documento | 1.000 documentos |
|---|---|---|
| Só determinístico | R$ 0,00 | R$ 0,00 |
| Semântico com Sonnet | ≈ R$ 0,25 | ≈ R$ 250 |
| Semântico com Opus | ≈ R$ 0,60 | ≈ R$ 600 |

Ordem de grandeza, câmbio aproximado. A camada determinística entrega a maior
parte do valor a custo marginal zero — o que sustenta cobrança por assento em
vez de por documento.
