# Relatório de testes — v61.0.30

Comandos executados no monorepo extraído:

```text
python -m compileall -q parser_browser/app api_docling/app
PYTHONPATH=parser_browser pytest -q
node --check parser_browser/browser/pyodide/pyodide-parser-worker.js
node --check parser_browser/browser/demo/pyodide/pyodide-parser-worker.js
python tools/quality_safety_scan.py .
zip -T api_pdf_v61_0_30_monorepo_guarantee_safe_recovery_v2.zip
zip -T lovable_browser_bundle_v61_0_30.zip
```

Resultado esperado da suíte:

```text
69 passed
compileall OK
node --check OK
quality_safety_scan OK
zip integrity OK
```

## Testes novos relevantes

- `test_cross_table_reconcile_runs_first_and_repairs_composition_from_budget_when_safe`
- `test_page_line_graph_marks_budget_financial_and_item_boundaries`
- `test_recovery_uses_learned_document_profile_when_column_maps_are_absent`
- `test_recovery_rejects_long_candidate_when_current_is_already_good_even_if_issue_says_broken`
- `test_guarantee_layer_formats_budget_public_numbers_and_flags_unsynced_gate`
