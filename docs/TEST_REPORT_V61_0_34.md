# Relatório de testes — v61.0.34

Comandos executados no monorepo final:

```text
PYTHONPATH=parser_browser pytest -q
python -m compileall -q parser_browser/app api_docling/app
node --check parser_browser/browser/pyodide/pyodide-parser-worker.js
node --check parser_browser/browser/demo/pyodide/pyodide-parser-worker.js
node --check parser_browser/browser/demo/api-pdf-browser.js
python tools/quality_safety_scan.py .
zip -T api_pdf_v61_0_34_monorepo_description_ownership_crosscheck.zip
zip -T lovable_browser_bundle_v61_0_34.zip
```

Resultado esperado:

```text
83 passed
compileall OK
node --check OK
quality_safety_scan OK
zip integrity OK
```

## Testes novos

- Ownership resolver detecta candidato contendo texto do item anterior e do próximo.
- Reverse repair troca descrição longa contaminada por descrição limpa do mesmo código quando há evidência forte.
- Selective Field Reparse Executor corrige o caso `ANP 01` usando composição + contexto de vizinhança.
- Targeted recovery escolhe `target_line_only` quando a descrição curta ocupa menos de metade da célula e já parece completa.

