# Test report — v61.0.71

## Testes executados

```txt
python -m compileall -q parser_browser/app api_docling/app
OK

PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=parser_browser pytest -q
231 passed

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
```

## Validação de fluxo real

Foram gerados relatórios em `validation_v61_0_71_full_block_coverage_proof_row_inventory.zip`.

### Casos críticos

- `93391 / 00001297` recuperado com `m² / 1,0571000 / 45,18 / 47,75`.
- `89446` recuperado com `M / 1,0000000 / 5,47 / 5,47`.
- `52.365,69` permanece em Meta `1`, e a submeta `1.1` não carrega mais o total indevido.
- `row_inventory_proof_status = complete` nos fluxos críticos.
- `row_inventory_json_open_rows = 0`.
- `row_inventory_orphan_numeric_fragments = 0`.
- `quality_gate.ok = true` e `blocking_issue_count = 0`.

## Observação

Não foi executada reextração completa do zero das páginas 9–148. A validação principal foi feita no fluxo real com páginas críticas e com não regressão usando PDF completo + JSON limpo anterior.
