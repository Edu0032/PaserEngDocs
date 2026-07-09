# v61.0.44 — Budget Reconstruction Graph

## Objetivo

Tratar orçamento sintético, composições principais, auxiliares contextuais, auxiliares globais, insumos e evidências físicas como uma cadeia de entidades relacionadas.

## Principais melhorias

- Novo `budget_reconstruction_graph.py` para montar cadeias orçamento → composição principal → linhas internas → auxiliares globais.
- Novo `composition_cost_reconciliation.py` para validar soma dos componentes de composições SINAPI-like.
- Novo `budget_hierarchy_reconciliation.py` para validar metas/submetas pela soma dos filhos.
- Novo `entity_chain_conflict_resolver.py` para registrar conflitos por cadeia.
- Novo `final_json_chain_organizer.py` para expor `analise_orcamentaria.budget_reconstruction` no JSON final.
- Auxiliares contextuais sem auxiliar global agora viram warning auditável, não erro fatal.
- SICRO continua autoritativo pelo motor `sicro_only`; não há novo motor A-F redundante.

## Testes

- `136 passed` no parser.
- `4 passed` na API Docling.
- `compileall`, `node --check`, `quality_safety_scan` e integridade dos ZIPs aprovados.
