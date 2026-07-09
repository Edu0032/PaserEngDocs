# Test report — v61.0.51

## Testes executados

```txt
python -m compileall -q parser_browser/app api_docling/app
OK

PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=parser_browser pytest -q
161 passed

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

## Teste de fluxo completo pós-merge com PDF real

Foi executado `run_output_contract_final_flow_file_json` usando o PDF DERACRE real e o JSON final gerado pela v61.0.50 como entrada de regressão.

Resultado comprovado:

```txt
status = ok
quality_gate_ok = true
quality_gate_issues = 0
89446|SINAPI principal.quant = 1
89446|SINAPI principal.valor_unit = 5,47
89446|SINAPI principal.total = 5,47
composition_principal_cascade_fields_repaired = 3
total_registros_com_erro = 0
total_pendencias_revisao = 28
```

O relatório do teste foi salvo em `/mnt/data/v61_0_51_full_flow_check.json` durante a geração desta versão.
