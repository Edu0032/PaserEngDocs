# Test report — v61.0.75-correction-output-contract-and-review-index

Validações executadas nesta versão:

- `python -m compileall -q parser_browser/app api_docling/app` — OK
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=parser_browser pytest -q tests/test_v61_0_75_correction_output_contract.py` — OK
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=parser_browser pytest -q tests/test_v61_0_75_correction_output_contract.py tests/test_v61_0_74_release_integrity_diff_scan.py tests/test_v61_0_73_inline_totals_strategic_diff_recovery.py tests/test_v61_0_72_total_lines_diff_scan_correction.py` — OK
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=api_docling pytest -q api_docling/tests` — OK
- `node --check parser_browser/browser/pyodide/pyodide-parser-worker.js` — OK
- `node --check parser_browser/browser/demo/pyodide/pyodide-parser-worker.js` — OK
- `node --check parser_browser/browser/demo/api-pdf-browser.js` — OK
- `python tools/quality_safety_scan.py .` — OK
- `python tools/release_integrity_scan.py .` — OK após empacotamento/manifest.

Observação: a versão é focada no output/correction contract. Os testes validam estrutura, categorização, localização, crop hints, separação de debug e compatibilidade com as versões imediatamente anteriores.
