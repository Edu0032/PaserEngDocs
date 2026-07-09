# Test Report — v61.0.45 Pipeline Consolidation and Closure Hardening

## Validações executadas

```bash
python -m compileall -q parser_browser/app api_docling/app
PYTHONPATH=parser_browser pytest -q
PYTHONPATH=api_docling pytest -q api_docling/tests
node --check parser_browser/browser/pyodide/pyodide-parser-worker.js
node --check parser_browser/browser/demo/pyodide/pyodide-parser-worker.js
node --check parser_browser/browser/demo/api-pdf-browser.js
python tools/quality_safety_scan.py .
zip -T api_pdf_v61_0_45_monorepo_pipeline_consolidation_and_closure_hardening.zip
zip -T lovable_browser_bundle_v61_0_45.zip
```

## Resultado esperado da bateria

- Parser browser: 139 passed.
- API Docling: 4 passed.
- Compileall: OK.
- Node check: OK.
- Quality scan: OK.
- ZIP integrity: OK.

## Testes novos

- `test_v61_0_45_pipeline_consolidation.py`
  - Confirma ordem consolidada do pipeline.
  - Confirma efeito rastreável das etapas.
  - Confirma deduplicação de warnings.
  - Confirma criação de pendências acionáveis.
  - Confirma `auditoria_consolidada`, `resumo_executivo` e `ordem_execucao_pipeline` no `documento_correcao`.
  - Confirma `analise_orcamentaria.pipeline_consolidation` no JSON final.
