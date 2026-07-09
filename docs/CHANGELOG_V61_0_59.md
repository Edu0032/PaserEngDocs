# v61.0.59 — document fidelity and public numeric guard

## Objetivo

Fortalecer a política central do parser: **campo público = valor físico extraído do PDF**. Evidências, consenso e cálculos continuam sendo usados para validação, aproximação e auditoria, mas não podem substituir automaticamente os valores públicos do orçamento/composição.

## Correções aplicadas

1. **Correção do mapeamento de cabeçalho SINAPI-like**
   - O resolvedor de cabeçalhos não aceita mais substring curta insegura.
   - Alias curto como `UN`/`UM` não captura `Valor Unit`.
   - Mapeamento esperado confirmado: `Und -> und`, `Quant. -> quant`, `Valor Unit -> valor_unit`, `Total -> total`.

2. **Preservação de tokens numéricos físicos**
   - O orçamento sintético agora carrega `detalhes.numeric_source` enquanto o pipeline trabalha internamente.
   - As composições SINAPI-like também preservam `numeric_source` para `quant`, `valor_unit` e `total`.
   - Antes da exportação pública, esses tokens são reaplicados e os detalhes transitórios são removidos.

3. **Cálculo deixou de sobrescrever valor público**
   - `composition_principal_cascade_repair` não preenche mais `quant`, `valor_unit` ou `total` por soma dos componentes.
   - Quando a soma dos componentes existe, ela fica em `detalhes._calc.component_sum_reported` e em warnings/blocked auditáveis.
   - Se faltar valor público, o campo deve ser recuperado por evidência física/reextração, não por cálculo.

4. **Regressão documentada do caso 93391**
   - Orçamento `93391`: `69,88`, `84,99`, `10.923,76` preservados via `numeric_source`.
   - Composição `93391`: `1,0000000`, `69,88`, `69,88` preservados.
   - Auxiliar `88256`: `0,2411000`, `31,60`, `7,61` preservados.
   - Insumo `00001297`: `1,0571000`, `45,18`, `47,75` preservados.
   - Valores calculados problemáticos `69,91`, `85,03`, `10.928,91` não sobrevivem quando há token físico correto.

## Regra consolidada

- Orçamento sintético escreve campos públicos do orçamento.
- Composições analíticas escrevem campos públicos da composição.
- Cálculos e consenso são validação/auditoria.
- Se houver conflito entre cálculo e PDF, o JSON público fica com o PDF; a diferença vai para auditoria/correção.
