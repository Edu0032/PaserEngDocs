# Test Report — v61.0.48-output-contract-and-human-error-correction

Comandos executados:

```bash
python -m compileall -q parser_browser/app api_docling/app
PYTHONPATH=parser_browser pytest -q
PYTHONPATH=api_docling pytest -q api_docling/tests
node --check parser_browser/browser/pyodide/pyodide-parser-worker.js
node --check parser_browser/browser/demo/pyodide/pyodide-parser-worker.js
node --check parser_browser/browser/demo/api-pdf-browser.js
python tools/quality_safety_scan.py .
```

Resultados:

- Parser tests: 116 passed
- API Docling tests: 4 passed
- compileall: OK
- node --check: OK
- quality_safety_scan: OK

Cobertura adicionada:

- Matemática não escreve campo público sem evidência.
- `_calc.math_only_expectations` registra valores calculados.
- Contratos de relação bloqueiam cópia de quantidade contextual.
- Consenso do Full PDF Sweep rejeita candidato isolado fraco.
- Evidence grade distingue matemática pura de prova física.
- Correction document inclui final reconciliation e targets globais com consenso.
