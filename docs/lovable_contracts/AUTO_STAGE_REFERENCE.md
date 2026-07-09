# AUTO — Stage reference

Gerado a partir de `parser_browser/app/pipeline/stage_registry.py`.

## 1. Preparar input Lovable (`input_prepare`)

**Bloqueante:** `True`

**Entrada:** `document_payload, runtime_options, admin_config_overlay, user_config_overlay, pdf_file`

**Saída:** `effective_runtime, validated_document_payload`

**Onde aparece:** `analise_orcamentaria.lovable_contract_reference.inputs`

separar dados do documento, opções runtime e overlays de configuração antes da extração

## 2. Carregar base_config default + overlays (`base_config_layering`)

**Bloqueante:** `True`

**Entrada:** `db/base_config.json, db/base_config.d, admin_config_overlay, user_config_overlay`

**Saída:** `effective_base_config, base_config_layering_report`

**Onde aparece:** `analise_orcamentaria.base_config_layering`

aplicar em memória o modelo simples default do ZIP + overlay admin + overlay usuário/projeto

## 3. Gerar seed PDF e chamar Docling (`seed_pdf_and_docling`)

**Bloqueante:** `True`

**Entrada:** `pdf_file, docling_seed_pages, runtime_options.docling`

**Saída:** `docling_response, seed_pdf_page_map`

**Onde aparece:** `documento_evidencias.docling_usage`

usar mini-PDF seed para obter estrutura de tabela sem enviar o PDF completo para a API Docling

## 4. Normalizer local PyMuPDF (`local_normalizer`)

**Bloqueante:** `False`

**Entrada:** `docling_response, seed_pdf, document_payload.tables`

**Saída:** `normalized_table_structure, column_maps`

**Onde aparece:** `documento_evidencias.normalizer`

refinar geometria, colunas e mapeamentos usando texto/posição no Pyodide

## 5. Extrair orçamento sintético (`budget_parse`)

**Bloqueante:** `True`

**Entrada:** `pdf_file, ranges.budget, column_maps.budget`

**Saída:** `orcamento_sintetico, budget_preview`

**Onde aparece:** `final_result.orcamento_sintetico`

extrair metas, submetas, itens folha e campos financeiros do orçamento sintético

## 6. Extrair composições SINAPI-like e próprias (`composition_parse`)

**Bloqueante:** `True`

**Entrada:** `pdf_file, ranges.compositions, column_maps.composition`

**Saída:** `composicoes.sinapi_like`

**Onde aparece:** `final_result.composicoes.sinapi_like`

extrair principais, auxiliares internas, insumos e auxiliares globais com campos matemáticos

## 7. Integrar composições SICRO (`sicro_bridge`)

**Bloqueante:** `False`

**Entrada:** `pdf_file, ranges.compositions, sicro_only output`

**Saída:** `composicoes.sicro`

**Onde aparece:** `final_result.composicoes.sicro`

integrar SICRO respeitando a estrutura própria: com item = principal; sem item = auxiliar global; seção D referencia auxiliares que impactam a principal

## 8. Construir índices de evidência (`evidence_indexes`)

**Bloqueante:** `False`

**Entrada:** `final_result parcial, pdf_file`

**Saída:** `document_evidence_index, physical_evidence_index`

**Onde aparece:** `documento_evidencias.evidence_indexes`

indexar evidências extraídas e físicas/brutas por código+banco e por contexto

## 9. Reparar, fechar e validar linhas (`repair_closure`)

**Bloqueante:** `False`

**Entrada:** `final_result parcial, evidence_indexes, math expectations`

**Saída:** `repairs, closure_status, quality_gate`

**Onde aparece:** `documento_correcao.painel_lovable`

aplicar cascata local, consenso, soma de componentes, validação matemática e fechamento realista

## 10. Cobertura, confiança e qualidade (`coverage_quality`)

**Bloqueante:** `False`

**Entrada:** `final_result, physical_evidence_index, closure_report`

**Saída:** `accuracy_report, extraction_coverage_report, entity_confidence_report`

**Onde aparece:** `analise_orcamentaria`

medir cobertura, taxa de matemática OK, confiança por entidade e possíveis lacunas

## 11. Organizar outputs e validar contrato (`output_contract`)

**Bloqueante:** `True`

**Entrada:** `final_result, documentos auxiliares`

**Saída:** `final_result, documento_correcao, documento_evidencias, documento_enriquecimento, analise_orcamentaria`

**Onde aparece:** `analise_orcamentaria.output_contract_validation`

separar resultado limpo, correção, evidências, enriquecimento e analytics em contrato estável para o Lovable
