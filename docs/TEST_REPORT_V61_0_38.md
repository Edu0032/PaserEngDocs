# Test Report — v61.0.39-deep-area-sweep-iterative-closure

Testes executados:

```text
python -m compileall -q parser_browser/app api_docling/app
PYTHONPATH=parser_browser pytest -q
PYTHONPATH=api_docling pytest -q api_docling/tests
node --check parser_browser/browser/pyodide/pyodide-parser-worker.js
node --check parser_browser/browser/demo/pyodide/pyodide-parser-worker.js
node --check parser_browser/browser/demo/api-pdf-browser.js
python tools/quality_safety_scan.py .
zip -T monorepo
zip -T bundle Lovable
```

Resultado:

```text
105 passed
4 passed
compileall OK
node --check OK
quality_safety_scan OK
zip integrity OK
```

Casos específicos adicionados:

- Orçamento corrigido por composição usando `codigo|banco`.
- Auxiliar dentro de principal corrigida por auxiliar global, preservando a quantidade contextual.
- SICRO com classificação/seções inconsistentes entra no correction document.
- Campos não fechados geram `deep_area_sweep_targets` para targeted recovery.
- Worker coleta alvos do `line_certainty_closure_engine`.
