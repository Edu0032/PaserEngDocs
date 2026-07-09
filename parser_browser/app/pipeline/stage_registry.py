from __future__ import annotations

"""Registry of the Lovable/Python parser pipeline stages.

The registry is intentionally lightweight and data-only so docs, tests, the
HTML demo and output analytics can all speak about the same stages without
duplicating text in multiple places.
"""

from typing import Any, Dict, List

VERSION = "v61.0.75-correction-output-contract-and-review-index"
SCHEMA_VERSION = "lovable_contracts.v1"

STAGE_REGISTRY: List[Dict[str, Any]] = [
    {
        "order": 1,
        "stage_id": "input_prepare",
        "name": "Preparar input Lovable",
        "input_keys": ["document_payload", "runtime_options", "admin_config_overlay", "user_config_overlay", "pdf_file"],
        "output_keys": ["effective_runtime", "validated_document_payload"],
        "blocking": True,
        "output_document_section": "analise_orcamentaria.lovable_contract_reference.inputs",
        "purpose": "separar dados do documento, opções runtime e overlays de configuração antes da extração",
    },
    {
        "order": 2,
        "stage_id": "base_config_layering",
        "name": "Carregar base_config default + overlays",
        "input_keys": ["db/base_config.json", "db/base_config.d", "admin_config_overlay", "user_config_overlay"],
        "output_keys": ["effective_base_config", "base_config_layering_report"],
        "blocking": True,
        "output_document_section": "analise_orcamentaria.base_config_layering",
        "purpose": "aplicar em memória o modelo simples default do ZIP + overlay admin + overlay usuário/projeto",
    },
    {
        "order": 3,
        "stage_id": "seed_pdf_and_docling",
        "name": "Gerar seed PDF e chamar Docling",
        "input_keys": ["pdf_file", "docling_seed_pages", "runtime_options.docling"],
        "output_keys": ["docling_response", "seed_pdf_page_map"],
        "blocking": True,
        "output_document_section": "documento_evidencias.docling_usage",
        "purpose": "usar mini-PDF seed para obter estrutura de tabela sem enviar o PDF completo para a API Docling",
    },
    {
        "order": 4,
        "stage_id": "local_normalizer",
        "name": "Normalizer local PyMuPDF",
        "input_keys": ["docling_response", "seed_pdf", "document_payload.tables"],
        "output_keys": ["normalized_table_structure", "column_maps"],
        "blocking": False,
        "output_document_section": "documento_evidencias.normalizer",
        "purpose": "refinar geometria, colunas e mapeamentos usando texto/posição no Pyodide",
    },
    {
        "order": 5,
        "stage_id": "budget_parse",
        "name": "Extrair orçamento sintético",
        "input_keys": ["pdf_file", "ranges.budget", "column_maps.budget"],
        "output_keys": ["orcamento_sintetico", "budget_preview"],
        "blocking": True,
        "output_document_section": "final_result.orcamento_sintetico",
        "purpose": "extrair metas, submetas, itens folha e campos financeiros do orçamento sintético",
    },
    {
        "order": 6,
        "stage_id": "composition_parse",
        "name": "Extrair composições SINAPI-like e próprias",
        "input_keys": ["pdf_file", "ranges.compositions", "column_maps.composition"],
        "output_keys": ["composicoes.sinapi_like"],
        "blocking": True,
        "output_document_section": "final_result.composicoes.sinapi_like",
        "purpose": "extrair principais, auxiliares internas, insumos e auxiliares globais com campos matemáticos",
    },
    {
        "order": 7,
        "stage_id": "sicro_bridge",
        "name": "Integrar composições SICRO",
        "input_keys": ["pdf_file", "ranges.compositions", "sicro_only output"],
        "output_keys": ["composicoes.sicro"],
        "blocking": False,
        "output_document_section": "final_result.composicoes.sicro",
        "purpose": "integrar SICRO respeitando a estrutura própria: com item = principal; sem item = auxiliar global; seção D referencia auxiliares que impactam a principal",
    },
    {
        "order": 8,
        "stage_id": "evidence_indexes",
        "name": "Construir índices de evidência",
        "input_keys": ["final_result parcial", "pdf_file"],
        "output_keys": ["document_evidence_index", "physical_evidence_index"],
        "blocking": False,
        "output_document_section": "documento_evidencias.evidence_indexes",
        "purpose": "indexar evidências extraídas e físicas/brutas por código+banco e por contexto",
    },
    {
        "order": 9,
        "stage_id": "repair_closure",
        "name": "Reparar, fechar e validar linhas",
        "input_keys": ["final_result parcial", "evidence_indexes", "math expectations"],
        "output_keys": ["repairs", "closure_status", "quality_gate"],
        "blocking": False,
        "output_document_section": "documento_correcao.painel_lovable",
        "purpose": "aplicar cascata local, consenso, soma de componentes, validação matemática e fechamento realista",
    },
    {
        "order": 10,
        "stage_id": "coverage_quality",
        "name": "Cobertura, confiança e qualidade",
        "input_keys": ["final_result", "physical_evidence_index", "closure_report"],
        "output_keys": ["accuracy_report", "extraction_coverage_report", "entity_confidence_report"],
        "blocking": False,
        "output_document_section": "analise_orcamentaria",
        "purpose": "medir cobertura, taxa de matemática OK, confiança por entidade e possíveis lacunas",
    },
    {
        "order": 11,
        "stage_id": "output_contract",
        "name": "Organizar outputs e validar contrato",
        "input_keys": ["final_result", "documentos auxiliares"],
        "output_keys": ["final_result", "documento_correcao", "documento_evidencias", "documento_enriquecimento", "analise_orcamentaria"],
        "blocking": True,
        "output_document_section": "analise_orcamentaria.output_contract_validation",
        "purpose": "separar resultado limpo, correção, evidências, enriquecimento e analytics em contrato estável para o Lovable",
    },
]

