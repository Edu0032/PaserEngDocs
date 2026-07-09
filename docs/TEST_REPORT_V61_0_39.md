# Test Report — v61.0.39-deep-area-sweep-iterative-closure

Executado em ambiente limpo a partir do ZIP v61.0.38 enviado pelo usuário.

## Comandos

```bash
python -m compileall -q parser_browser/app api_docling/app
PYTHONPATH=parser_browser pytest -q
PYTHONPATH=api_docling pytest -q api_docling/tests
node --check parser_browser/browser/pyodide/pyodide-parser-worker.js
node --check parser_browser/browser/demo/pyodide/pyodide-parser-worker.js
node --check parser_browser/browser/demo/api-pdf-browser.js
python tools/quality_safety_scan.py .
```

## Resultados

```txt
compileall OK
parser_browser/tests: 111 passed
api_docling/tests: 4 passed
node --check OK
quality_safety_scan OK
```

## Novos testes relevantes

- Validadores rejeitam código como unidade/número.
- Commit aceita campo numérico e reexecuta closure.
- Cruzamento leve recupera descrição/unidade/valor sem copiar quantidade.
- Full PDF Code-Bank Sweep é target separado de fallback tardio.
- Deep Area Sweep recupera `valor_unit` por banda de coluna.
- Worker contém ciclo iterativo de recovery e target global por código+banco.
- SICRO sem item é movido para `auxiliares_globais`.
