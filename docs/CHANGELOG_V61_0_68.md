# v61.0.68 — Extraction vs Document Consistency

## Objetivo
Separar explicitamente fidelidade de extração e coerência documental: o parser deve extrair fielmente o que está no PDF, preservar tokens públicos declarados e registrar divergências matemáticas como inconsistências do documento quando todos os campos físicos foram extraídos.

## Principais mudanças
- Novo `coverage_engine.py` para gerar alvos explícitos de cobertura antes e depois do recovery.
- Novo `extraction_consistency_status.py` com `extraction_status` e `document_consistency_status` no JSON final.
- Novo `evidence_conflict_resolver.py` para marcar `truth_type` no registry: `pdf_declared`, `calculated_audit_only`, `supporting_evidence` ou `missing_or_unverified`.
- `integrity_orchestrator.py` passou a rodar coverage, conflict resolver e status extraction-vs-document no fluxo real.
- `final_quality_metrics.py` passou a expor métricas de cobertura e dos novos status.
- `lovable_consumption_policy` agora explica como o Lovable deve tratar inconsistência documental sem recalcular valores públicos.

## Política consolidada
- Campo público = token físico declarado no PDF.
- Cálculo = auditoria, validação e ranking de candidatos.
- Se todos os campos visíveis foram extraídos mas a matemática não fecha, o problema é do documento, não do parser.
- Se campo crítico não foi encontrado, é falha de extração ou `needs_review`.
