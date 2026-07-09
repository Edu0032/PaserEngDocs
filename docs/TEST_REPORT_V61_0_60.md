# Test report — v61.0.60

## Testes automatizados

```txt
python -m compileall -q parser_browser/app api_docling/app
OK

PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=parser_browser pytest -q
196 passed

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

## Teste direcionado com PDF real

Arquivo: `[6]-0015690782_Orcamento (3)(26).pdf`.

Fluxo parcial reproduzível: orçamento 2–4 + composição página 24 + merge + recuperação física.

Tempos observados:

```txt
budget_s = 2.61
comp24_s = 1.58
merge_s = 4.69
recovery_s = 0.74
status = ok
quality_gate_ok = true
quality_gate_issues = 0
```

Resultado `93391`:

```txt
principal: m² / 1,0000000 / 69,88 / 69,88
88256: H / 0,2411000 / 31,60 / 7,61
88316: H / 0,1290000 / 24,36 / 3,14
00001381: KG / 9,1325000 / 1,08 / 9,86
00034357: KG / 0,2410000 / 6,34 / 1,52
00001297: m² / 1,0571000 / 45,18 / 47,75
math_status = ok
component_sum = 69,88
missing_component_totals = 0
```

## Teste sobre JSON final anterior v61.0.59

Entrada: `final_v61.0.59-document-fidelity-and-public-numeric-guard.json` + PDF completo.

Resultado da recuperação física standalone:

```txt
seconds = 26.21
status = ok
quality_gate_ok = true
quality_gate_issues = 0
patches_applied = 21
```

Correção aplicada no caso crítico:

```txt
00001297:
und = m²
quant = 1,0571000
valor_unit = 45,18
total = 47,75
```

Valores indevidos não aparecem no resultado recuperado:

```txt
69,91 = 0 ocorrências
85,03 = 0 ocorrências
10.928,91 = 0 ocorrências
```

## Observação honesta

A tentativa de rodar novamente o intervalo completo de composições `9–148` desde a extração inicial excedeu o tempo limite deste ambiente. Foi validado o fluxo direcionado com extração real da página problemática e o fluxo de recuperação física sobre o JSON final completo anterior, usando o PDF completo.
