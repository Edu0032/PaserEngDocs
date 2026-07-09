# Changelog — v61.0.28

`v61.0.39-deep-area-sweep-iterative-closure`

## Correções bloqueadoras

- O `status` final agora reflete o `auditoria_final.quality_gate`.
  - `quality_gate.ok=false` resulta em `status="quality_gate_failed"`.
  - resultados com problemas finais reais não são mais marcados como plenamente `ok`.
- A classificação SICRO foi endurecida pela regra oficial:
  - SICRO com `item` → `composicoes.sicro.principais`;
  - SICRO sem `item` → `composicoes.sicro.auxiliares_globais`.
- O motor SICRO v20 continua sendo a fonte exclusiva para composições SICRO; o parser apenas adapta sem destruir colunas.
- O targeted recovery ficou conservador:
  - não atravessa linhas com valores financeiros;
  - não prefere hipótese longa quando a linha alvo já está boa;
  - não aplica patch que reduz similaridade com o valor atual;
  - executa pós-validação e rollback quando detecta poluição.
- O Evidence Graph recebeu quarentena de descrições poluídas:
  - bloqueia `=>`, repetição de categorias, sufixos suspeitos após `COM ENCARGOS COMPLEMENTARES` e concatenações longas de categorias.
- O correction document agora recebe issues do Quality Gate e não subnotifica falhas finais.
- Valores numéricos públicos em composições são formatados como string pt-BR no JSON final.
- O pós-filtro público detecta descrições com `=>`, fragmentos órfãos iniciando com `-`, múltiplos anchors `AF_` e sufixos suspeitos.

## Payload/Docling

- O payload Lovable foi separado logicamente em:
  - `document_payload` para dados variáveis do documento;
  - `runtime_config` para URLs, timeouts, cache e flags internas.
- `payload_usage` agora reconhece corretamente `observed_headers` com `canonical`, `sample_text`, `content_text` e `first_row_text`.
- `/docling/validate-payload` retorna `payload_split` e reporta chaves fixas que devem ficar fora do payload semântico.
- O trace do Docling agora expõe campos preenchidos para runtime, conversão, extração, adapter, cache e bundle timing.

## Testes novos

- Teste de classificação SICRO por item.
- Teste de status final sincronizado com Quality Gate.
- Teste de targeted recovery impedindo o erro real do item `3.2.7 ANP 01`.
- Teste de quarentena do Evidence Graph contra descrições poluídas.
- Teste de `payload_usage` com headers observados/canônicos.
