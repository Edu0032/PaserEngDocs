# Manual Lovable — Revisões e Confiança por Entidade v61.0.53

## `documento_correcao.auditoria_humana`

Use esta seção para montar a fila de revisão da interface.

- `bloqueantes`: precisam ser resolvidos antes de confiar no resultado.
- `revisoes_recomendadas`: revisão útil, mas não necessariamente bloqueia exportação.
- `avisos`: informações relevantes, geralmente não bloqueantes.

Cada item deve ser lido com:

- `severity`
- `type` ou `categories`
- `codigo`, `banco`, `item`
- `message`
- `evidence`
- `impacto`
- `suggested_action`

## `analise_orcamentaria.entity_confidence_report`

Mostra confiança por entidade:

- `budget_item`
- `composition_principal`
- `sicro_principais`
- `sicro_auxiliares_globais`

Níveis:

- `high`: entidade muito confiável.
- `medium`: entidade utilizável, mas com diagnóstico leve.
- `review`: precisa de atenção.

## `documento_evidencias.component_mismatch_diagnostics`

Mostra composições cuja soma dos componentes não fecha com a principal.

O parser tenta identificar linhas candidatas que explicam a divergência. Se não houver candidato e todos os valores foram extraídos corretamente, o caso deve ser tratado como provável erro humano/documental.

## `documento_enriquecimento`

Continua servindo apenas para enriquecer base_config/admin após aprovação humana. Não é documento de correção e não deve alterar regras automaticamente.
