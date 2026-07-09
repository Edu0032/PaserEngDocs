# Test report v61.0.68

## Testes automatizados
- `python -m compileall -q parser_browser/app api_docling/app` — OK
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=parser_browser pytest -q` — 217 passed
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=api_docling pytest -q api_docling/tests` — 4 passed
- `node --check parser_browser/browser/pyodide/pyodide-parser-worker.js` — OK
- `node --check parser_browser/browser/demo/pyodide/pyodide-parser-worker.js` — OK
- `node --check parser_browser/browser/demo/api-pdf-browser.js` — OK
- `python tools/quality_safety_scan.py .` — OK

## Validação com PDF real e JSON problemático v61
- `run_core_extraction_accuracy_flow_file_json` com PDF real + JSON problemático anterior:
  - `status = ok`
  - `extraction_status.ok = true`
  - `document_consistency_status.ok = true`
  - `quality_gate.ok = true`
  - `coverage_pre_recovery_targets = 4`
  - `coverage_post_recovery_blocking_targets = 0`
  - `composition_closed_count = 403`
  - `composition_with_missing_numeric_count = 0`

## Validação com PDF real e JSON limpo v65
- `run_core_extraction_accuracy_flow_file_json` com PDF real + JSON v65:
  - `status = ok`
  - `extraction_status.ok = true`
  - `document_consistency_status.ok = true`
  - `quality_gate.ok = true`
  - `composition_closed_count = 403`
  - `composition_with_missing_numeric_count = 0`
