# Test report — v61.0.57

## Comandos executados

```txt
python -m compileall -q parser_browser/app api_docling/app
OK

PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=parser_browser pytest -q
183 passed

PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=api_docling pytest -q api_docling/tests
4 passed

node --check parser_browser/browser/pyodide/pyodide-parser-worker.js
OK

node --check parser_browser/browser/demo/pyodide/pyodide-parser-worker.js
OK

node --check parser_browser/browser/demo/api-pdf-browser.js
OK

python tools/quality_safety_scan.py .
OK

PYTHONPATH=parser_browser python tools/validate_lovable_contract.py --payload examples/lovable/minimal_payload.json --final examples/lovable/final_result_minimal.example.json
OK
```

## Validações específicas

- `api_pdf_pyodide_src.zip` contém `app/pipeline/stage_registry.py`, `app/config/version.py` v61.0.57 e `db/base_config.json`.
- `docs/lovable_contracts/` contém o contrato completo Lovable ↔ Python.
- `schemas/` contém schemas de input/output.
- `examples/lovable/` contém payload, runtime_options, overlays e final_result mínimo.
- HTML demo mostra aba `Contrato Lovable`.
