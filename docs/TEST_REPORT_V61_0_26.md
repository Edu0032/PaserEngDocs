# Relatório de testes — v61.0.26

## Comandos executados

```text
python -m compileall -q parser_browser/app api_docling/app
PYTHONPATH=parser_browser pytest -q
node --check parser_browser/browser/pyodide/pyodide-parser-worker.js
node --check parser_browser/browser/demo/pyodide/pyodide-parser-worker.js
zip -T api_pdf_v61_0_26_monorepo_evidence_graph_profile_reparse.zip
zip -T lovable_browser_bundle_v61_0_26.zip
```

## Resultado

```text
52 passed
compileall OK
node --check OK
zip integrity OK
```

## Casos cobertos

- Evidence Graph confirma descrição por repetição/cross-table e corrige orçamento + composição.
- Descrição confirmada gera bloqueio negativo contra fragmentos indevidos.
- Perfil aprendido separa bandas de orçamento e composição.
- `selective_reparse_plan` lista alvos fracos de orçamento e composição.
- Targeted recovery de orçamento retorna hipóteses pontuadas e patch aplicável.
- Classificador aceita `CADM.01`, `COMP.JCO.3`, `CP - 120`, `74209/001`, `103672-01` como códigos.
- Classificador rejeita `1.234,56`, `6,05`, `100,0000` como código e reconhece como valor pt-BR.
- Payload Docling preserva header↔canônico e `first_row_samples`, sem enviar chaves de transporte/API key como regra de processamento.
