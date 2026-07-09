# 02 — Contrato de outputs

Todos os outputs públicos usam `schema_version = outputs.v1` quando aplicável.

## `final_result`

Usado para popular o sistema Lovable. Deve ser o mais limpo possível.

Contém:

- `orcamento_sintetico`
- `composicoes`
- `documento_correcao`
- `documento_evidencias`
- `documento_enriquecimento`
- `analise_orcamentaria`

## `documento_correcao`

Usado pela UI de revisão. Priorizar:

- `painel_lovable`
- `auditoria_humana.bloqueantes`
- `auditoria_humana.revisoes_recomendadas`
- `auditoria_humana.avisos`
- `possiveis_erros_humanos`
- `possiveis_falhas_extracao`

## `documento_evidencias`

Usado para explicar decisões técnicas. Não é para enriquecer base_config.

## `documento_enriquecimento`

Usado para sugerir melhorias ao admin/usuário. Nunca altera base_config sozinho.

## `analise_orcamentaria`

Painel técnico com:

- `accuracy_report`
- `extraction_coverage_report`
- `entity_confidence_report`
- `base_config_layering`
- `outputs_package_manifest`
- `lovable_operational_summary`
- `lovable_contract_reference`
