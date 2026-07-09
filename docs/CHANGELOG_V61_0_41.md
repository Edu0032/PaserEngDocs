# Changelog — v61.0.48-output-contract-and-human-error-correction

## Objetivo

A v61.0.41 evolui a v61.0.40 para usar o documento inteiro de forma mais eficiente, sem repetir buscas pesadas linha por linha e sem criar um motor SICRO redundante.

## Principais mudanças

- Adicionado `Document Evidence Index`, um índice global por `codigo+banco` com ocorrências, campos, fontes, páginas e evidências já extraídas.
- Adicionado `Field Consensus Engine`, que usa o índice para selecionar candidatos de campo com consenso e validação antes de aplicar patches.
- Adicionado `Batch Code+Bank Occurrence Indexer`, que planeja a varredura global do PDF em lote por identidade `codigo+banco`.
- Adicionado `Adaptive Closure Scheduler`, que classifica linhas em prioridades P0/P1/P2/P3 para concentrar recuperação nas linhas críticas.
- Adicionado `Runtime Evidence Cache` para manter metadados de cache interno por execução.
- Mantida a regra da v61.0.40: matemática gera expectativa em `_calc`, mas não escreve campo público sem evidência encontrada.
- Mantido o motor SICRO separado em `parser_browser/app/sicro_only/`; a v41 não cria novo motor A-F paralelo.
- Atualizado o worker Lovable para consumir `full_pdf_code_bank_occurrence_batch_targets` antes dos alvos individuais.

## Impacto esperado

- Menos repetição em varreduras globais.
- Mais fechamento de campos vazios quando outro ponto do documento já contém o valor correto.
- Melhor rastreabilidade no `documento_correcao`.
- Menor risco de poluição, porque cada linha fechada continua bloqueando seus fragmentos para as próximas rodadas.

## Testes

- `PYTHONPATH=parser_browser pytest -q` → 121 passed.
- `PYTHONPATH=api_docling pytest -q api_docling/tests` → 4 passed.
- `python -m compileall -q parser_browser/app api_docling/app` → OK.
- `node --check` nos workers e demo browser → OK.
- `python tools/quality_safety_scan.py .` → OK.
