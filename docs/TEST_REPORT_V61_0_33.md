# Relatório de testes — v61.0.33

Comandos executados no monorepo final:

```text
PYTHONPATH=parser_browser pytest -q
python -m compileall -q parser_browser/app api_docling/app
node --check parser_browser/browser/pyodide/pyodide-parser-worker.js
node --check parser_browser/browser/demo/pyodide/pyodide-parser-worker.js
node --check parser_browser/browser/demo/api-pdf-browser.js
python tools/quality_safety_scan.py .
```

Resultado:

```text
79 passed
compileall OK
node --check OK
quality_safety_scan OK
```

Testes novos adicionados:

```text
- correção cross-table segura de orçamento truncado usando composição confirmada;
- bloqueio de patch em item de orçamento que já está correto;
- quarentena de descrição poluída no Evidence Graph;
- geração de alvo cirúrgico quando não há candidato seguro;
- worker coletando alvos do Selective Field Reparse Executor.
```
