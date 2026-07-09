# v61.0.51 — Correction Document Actionability and Cascade Propagation

## Objetivo

Corrigir as pendências observadas no fluxo HTML/worker da v61.0.50:

- cascata de composição principal não aparecia no resultado final baixado pelo HTML em alguns fluxos;
- `quality_gate` falhava por diagnóstico interno antigo ou por estado `quality_gate_failed` não atualizado;
- `documento_correcao` misturava erro bloqueante, revisão recomendada e ruído do targeted recovery;
- targeted recovery continuava gerando muitos alvos de descrição sem ganho real;
- outputs ainda podiam carregar metadados antigos em alguns documentos pós-recovery.

## Correções principais

1. O fluxo `run_output_contract_final_flow_file_json` força uma nova rodada de `Line Certainty Closure` antes de organizar os outputs.
2. A cascata de composição principal agora é propagada até o JSON final, documento de evidências e documento de correção.
3. A composição `89446|SINAPI`, quando vem com principal sem `quant`, `valor_unit` e `total`, é fechada por soma dos componentes como:
   - `quant = 1`
   - `valor_unit = 5,47`
   - `total = 5,47`
   sem copiar a quantidade do orçamento.
4. O `quality_gate` é recalculado após os reparos e volta o status de `quality_gate_failed` para `ok` quando não há issues reais.
5. `documento_correcao.auditoria_humana` agora separa:
   - erros bloqueantes;
   - revisões recomendadas;
   - diagnósticos do targeted recovery ignorados;
   - pendências de referência/hierarquia para Lovable revisar.
6. Targeted recovery no worker ficou mais seletivo: descrições já boas ou candidatos `no_op_same_value` deixam de virar pendência humana.

## Contrato preservado

- Quantidade do orçamento não sobrescreve quantidade da composição principal.
- Quantidade de auxiliar global não sobrescreve consumo contextual dentro de composição principal.
- SICRO continua usando motor separado e regra: com item → principal; sem item → auxiliar global.
- Ausência de referência no orçamento vira revisão organizada para Lovable, não reclassificação automática.
