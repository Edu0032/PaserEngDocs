# Guia Lovable — Bundle v61.0.26

## Arquivo a usar

```text
release/lovable_browser_bundle_v61_0_26.zip
```

## Mudanças importantes

O payload da IA continua responsável por associar o header visual do PDF ao canônico consumido pelo código. A v61.0.26 preserva essa associação no payload enviado ao Docling, junto com `first_row_samples`/`sample_text`, mas remove do corpo do Docling informações fixas de execução que pertencem ao `base_config` ou ao worker.

## Fluxo recomendado

```text
PDF completo no browser
→ seed PDF para Docling
→ payload Docling apenas com evidência do documento
→ Normalizer local PyMuPDF
→ parser orçamento + composições
→ Evidence Graph por codigo|banco
→ recheck orçamento + SINAPI-like
→ targeted recovery local profile-aware
→ final_result + correction_document
```

## Saídas novas/importantes

```text
meta.performance.evidence_graph
meta.performance.document_learning_profile.selective_reparse_plan
meta.performance.profile_aware_recheck.evidence_graph
```

## Regra de payload

Fica no payload:

```text
ranges, seed_pages, headers observados, canônicos, first_row_samples, dicas do documento.
```

Fica no base_config/worker:

```text
regex fixos, políticas de parser, tolerâncias, regras de recheck, chaves/URLs/timeouts de transporte.
```
