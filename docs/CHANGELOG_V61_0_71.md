# v61.0.71 — full-block-coverage-proof-row-inventory

## Objetivo

Fortalecer a prova de cobertura no fluxo real sem endurecer demais o parser. A versão adiciona um manifesto compacto de inventário de linhas que cruza:

- cobertura final dos blocos físicos;
- inventário PDF-first quando ele foi executado;
- linhas abertas/locked no JSON público;
- fragmentos numéricos úteis órfãos;
- escopo físico realmente avaliado.

## Mudanças principais

- Novo módulo `parser_browser/app/parser/row_inventory_proof.py`.
- Integração no `integrity_orchestrator.py` após `physical_block_coverage`.
- Novas métricas em `quality_metrics`:
  - `row_inventory_proof_status`;
  - `row_inventory_physical_scope`;
  - `row_inventory_physical_blocks_evaluated`;
  - `row_inventory_json_open_rows`;
  - `row_inventory_orphan_numeric_fragments`;
  - `row_inventory_physical_row_mismatch_count`.
- Novo teste `tests/test_v61_0_71_row_inventory_proof.py`.
- Atualização do bundle Pyodide e manifesto para v61.0.71.

## Política

O parser não deve perder resultados corretos por rigidez excessiva. Quando o inventário PDF-first não cobre todos os blocos, isso vira escopo declarado, não falha automática. Bloqueios continuam reservados para campos críticos ausentes, linhas abertas, fragmentos numéricos úteis órfãos e falhas obrigatórias do fluxo.
