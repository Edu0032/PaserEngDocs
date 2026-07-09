# Contratos de dados

## Entrada

Schemas principais:

```text
schemas/input/document_payload.schema.json
schemas/input/base_config_overlay.schema.json
schemas/input/runtime_options.schema.json
```

## Saída

Schemas principais:

```text
schemas/output/final_result.schema.json
schemas/output/correction_document.schema.json
schemas/output/evidence_document.schema.json
schemas/output/enrichment_document.schema.json
schemas/output/analytics_document.schema.json
```

## Documento de correção

O documento de correção concentra divergências e pendências revisáveis. Cada item pode conter:

- página;
- intervalo de páginas;
- composição;
- item;
- código;
- banco;
- campo;
- valor atual;
- valor encontrado no PDF;
- evidência;
- sugestão de revisão.

## Final result

`final_result` representa a saída pública e consumível pela aplicação. Debug, hipóteses e rastros internos devem permanecer fora desse contrato principal.

## Documento de evidências

`documento_evidencias` mantém índices e referências auxiliares para auditoria e revisão sem poluir a saída final.
