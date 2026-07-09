# Test Report — v61.0.54

Validações esperadas antes de empacotar:

- `python -m compileall -q parser_browser/app api_docling/app`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=parser_browser pytest -q`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=api_docling pytest -q api_docling/tests`
- `node --check parser_browser/browser/pyodide/pyodide-parser-worker.js`
- `node --check parser_browser/browser/demo/pyodide/pyodide-parser-worker.js`
- `node --check parser_browser/browser/demo/api-pdf-browser.js`
- `python tools/quality_safety_scan.py .`
- `zip -T` nos pacotes finais.

Novos testes específicos:

- merge simples de base_config: ZIP default + admin + usuário;
- coverage map para orçamento, composições e SICRO;
- documentos finais contendo cobertura e relatório de base_config layering.
