# Test report v61.0.67

Executado na sandbox:

```txt
python -m compileall -q parser_browser/app api_docling/app
OK

PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=parser_browser pytest -q
213 passed

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

Validação de fluxo real com PDF real e JSONs problemáticos/limpos:
- `from_v61_problem`: status ok, quality gate ok, blocking 0, 403/403 composições fechadas, 2141 locked rows.
- `from_v65_clean`: status ok, quality gate ok, blocking 0, 403/403 composições fechadas, 2141 locked rows.
- `post_organizer_from_v61_problem`: status ok, quality gate ok, blocking 0.

Casos conferidos:
- `93391 / 00001297` completo: `m² / 1,0571000 / 45,18 / 47,75`.
- `89446` completo: `M / 1,0000000 / 5,47 / 5,47`.
- `52.365,69` no owner correto da Meta 1, removido de `1.1`.
- `lovable_consumption_policy.do_not_recalculate_public_totals = true`.
- `documento_evidencias.evidence_registry` presente e alimentado.
