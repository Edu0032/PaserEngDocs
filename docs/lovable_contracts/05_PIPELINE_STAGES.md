# 05 — Stages do pipeline

A ordem oficial está em `parser_browser/app/pipeline/stage_registry.py` e também em `analise_orcamentaria.lovable_contract_reference.stage_reference`.

Resumo:

1. Preparar input.
2. Carregar base_config default + overlays.
3. Gerar seed PDF e chamar Docling.
4. Normalizer local PyMuPDF.
5. Extrair orçamento sintético.
6. Extrair composições SINAPI-like/próprias.
7. Integrar SICRO.
8. Construir índices de evidência.
9. Reparar, fechar e validar linhas.
10. Medir cobertura, confiança e qualidade.
11. Organizar outputs e validar contrato.

Cada stage possui `stage_id`, entradas, saídas, se é bloqueante e onde aparece nos outputs.
