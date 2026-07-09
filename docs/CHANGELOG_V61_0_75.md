# v61.0.75-correction-output-contract-and-review-index

## Mudanças

- Reformulado o `documento_correcao.resumo_final_curto` para ser um contrato de revisão acionável.
- Adicionado índice plano `documento_correcao.problemas` para Lovable listar problemas sem vasculhar debug.
- Adicionado `documento_correcao.problemas_por_categoria`, separando:
  - `quality_gate`
  - `extraction`
  - `document_consistency`
  - `possible_left_behind_lines`
- Cada problema compacto passa a carregar localização estruturada, crop hint, intervalo de páginas e referência para evidência quando disponível.
- Incoerências documentais extraídas de `document_consistency_status.issues` passam a aparecer no documento de correção como problemas de categoria `document_consistency`.
- Problemas de extração extraídos de `extraction_status.issues` passam a aparecer no documento de correção como categoria `extraction`.
- Debug pesado permanece em `analise_orcamentaria.debug_recovery`, não no documento principal.
- Criado contrato Lovable: `docs/lovable_contracts/13_CORRECTION_DOCUMENT_UI_REVIEW_CONTRACT.md`.
- Atualizado `release_integrity_scan.py` para validar documentação da versão corrente dinamicamente.

## Escopo

Esta versão melhora somente o output/contrato de correção. Não altera motor SICRO, extração de composições, cálculo público ou regras de ownership.
