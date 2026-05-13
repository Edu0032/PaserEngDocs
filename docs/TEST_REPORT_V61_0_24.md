# Test Report — v61.0.24

## Comandos executados

```text
python -m compileall -q parser_browser/app api_docling/app
PYTHONPATH=parser_browser pytest -q
node --check parser_browser/browser/pyodide/pyodide-parser-worker.js
node --check parser_browser/browser/demo/pyodide/pyodide-parser-worker.js
zip -t api_pdf_v61_0_24_monorepo_profile_aware_budget_sinapi_recheck.zip
zip -t lovable_browser_bundle_v61_0_24.zip
```

## Resultado

```text
42 passed
node --check OK
compileall OK
zip -t OK
```

## Testes novos da v61.0.24

- Classificador diferencia códigos de valores:
  - aceita `CADM.01`, `COMP.JCO.3`, `CP - 120`, `74209/001`, `103672-01`;
  - reconhece `1.234,56` e `6,05` como valores pt-BR.
- Veto anti-poluição rejeita repetições genéricas:
  - `Insumo Insumo Insumo Insumo`;
  - `Material Material Material`;
  - `Custo Total das Atividades =>`.
- Registry de descrição confirmada corrige:
  - orçamento sintético truncado;
  - composição SINAPI-like truncada.
- Perfil de colunas separa `budget.descricao` e `composition.descricao`.
- Targeted recovery local recupera linha quebrada para baixo.
- Targeted recovery local recupera fragmento acima da linha alvo.
- Recovery agent grava patch não-prefixado em `composicoes.sinapi_like` quando há evidência de fragmento acima.