INPUT_CONTRACT = {
    "document_payload": "somente informações do documento/PDF atual: arquivo, páginas, ranges, headers observados, samples e hints de tabela",
    "runtime_options": "opções da execução atual: endpoint Docling, cache, timeout, modo local/remoto; não devem ser salvas dentro do payload documental",
    "admin_config_overlay": "configuração persistente da plataforma/admin; pode ser cópia completa ou overlay parcial sobre o base_config do ZIP",
    "user_config_overlay": "configuração persistente do usuário/projeto; banco personalizado, aliases locais, unidades aceitas pelo projeto",
}

OUTPUT_CONTRACT = {
    "final_result": "resultado limpo para popular o sistema Lovable",
    "documento_correcao": "pendências, revisões, prováveis erros humanos/documentais e ações recomendadas",
    "documento_evidencias": "provas técnicas usadas para confirmar, corrigir ou rejeitar valores",
    "documento_enriquecimento": "sugestões de unidades/aliases/templates para admin/base_config; nunca autoaplica",
    "analise_orcamentaria": "métricas, cobertura, confiança por entidade, stage reference, contrato e resumo operacional",
}


def build_stage_reference() -> Dict[str, Any]:
    return {
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "document_type": "pipeline_stage_reference",
        "stages": STAGE_REGISTRY,
        "stage_count": len(STAGE_REGISTRY),
        "blocking_stages": [s["stage_id"] for s in STAGE_REGISTRY if s.get("blocking")],
    }


def build_lovable_contract_reference() -> Dict[str, Any]:
    return {
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "document_type": "lovable_contract_reference",
        "input_contract": INPUT_CONTRACT,
        "output_contract": OUTPUT_CONTRACT,
        "base_config_model": {
            "formula": "effective_base_config = zip_default_base_config + admin_config_overlay + user_config_overlay",
            "zip_default": "somente leitura; enviado no bundle; não é modificado em runtime",
            "admin_overlay": "persistido fora do ZIP pelo Lovable/plataforma; sobrepõe ou estende o default",
            "user_overlay": "persistido fora do ZIP por usuário/projeto; sobrepõe ou estende onde permitido",
            "merge_time": "início de cada execução, em memória",
        },
        "sicro_association": {
            "same_general_rule": "segue o mesmo princípio de associação por código+banco e por item, mas com estrutura própria de seções",
            "principal_rule": "SICRO com item próprio é principal; SICRO sem item próprio é auxiliar_global",
            "section_d": "a seção D referencia atividades auxiliares; alterações no custo dessas auxiliares devem impactar a composição principal que as referencia",
            "lovable_review": "SICRO com item mas sem referência no orçamento sintético é revisão para Lovable, não reclassificação automática pelo parser",
        },
        "stage_reference": build_stage_reference(),
    }
