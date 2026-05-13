# Relatório de testes — v61.0.25

## Comandos executados

```text
python -m compileall -q parser_browser/app api_docling/app
PYTHONPATH=parser_browser pytest -q
node --check parser_browser/browser/pyodide/pyodide-parser-worker.js
node --check parser_browser/browser/demo/pyodide/pyodide-parser-worker.js
zip -T api_pdf_v61_0_25_monorepo_budget_profile_recovery.zip
zip -T lovable_browser_bundle_v61_0_25.zip
```

## Resultado

```text
47 passed
compileall OK
node --check OK
zip integrity OK
```

## Teste pequeno de fluxo completo

PDF sintético com:

- orçamento sintético na página 1;
- composição SINAPI-like na página 2;
- descrição quebrada em duas linhas no orçamento;
- descrição quebrada em duas linhas na composição;
- `structured_tables` simulando o primeiro perfil vindo do Docling.

Saída verificada:

```text
orcamento_sintetico.itens_raiz[0].filhos[0].especificacao =
ENGENHEIRO CIVIL DE OBRA JUNIOR COM ENCARGOS COMPLEMENTARES

composicoes.sinapi_like.principais["90777|SINAPI"].principal.descricao =
ENGENHEIRO CIVIL DE OBRA JUNIOR COM ENCARGOS COMPLEMENTARES

meta.performance.document_learning_profile presente = true
```
