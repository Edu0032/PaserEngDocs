# Test report — v61.0.75-correction-output-contract-and-review-index

## Resultados executados

- `python -m compileall -q parser_browser/app api_docling/app` — OK
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=parser_browser pytest -q` — 237 passed antes da inclusão dos testes v74 específicos
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=parser_browser pytest -q tests/test_v61_0_74_release_integrity_diff_scan.py` — 2 passed
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=parser_browser pytest -q tests/test_v61_0_74_release_integrity_diff_scan.py tests/test_v61_0_73_inline_totals_strategic_diff_recovery.py tests/test_v61_0_72_total_lines_diff_scan_correction.py tests/test_v61_0_71_row_inventory_proof.py` — 12 passed
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=api_docling pytest -q api_docling/tests` — 4 passed
- `node --check parser_browser/browser/pyodide/pyodide-parser-worker.js` — OK
- `node --check parser_browser/browser/demo/pyodide/pyodide-parser-worker.js` — OK
- `node --check parser_browser/browser/demo/api-pdf-browser.js` — OK
- `python tools/quality_safety_scan.py .` — OK
- `python tools/release_integrity_scan.py .` — OK
- `zip -T` nos pacotes gerados — OK

## Validações específicas

- `base_config` global sem exemplos específicos do documento de teste: `74209/001`, `00006079`, `COMP.JCO.3`, `CP - 120`, `ANP 01`, `5503041`, `2003373`.
- Manifest do bundle com SHA real do `api_pdf_pyodide_src.zip`.
- Scan diferencial occurrence-aware validado por teste: uma segunda ocorrência física do mesmo código/banco com cauda diferente não é mascarada pela primeira ocorrência já presente no JSON.
- `documento_correcao` não recebe mais `final_integrity_orchestrator` pesado na raiz; debug detalhado fica em `analise_orcamentaria.debug_recovery`.
- Totais do orçamento continuam inline: metas/submetas em `custo_total`, itens folha em `custo_parcial`.
