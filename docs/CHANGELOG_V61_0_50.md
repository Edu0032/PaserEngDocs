# v61.0.50-composition-cascade-and-output-sanity

## Objetivo
Corrigir os gargalos observados nos resultados reais da v61.0.49: composição principal incompleta, ruído no targeted recovery, quality gate acusando floats internos, enriquecimento escaneando estruturas técnicas e fronteira payload/base_config.

## Principais mudanças
- Novo `composition_principal_cascade_repair.py`.
- Composição principal SINAPI-like incompleta pode ser fechada com soma dos componentes + orçamento sem BDI, sem copiar quantidade do orçamento.
- `quality_gate` agora diferencia campos públicos de métricas internas de auditoria.
- `documento_enriquecimento` agora escaneia apenas campos públicos de domínio e evidência física controlada.
- O HTML demo deixou de incluir `fixed_contract` no payload exemplo.
- Políticas runtime/admin foram movidas para `db/base_config.d/96_runtime_policy_admin.json`.
- SICRO continua com a regra oficial: com item é principal, sem item é auxiliar global; falta de referência no sintético é informação para Lovable, não reclassificação automática.

## Política de quantidade contextual
- Quantidade do orçamento não sobrescreve quantidade da composição.
- Quantidade da auxiliar global não sobrescreve consumo da auxiliar dentro da principal.
- Quando a principal da composição está incompleta e os componentes fecham matematicamente, o parser pode restaurar `quant = 1` como quantidade-base da composição, documentando a decisão.
