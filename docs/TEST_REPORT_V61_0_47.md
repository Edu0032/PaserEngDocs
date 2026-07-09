# Test Report — v61.0.48-output-contract-and-human-error-correction

Comandos esperados antes do empacotamento:

```bash
python -m compileall -q parser_browser/app api_docling/app
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=parser_browser pytest -q
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=api_docling pytest -q api_docling/tests
node --check parser_browser/browser/pyodide/pyodide-parser-worker.js
node --check parser_browser/browser/demo/pyodide/pyodide-parser-worker.js
node --check parser_browser/browser/demo/api-pdf-browser.js
python tools/quality_safety_scan.py .
zip -T api_pdf_v61_0_47_monorepo_core_extraction_accuracy_and_math_field_hardening.zip
zip -T lovable_browser_bundle_v61_0_47.zip
```

Testes novos da v47:

- cascata local encontra custo parcial esperado em linha física do orçamento;
- matemática não escreve preço público usando memória de cálculo;
- composição fecha `total` por evidência física e matemática;
- `documento_enriquecimento` e `outputs_contract` são gerados com segurança.
