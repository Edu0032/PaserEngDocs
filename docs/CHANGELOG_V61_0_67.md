# v61.0.67 — Golden real-flow and evidence registry

## Objetivo
Consolidar evidências em um registro central e tornar os testes de fluxo real/golden permanentes para evitar regressão nas correções de orçamento sintético e composições SINAPI-like. O motor SICRO não foi alterado.

## Mudanças principais
- Novo `parser_browser/app/parser/evidence_registry.py`.
- `integrity_orchestrator` agora consolida evidências após recovery, token fidelity, banded closure e public numeric evidence.
- `final_quality_metrics` expõe métricas do evidence registry.
- `composition_banded_closure` registra políticas de ownership/fragment lock e motivo de fechamento.
- Novos testes golden de fluxo real para `93391/00001297`, `89446`, ownership do `52.365,69`, policy Lovable e registry central.

## Política mantida
- Campo público = valor físico do PDF.
- Matemática valida e seleciona candidatos; não sobrescreve valor público.
- Composição com campos numéricos críticos ausentes não pode sair como ok.
- Lovable não deve recalcular totais públicos.
