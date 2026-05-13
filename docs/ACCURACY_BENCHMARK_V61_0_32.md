# Accuracy Benchmark — v61.0.32

A versão inclui um benchmark JSON-first para comparar `actual final_result` contra `expected_final_result`.

Campos avaliados por padrão:

- `codigo`
- `banco`/`fonte`
- `descricao`/`especificacao`
- `und`
- `quant`
- `valor_unit`
- `total`
- `custo_parcial`
- `custo_total`

Uso no HTML/Lovable:

1. Inclua `expected_final_result` ou `golden_expected_result` no payload de teste.
2. Execute o fluxo completo.
3. Consulte a aba **Acurácia** ou `final_result.meta.accuracy_report`.
4. Consulte a aba **Debug overlay** ou `final_result.meta.debug_overlay` para ver colunas, Quality Gate, patches e unresolved.

O objetivo é deixar de depender apenas de inspeção manual e começar a medir ganho real por campo e por versão.
