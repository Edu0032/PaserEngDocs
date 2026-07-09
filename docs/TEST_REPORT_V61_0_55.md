# Test report — v61.0.55

Validações executadas:

```text
python -m compileall -q parser_browser/app api_docling/app
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=parser_browser pytest -q
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=api_docling pytest -q api_docling/tests
node --check parser_browser/browser/pyodide/pyodide-parser-worker.js
node --check parser_browser/browser/demo/pyodide/pyodide-parser-worker.js
node --check parser_browser/browser/demo/api-pdf-browser.js
python tools/quality_safety_scan.py .
zip -T monorepo
zip -T bundle Lovable
```

Resultado esperado do fluxo DERACRE validado:

```text
status = ok
quality_gate_ok = true
status_uso = utilizavel
orcamento.math_ok_rate = 1.0
orcamento.coverage_rate = 1.0
composicoes.required_field_rate = 1.0
SICRO: regra tem item/principal e sem item/auxiliar preservada
outputs_package_manifest presente
schema_version = outputs.v1 nos documentos públicos
```
