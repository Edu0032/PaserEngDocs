# Guia Lovable — Bundle v61.0.24

## Arquivo a usar

```text
release/lovable_browser_bundle_v61_0_24.zip
```

## Fluxo esperado

```text
PDF completo no browser
→ seed PDF para Docling
→ Normalizer local PyMuPDF refina Docling
→ parser orçamento
→ parser composições SINAPI-like/PRÓPRIO
→ motor SICRO v20 autoritativo
→ registry de descrições confirmadas orçamento ↔ composições
→ rechecagem forte do orçamento sintético
→ rechecagem forte SINAPI-like
→ targeted recovery local de linhas quebradas acima/abaixo
→ merge final
→ correction document final
```

## Novidades relevantes para o Lovable

- A rechecagem agora também afeta o orçamento sintético.
- O worker coleta alvos dentro do contrato novo `composicoes.sinapi_like.*`.
- O worker envia `description_registry` para o normalizer local.
- Patches de descrição podem ser aceitos mesmo quando o fragmento correto vem antes da linha principal, desde que a descrição atual esteja contida no candidato e a evidência seja forte.
- O `meta.performance.profile_aware_recheck` registra auditoria da rechecagem de orçamento e composições.

## Logs úteis

```text
profile_aware_broken_line_recheck
targeted-recovery-pdf-ready
normalizer-local-recovery-finished
targeted-recovery-patches-committed
document_learning_profile
```
