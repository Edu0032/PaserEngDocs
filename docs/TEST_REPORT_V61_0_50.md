# Test report v61.0.50

Comandos usados:

```bash
python -m compileall -q parser_browser/app api_docling/app
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=parser_browser pytest -q
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=api_docling pytest -q api_docling/tests
node --check parser_browser/browser/pyodide/pyodide-parser-worker.js
node --check parser_browser/browser/demo/pyodide/pyodide-parser-worker.js
node --check parser_browser/browser/demo/api-pdf-browser.js
python tools/quality_safety_scan.py .
zip -T <monorepo.zip>
zip -T <bundle.zip>
```

Testes novos:
- `test_v61_0_50_repairs_incomplete_composition_principal_without_copying_budget_quantity`
- `test_v61_0_50_quality_gate_allows_internal_math_status_floats_but_not_public_float`
- `test_v61_0_50_enrichment_scans_public_domain_not_audit_details`
