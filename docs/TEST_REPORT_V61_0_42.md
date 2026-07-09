# Test Report — v61.0.42

## Mini-fluxo físico validado
Foi criado um PDF sintético com a linha física:

`89446 SINAPI TUBO PVC ESGOTO m 1,0000000 14,27 14,27`

O JSON inicial tinha a composição `89446|SINAPI` com `total` vazio. O fluxo validado foi:

1. `enrich_physical_evidence_index_file_json` abriu o PDF.
2. `physical_evidence_index` encontrou `89446|SINAPI` uma única vez.
3. O índice detectou `und=m`, `quant=1,0000000`, `valor_unit=14,27` e `total=14,27`.
4. O closure foi reexecutado com `physical_index_used=true`.
5. O `Field Consensus Engine` aplicou `total=14,27` com fonte física.
6. O `documento_correcao` recebeu `physical_evidence_index`.

Também foi validado o caso inverso: quando o valor esperado matematicamente não aparece na linha física, ele fica apenas em `_calc` e não é escrito no campo público.

## Comandos executados

```bash
python -m compileall -q parser_browser/app api_docling/app
PYTHONPATH=parser_browser pytest -q
PYTHONPATH=api_docling pytest -q api_docling/tests
node --check parser_browser/browser/pyodide/pyodide-parser-worker.js
node --check parser_browser/browser/demo/pyodide/pyodide-parser-worker.js
node --check parser_browser/browser/demo/api-pdf-browser.js
python tools/quality_safety_scan.py .
zip -T release/api_pdf_v61_0_42_monorepo_physical_evidence_index_active_closure.zip
zip -T release/lovable_browser_bundle_v61_0_42.zip
```

## Resultado

- Parser/browser: `127 passed`
- API Docling: `4 passed`
- Node syntax checks: OK
- Quality safety scan: OK
- ZIP integrity: OK
