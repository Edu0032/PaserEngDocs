# Test Report — v61.0.48-output-contract-and-human-error-correction

## Testes executados

```bash
python -m compileall -q parser_browser/app api_docling/app
PYTHONPATH=parser_browser pytest -q
PYTHONPATH=api_docling pytest -q api_docling/tests
node --check parser_browser/browser/pyodide/pyodide-parser-worker.js
node --check parser_browser/browser/demo/pyodide/pyodide-parser-worker.js
node --check parser_browser/browser/demo/api-pdf-browser.js
python tools/quality_safety_scan.py .
zip -T api_pdf_v61_0_46_monorepo_real_document_regression_and_error_driven_tuning.zip
zip -T lovable_browser_bundle_v61_0_46.zip
```

## Coberturas novas

- `test_real_pdf_physical_index_is_section_aware_and_fuses_split_rows`
- `test_memoria_and_curva_abc_are_not_allowed_to_pollute_public_price_fields`
- `test_field_consensus_uses_budget_physical_values_but_respects_section_policy`
- `test_real_document_regression_expected_core_passes_on_uploaded_pdf`

## Resultado esperado

- Physical index encontra evidências reais no PDF DERACRE.
- Fusão de baselines recupera `89446|SINAPI` no orçamento com `6,65` e `405,65`.
- Memória de cálculo não contamina preço/custo.
- Curva ABC é tratada como diagnóstica.
- `CM-30` não vira unidade `cm`.
- Expected core do PDF real fecha 100%.
