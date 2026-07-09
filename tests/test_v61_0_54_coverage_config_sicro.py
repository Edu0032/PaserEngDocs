from app.config.loader import merge_base_config_layers
from app.parser.extraction_coverage import build_extraction_coverage_report, build_base_config_layering_report
from app.parser.output_documents_organizer import organize_lovable_output_documents


def test_base_config_layering_simple_admin_and_user_overlays():
    embedded = {"knowledge_base": {"units": ["M"]}, "quality_gate": {"enabled": True}}
    admin = {"knowledge_base": {"units": ["M", "M3XKM"]}, "quality_gate": {"enabled": False}}
    user = {"custom_bank_profiles": {"profiles": {"x": {"templates": [{"columns": [{"canonical": "codigo"}]}]}}}}
    merged = merge_base_config_layers(admin, user, embedded_config=embedded)
    assert merged["knowledge_base"]["units"] == ["M", "M3XKM"]
    assert merged["quality_gate"]["enabled"] is False
    assert "x" in merged["custom_bank_profiles"]["profiles"]
    assert merged["metadata"]["base_config_layering"]["admin_base_config_merged"] is True
    assert merged["metadata"]["base_config_layering"]["user_base_config_merged"] is True
    assert merged["metadata"]["base_config_layering"]["zip_mutated"] is False


def _sample_final():
    return {
        "orcamento_sintetico": {"itens_raiz": [
            {"tipo": "item", "item": "1.1", "codigo": "74209/001", "fonte": "SINAPI", "especificacao": "PLACA", "und": "m²", "quant": "6,00", "custo_unitario_com_bdi": "634,16", "custo_parcial": "3.804,96"},
            {"tipo": "item", "item": "3.1.5", "codigo": "5503041", "fonte": "SICRO", "especificacao": "Compactação", "und": "m³", "quant": "1,00", "custo_unitario_com_bdi": "7,35", "custo_parcial": "7,35"},
        ]},
        "composicoes": {
            "sinapi_like": {"principais": {"74209001|SINAPI": {"item": "1.1", "principal": {"codigo": "74209/001", "banco": "SINAPI", "descricao": "PLACA", "und": "m²", "quant": "1", "valor_unit": "521,39", "total": "521,39"}}}, "auxiliares_globais": {}},
            "sicro": {"principais": {"5503041|SICRO": {"item": "3.1.5", "principal": {"codigo": "5503041", "banco": "SICRO", "descricao": "Compactação"}}, "2003373|SICRO": {"item": "9.9", "principal": {"codigo": "2003373", "banco": "SICRO", "descricao": "Meio fio"}}}, "auxiliares_globais": {"9999999|SICRO": {"principal": {"codigo": "9999999", "banco": "SICRO"}}}},
        },
        "meta": {"performance": {"physical_evidence_index": {"status": "ok", "keys": {
            "74209001|SINAPI": {"occurrences": [{"page": 2, "document_section": "orcamento_sintetico", "line_text": "74209/001 SINAPI PLACA", "fields_detected": {"und": "m²"}}, {"page": 9, "document_section": "composicoes_analiticas", "line_text": "Composição 74209/001 SINAPI", "fields_detected": {"total": "521,39"}}]},
            "5503041|SICRO": {"occurrences": [{"page": 2, "document_section": "orcamento_sintetico", "line_text": "5503041 SICRO Compactação"}]},
            "ORFAO|SINAPI": {"occurrences": [{"page": 10, "document_section": "composicoes_analiticas", "line_text": "Insumo ORFAO SINAPI"}]},
        }}}},
    }


def test_extraction_coverage_maps_budget_composition_and_sicro():
    report = build_extraction_coverage_report(_sample_final())
    assert report["summary"]["budget_json_leaf_items"] == 2
    assert report["budget"]["mapped_physical_occurrences"] >= 2
    assert report["sinapi_like_compositions"]["physical_candidate_occurrences"] == 2
    assert report["sicro"]["budget_sicro_items"] == 1
    assert report["sicro"]["sicro_main_with_item"] == 2
    assert report["sicro"]["main_with_item_not_referenced_by_budget"] == 1
    assert any(u["normalized_key"] == "ORFAO|SINAPI" for u in report["unmapped_physical_candidates"])


def test_output_documents_include_coverage_and_base_config_layering():
    final = _sample_final()
    organize_lovable_output_documents(final, {"summary": {}, "rows": []})
    assert "extraction_coverage_report" in final["analise_orcamentaria"]
    assert "base_config_layering" in final["analise_orcamentaria"]
    assert "extraction_coverage_report" in final["documento_evidencias"]
    assert final["analise_orcamentaria"]["outputs_contract"]["summary"]["coverage_summary"]
    assert "coverage" in final["documento_correcao"]["manual_consumo_lovable_resumo"]


def test_base_config_layering_report_explains_simple_flow():
    report = build_base_config_layering_report({}, {"admin_base_config_overlay": {"x": 1}, "user_base_config_overlay": {"y": 2}})
    assert report["practical_model"]["admin_can_send_full_copy_or_patch"] is True
    assert report["current_run_metadata"]["admin_overlay_present"] is True
    assert report["current_run_metadata"]["user_overlay_present"] is True
