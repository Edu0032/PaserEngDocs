# Manual Lovable — Outputs v61.0.53

## Ordem recomendada de consumo

1. Use `final_result` para popular o sistema.
2. Leia `analise_orcamentaria.output_quality_summary` para mostrar status geral.
3. Leia `documento_correcao.painel_lovable` para decidir se o resultado está utilizável ou precisa revisão.
4. Leia `documento_correcao.auditoria_humana.bloqueantes` primeiro.
5. Depois mostre `revisoes_recomendadas` e `avisos`.
6. Use `documento_evidencias` para explicar de onde veio cada decisão/correção.
7. Use `documento_enriquecimento` apenas para sugerir melhorias de base_config/admin, nunca para corrigir o JSON automaticamente.

## `final_result`

JSON limpo para uso pelo sistema. Contém:

- `orcamento_sintetico`
- `composicoes`
- `documento_correcao`
- `documento_evidencias`
- `documento_enriquecimento`
- `analise_orcamentaria`

## `documento_correcao`

Documento de ação humana e auditoria. Campos principais:

- `resumo`: números consolidados.
- `painel_lovable`: status curto para UI.
- `auditoria_humana.bloqueantes`: problemas que exigem atenção prioritária.
- `auditoria_humana.revisoes_recomendadas`: inconsistências ou referências ausentes que não bloqueiam automaticamente.
- `auditoria_humana.avisos`: diagnósticos úteis.
- `reparos_aplicados_consolidados`: correções aplicadas.
- `candidatos_rejeitados_consolidados`: candidatos rejeitados com motivo.

### Como interpretar

- `total_registros_com_erro = 0` significa que não há erro bloqueante de extração final.
- `total_pendencias_revisao > 0` pode existir mesmo com resultado utilizável; normalmente são conferências de referência, auxiliares ausentes ou divergências humanas.
- `total_diagnosticos_targeted_recovery_ignorados` mostra ruídos/no-op que foram removidos da fila humana.

## `documento_evidencias`

Documento de prova. Contém:

- índices de evidência física/documental;
- resumo matemático;
- cascatas de reparo;
- reparos de composições principais;
- resumo de cadeias orçamento → composição.

Não deve ser usado para alterar base_config.

## `documento_enriquecimento`

Documento para aprendizado do sistema/admin. Contém:

- unidades observadas;
- candidatas a novas unidades;
- aliases de banco/fonte;
- padrões de código;
- templates/seções detectadas.

Não altera base_config automaticamente.

## `analise_orcamentaria.accuracy_report`

Relatório de acurácia do resultado atual, não comparativo entre versões. Campos úteis:

- `summary.budget_math_ok_rate`
- `summary.budget_required_field_rate`
- `summary.composition_principal_required_field_rate`
- `summary.composition_principal_triplet_ok_rate`
- `budget.math_mismatch`
- `compositions.problem_examples`
- `sicro.principais_com_item_sem_referencia_sintetico`

## `analise_orcamentaria.output_contract_validation`

Valida se os outputs estão no papel correto:

- `final_result` limpo;
- `documento_correcao` para problemas;
- `documento_evidencias` para provas;
- `documento_enriquecimento` para sugestões de base_config/admin;
- payload sem configuração interna/runtime.
