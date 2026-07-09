# Manual dos outputs — v61.0.55

## Contrato estável

A partir da v61.0.55 os outputs principais seguem `schema_version = outputs.v1`.

## Documentos

### `final_result`

É o JSON limpo usado para alimentar o sistema. Contém principalmente:

- `orcamento_sintetico`
- `composicoes`
- metadados mínimos
- `documento_correcao`, `documento_evidencias`, `documento_enriquecimento` e `analise_orcamentaria` anexados no retorno completo do browser

### `documento_correcao`

Documento para decisão humana. Deve conter:

- `painel_lovable`
- `auditoria_humana`
- `bloqueantes`
- `revisoes_recomendadas`
- `avisos`
- `decisao_uso_lovable`

Regra: diagnóstico pesado não deve virar erro para o usuário sem impacto em campo, matemática ou cobertura.

### `documento_evidencias`

Documento técnico de prova. Contém:

- índices de evidência
- cobertura
- reparos em cascata
- diagnóstico de divergência matemática
- validação de cadeias

### `documento_enriquecimento`

Documento para melhorar base_config/admin. Não é correção, não é evidência de campo e não atualiza nada automaticamente.

Seções importantes:

- `unit_candidates`
- `bank_aliases_detected`
- `code_patterns_detected`
- `sugestoes_por_confianca`

### `analise_orcamentaria`

Documento analítico para Lovable/UI:

- `accuracy_report`
- `entity_confidence_report`
- `extraction_coverage_report`
- `base_config_layering`
- `output_contract_validation`
- `outputs_package_manifest`
- `output_schema_stability`
- `lovable_operational_summary`

## Base config configurável

Fluxo simples:

```text
base_config efetivo =
  base_config default do ZIP
  + overlay/cópia do administrador
  + overlay do usuário/projeto
```

O ZIP não é alterado. O Lovable persiste overlays fora do ZIP e envia ao parser em runtime. O parser faz merge em memória.

## SICRO

A regra continua:

```text
tem item próprio → principal
não tem item próprio → auxiliar global
```

Se uma composição SICRO tem item, mas não aparece no sintético, o parser não reclassifica: registra para o Lovable revisar.
