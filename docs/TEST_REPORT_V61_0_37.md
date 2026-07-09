# Test Report — v61.0.39-deep-area-sweep-iterative-closure

## Comandos executados

```bash
python -m compileall -q parser_browser/app api_docling/app
PYTHONPATH=parser_browser pytest -q
PYTHONPATH=api_docling pytest -q api_docling/tests
node --check parser_browser/browser/pyodide/pyodide-parser-worker.js
node --check parser_browser/browser/demo/pyodide/pyodide-parser-worker.js
node --check parser_browser/browser/demo/api-pdf-browser.js
python tools/quality_safety_scan.py .
zip -T api_pdf_v61_0_37_monorepo_targeted_recovery_batching_config_ui.zip
zip -T lovable_browser_bundle_v61_0_37.zip
```

## Resultado

```text
100 passed
4 passed
compileall OK
node --check OK
quality_safety_scan OK
zip integrity OK
```

## Casos cobertos

- Worker contém targeted recovery em lotes.
- Falha de lote vira `error_nonfatal` e não derruba o fluxo.
- Patches/unresolved de vários lotes são mesclados.
- `base_config` declara interface admin e interface usuário.
- Exemplos de payload são semânticos e não misturam runtime/API.
- Payload preenchido preserva colunas agrupadas e coluna `tipo` ignorada.
- API Docling v36 mantém CORS, `/health`, `/healthz` e autenticação.
