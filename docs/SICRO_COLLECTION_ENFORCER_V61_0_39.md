# SICRO Collection Enforcer — v61.0.39

## Regra oficial

- Composição SICRO com número de item → `composicoes.sicro.principais`.
- Composição SICRO sem número de item → `composicoes.sicro.auxiliares_globais`.

O enforcer não depende de a composição aparecer ou não no orçamento. A classificação final depende apenas de item.

## Por que existe

Mesmo que o motor SICRO nativo classifique corretamente, etapas de merge, fallback ou compatibilidade podem misturar coleções. O enforcer final protege o JSON consolidado.

## Auditoria

Movimentos ficam em:

```txt
meta.performance.sicro_collection_enforcer
documento_correcao.sicro_collection_enforcer
documento_correcao.warnings[] tipo=sicro_collection_enforced
```
