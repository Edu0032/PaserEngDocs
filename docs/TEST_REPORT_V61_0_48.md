# Test Report — v61.0.48-output-contract-and-human-error-correction

## Testes executados

```txt
python -m compileall -q parser_browser/app api_docling/app
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=parser_browser pytest -q
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=api_docling pytest -q api_docling/tests
node --check parser_browser/browser/pyodide/pyodide-parser-worker.js
node --check parser_browser/browser/demo/pyodide/pyodide-parser-worker.js
node --check parser_browser/browser/demo/api-pdf-browser.js
python tools/quality_safety_scan.py .
zip -T api_pdf_v61_0_48_monorepo_output_contract_and_human_error_correction.zip
zip -T lovable_browser_bundle_v61_0_48.zip
```

## Cobertura nova

- separação entre `documento_evidencias` e `documento_enriquecimento`;
- enriquecimento de unidades, aliases e padrões de código;
- unidade suspeita não vira sugestão automática;
- `documento_correcao.auditoria_humana` com fila acionável;
- reorganização de outputs após recovery tardio;
- bundle Lovable com manifest e source zip atualizados.
