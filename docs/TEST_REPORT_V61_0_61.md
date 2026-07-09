# Test report — v61.0.62

## Testes automatizados

```txt
python -m compileall -q parser_browser/app api_docling/app
OK

PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=parser_browser pytest -q
198 passed

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

## Validação com PDF real

### Fluxo direcionado

- PDF: DERACRE casa do produtor.
- Orçamento: páginas 2–4.
- Composição direcionada: página 24.
- Caso crítico: `4.5.2 / 93391 / 00001297`.

Resultado validado:

```txt
status = ok
quality_gate_ok = true
severity_summary = {blocking: 0, warning: 0, info: 0}
principal 93391 = 1,0000000 / 69,88 / 69,88
00001297 = m² / 1,0571000 / 45,18 / 47,75
math_status = ok
missing_component_totals = 0
```

### Recovery sobre JSON final completo anterior

- Entrada: `final_v61.0.59-document-fidelity-and-public-numeric-guard.json`.
- Recovery físico aplicado com PDF completo.

Resultado:

```txt
patches_applied = 21
blocking_unresolved = 0
status = ok
quality_gate_ok = true
quality_gate_issues = 0
```

### Fluxo completo 9–148

Tentado nesta sandbox, mas excedeu o limite de execução de 260 segundos antes de gravar o resultado final. A validação concluída nesta versão cobre o fluxo direcionado real e a recuperação física sobre o JSON final completo anterior.
