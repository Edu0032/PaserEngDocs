# Adaptive Closure e Batch Sweep — v61.0.41

## Adaptive Closure Scheduler

Classifica linhas por prioridade:

- P0: campo obrigatório crítico vazio.
- P1: matemática divergente ou campo importante pendente.
- P2: suspeita de descrição/poluição.
- P3: linha fechada, apenas protegida contra regressão.

## Batch Code+Bank Occurrence Indexer

A varredura global do PDF por `codigo+banco` passa a ser planejada em lote:

- Agrupa todas as linhas pendentes pelo mesmo ID.
- Evita varrer o PDF várias vezes para o mesmo código.
- Gera `full_pdf_code_bank_occurrence_batch_targets` para o worker.
- O worker distribui os alvos por campo e página mantendo compatibilidade com o recovery existente.

## SICRO

A v41 não cria um novo motor SICRO. O pipeline continua usando `parser_browser/app/sicro_only/`, especialmente o `SicroTwoPassPipeline`, bridge e auditorias já existentes.
