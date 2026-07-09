# v61.0.69 — physical-block coverage and compact correction

## Added
- Compact physical block coverage manifests for SINAPI-like composition blocks and budget leaves.
- Short final-state correction summary in `documento_correcao.resumo_final_curto`.
- Quality metrics for physical block coverage: complete/incomplete blocks, open rows, orphan fragments, and budget missing leaves.
- Real-flow integration through `integrity_orchestrator`.

## Policy
- The final JSON preserves PDF-declared public values.
- Composition/budget block coverage is compact: summaries and small open-row samples, not raw page text.
- Correction document is short and final-state oriented; evidence remains in `documento_evidencias`.
- SICRO engine was not changed.
