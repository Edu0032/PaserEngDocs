# Relatório de testes — v61.0.28

Comandos executados no monorepo final:

```text
python -m compileall -q parser_browser/app api_docling/app
PYTHONPATH=parser_browser pytest -q
node --check parser_browser/browser/pyodide/pyodide-parser-worker.js
node --check parser_browser/browser/demo/pyodide/pyodide-parser-worker.js
python tools/quality_safety_scan.py .
PYTHONPATH=api_docling python teste manual de /docling/validate-payload com payload real v61.0.27
zip -T api_pdf_v61_0_28_monorepo_quality_gate_safe_recovery.zip
zip -T lovable_browser_bundle_v61_0_28.zip
```

Resultado:

```text
64 passed
compileall OK
node --check OK
quality_safety_scan OK
/docling/validate-payload OK
zip integrity OK
```

Validações específicas feitas:

- `payload_usage.tables.budget.canonical_mapping_used=true` com o payload real.
- `payload_usage.tables.budget.first_row_samples_used=true` com o payload real.
- `payload_usage.tables.composition.canonical_mapping_used=true` com o payload real.
- `payload_usage.tables.composition.first_row_samples_used=true` com o payload real.
- O final JSON antigo v61.0.27, quando reprocessado pelo pós-filtro v61.0.28, passa a marcar `status=quality_gate_failed` por poluições reais que antes passavam batidas.
- Blocos SICRO sem `item` são movidos para `auxiliares_globais`.
- O caso `3.2.7 ANP 01` não recebe mais fragmentos de `3.2.6` nem de `3.2.8` no targeted recovery.
