# Test Report — v61.0.48-output-contract-and-human-error-correction

## Validações executadas

```bash
python -m compileall -q parser_browser/app api_docling/app
PYTHONPATH=parser_browser pytest -q  # executado em lotes por limite do ambiente
PYTHONPATH=api_docling pytest -q api_docling/tests
node --check parser_browser/browser/pyodide/pyodide-parser-worker.js
node --check parser_browser/browser/demo/pyodide/pyodide-parser-worker.js
node --check parser_browser/browser/demo/api-pdf-browser.js
python tools/quality_safety_scan.py .
```

## Resultado

- Parser/browser: 127 tests collected / 127 passed.
- API Docling: 4 passed.
- compileall: OK.
- node --check: OK.
- quality_safety_scan: OK.

## Mini-fluxo completo validado

O teste `test_v43_mini_flow_runs_puzzle_resolver_and_closes_from_raw_physical_evidence` cria um PDF sintético com ocorrência de `89446|SINAPI` fora dos ranges conhecidos e confirma que:

1. `Physical Evidence Index` varre fora dos ranges.
2. `raw_occurrence_context_parser` coleta texto bruto.
3. `Line Certainty Closure` reexecuta usando o índice físico.
4. `Budget Puzzle Resolver` entra no relatório de fechamento.
5. `Entity Relation Graph` identifica relações orçamento ↔ composição principal e auxiliar contextual ↔ auxiliar global.
6. Campo `total` vazio é fechado usando evidência física bruta + consenso, não matemática isolada.
7. `documento_correcao` recebe `budget_puzzle_resolver`.

## Testes novos

- `test_v43_entity_relation_graph_treats_budget_as_puzzle`
- `test_v43_physical_index_scans_outside_known_intervals_as_raw_context`
- `test_v43_mini_flow_runs_puzzle_resolver_and_closes_from_raw_physical_evidence`
- `test_v43_budget_puzzle_context_builds_fragment_ownership_graph`
