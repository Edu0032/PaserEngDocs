# Test Report — v61.0.53

## Testes automatizados

```txt
python -m compileall -q parser_browser/app api_docling/app
OK

PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=parser_browser pytest -q
165 passed

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

## Fluxo completo validado

Foi executado `run_output_contract_final_flow_file_json` com o PDF DERACRE real e JSON final de regressão.

Resultado:

```txt
status = ok
quality_gate_ok = true
quality_gate_issues = 0
89446|SINAPI = quant 1, valor_unit 5,47, total 5,47
budget_math_ok_rate = 1.0
budget_required_field_rate = 1.0
composition_principal_required_field_rate = 1.0
composition_principal_triplet_ok_rate = 1.0
documento_correcao.painel_lovable.status = ok
```

O arquivo de verificação foi salvo durante a geração em `/mnt/data/v52_full_flow_result.json`.
