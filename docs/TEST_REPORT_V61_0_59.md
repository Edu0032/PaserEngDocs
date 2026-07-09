# Test report — v61.0.59

## Testes executados

```txt
python -m compileall -q parser_browser/app api_docling/app
OK

PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=parser_browser pytest -q
193 passed

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

## Testes novos principais

Arquivo: `tests/test_v61_0_59_document_fidelity_numeric_guard.py`

1. `test_v61_0_59_header_resolver_does_not_map_un_inside_valor_unit`
   - Garante que `UN` não captura `Valor Unit`.

2. `test_v61_0_59_composition_tail_keeps_pdf_text_for_valor_unit_not_quant`
   - Garante que a linha `m² 1,0000000 69,88 69,88` vira `quant=1,0000000`, `valor_unit=69,88`, `total=69,88`.

3. `test_v61_0_59_public_output_reapplies_pdf_numeric_source_after_bad_mutation`
   - Simula mutação ruim para `69,91`, `85,03`, `10.928,91` e confirma restauração para os tokens físicos do PDF.

4. `test_v61_0_59_component_sum_is_audit_only_when_pdf_principal_is_missing`
   - Confirma que soma dos componentes `69,91` fica somente em `_calc`, sem preencher `valor_unit/total/quant` públicos.

## Observação

Não foi chamado endpoint Docling externo real neste ambiente. A validação cobriu módulos Python, fluxo local/direcionado, bundle Pyodide, contratos JS/HTML, API Docling local por testes automatizados, quality scan e empacotamento.
