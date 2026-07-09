# Changelog — v61.0.39-deep-area-sweep-iterative-closure

## Objetivo

Adicionar um motor final de garantia de acerto que não apenas corrige campos isolados, mas tenta **fechar linhas inteiras** usando evidência cruzada, matemática e posse de fragmentos.

## Novidades

- Novo `Line Certainty Closure Engine`.
- Novo `Field Evidence Ledger`.
- Novo `Fragment Ownership Pool`.
- Novo `Numeric Constraint Solver`.
- Novo plano de `Deep Area Sweep` para campos que não fecharam.
- Validação de linhas para:
  - orçamento sintético;
  - composições SINAPI-like;
  - composições SICRO e seções A-F.
- Correction Document agora recebe `line_certainty_closure` com linhas pendentes, motivos e alvos de recuperação.
- Worker agora coleta alvos gerados pelo fechamento de linhas e envia para targeted recovery em lotes.

## Regra central

Uma linha termina em um dos estados:

- `closed_100`: todos os campos essenciais fecharam com evidência forte.
- `closed_with_warning`: conteúdo existe, mas há alerta matemático/contextual.
- `unresolved`: faltam campos, há poluição, conflito ou inconsistência.

## SICRO

SICRO continua sendo extraído pelo motor SICRO v20. A v61.0.38 apenas valida o contrato final:

- composição SICRO com `item` deve estar em `sicro.principais`;
- composição SICRO sem `item` deve estar em `sicro.auxiliares_globais`;
- seções A-F precisam preservar campos essenciais;
- incoerências SICRO entram no correction document.
