# Test Report — v61.0.53

## Bateria executada

```txt
python -m compileall -q parser_browser/app api_docling/app
OK

PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=parser_browser pytest -q
169 passed

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

Entrada usada: PDF DERACRE real + resultado v52 de regressão.

```txt
status = ok
version = v61.0.55-architecture-cleanup-and-output-schema-stability
quality_gate_ok = true
quality_gate_issues = 0

89446|SINAPI:
quant = 1
valor_unit = 5,47
total = 5,47

budget_math_ok_rate = 1.0
budget_required_field_rate = 1.0
composition_principal_required_field_rate = 1.0
composition_principal_triplet_ok_rate = 1.0
composition_component_sum_ok_rate = 0.982456

human_review_queue_count = 15
bloqueantes = 0
revisoes_recomendadas = 1
avisos = 14
targeted_recovery_diagnostic_ignored = 492

entity_confidence_summary:
high = 148
medium = 1
review = 0
```

## Interpretação

A versão manteve o orçamento matematicamente fechado, manteve bloqueantes em zero, preservou a correção da composição `89446|SINAPI` e reduziu o ruído de revisões recomendadas, separando avisos de problemas realmente acionáveis.
