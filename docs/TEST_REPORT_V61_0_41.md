# Test Report — v61.0.41

## Comandos executados

```bash
python -m compileall -q parser_browser/app api_docling/app
PYTHONPATH=parser_browser pytest -q
PYTHONPATH=api_docling pytest -q api_docling/tests
node --check parser_browser/browser/pyodide/pyodide-parser-worker.js
node --check parser_browser/browser/demo/pyodide/pyodide-parser-worker.js
node --check parser_browser/browser/demo/api-pdf-browser.js
python tools/quality_safety_scan.py .
```

## Resultado

```txt
compileall OK
121 passed
4 passed
node --check OK
quality_safety_scan OK
```

## Testes novos

Arquivo: `tests/test_v61_0_41_document_evidence_index.py`

Cobertura adicionada:

- índice global de evidências por `codigo+banco`;
- consenso de campo preenchendo campo público somente com evidência já existente;
- matemática permanecendo em `_calc` quando não há evidência física/cruzada;
- alvos globais agrupados por identidade `codigo+banco`;
- scheduler adaptativo P0/P3;
- worker Lovable expondo `full_pdf_code_bank_occurrence_batch_targets`;
- garantia de que não foi criado novo motor SICRO redundante.
