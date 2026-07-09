from app.parser.output_documents_organizer import organize_lovable_output_documents
from app.parser.output_contract_validator import validate_output_contract
from app.parser.output_schema_stability import build_outputs_package_manifest, normalize_output_schema_documents
from app.parser.extraction_coverage import build_base_config_layering_report


def _sample_final():
    return {
        "orcamento_sintetico": {"itens_raiz": [
            {"tipo": "item", "item": "1.1", "codigo": "74209/001", "fonte": "SINAPI", "especificacao": "PLACA", "und": "m²", "quant": "6,00", "custo_unitario_com_bdi": "634,16", "custo_parcial": "3.804,96"},
        ]},
        "composicoes": {
            "sinapi_like": {"principais": {"74209001|SINAPI": {"item": "1.1", "principal": {"codigo": "74209/001", "banco": "SINAPI", "descricao": "PLACA", "und": "m²", "quant": "1", "valor_unit": "521,39", "total": "521,39"}}}, "auxiliares_globais": {}},
            "sicro": {"principais": {}, "auxiliares_globais": {}},
        },
        "auditoria_final": {"quality_gate": {"ok": True}},
        "meta": {"performance": {"physical_evidence_index": {"status": "ok", "keys": {
            "74209001|SINAPI": {"occurrences": [
                {"page": 2, "document_section": "orcamento_sintetico", "line_text": "74209/001 SINAPI PLACA", "fields_detected": {"und": "m²"}},
                {"page": 9, "document_section": "composicoes_analiticas", "line_text": "Composição 74209/001 SINAPI", "fields_detected": {"total": "521,39"}},
            ]},
        }}}},
        "documento_correcao": {"resumo": {}, "warnings": []},
    }


def test_v56_stable_output_schema_and_manifest():
    final = _sample_final()
    organize_lovable_output_documents(final, {"summary": {}, "rows": []})
    analysis = final["analise_orcamentaria"]
    assert analysis["output_schema_stability"]["schema_version"] == "outputs.v1"
    manifest = analysis["outputs_package_manifest"]
    assert {d["document_type"] for d in manifest["documents"]} >= {"final_result", "correction_document", "evidence_document", "enrichment_document", "analytics_document"}
    assert final["documento_correcao"]["schema_version"] == "outputs.v1"
    assert final["documento_evidencias"]["schema_version"] == "outputs.v1"
    assert final["documento_enriquecimento"]["schema_version"] == "outputs.v1"
    assert final["documento_correcao"]["decisao_uso_lovable"]["status_uso"] == "utilizavel"


def test_v56_contract_validator_accepts_stable_outputs():
    final = _sample_final()
    organize_lovable_output_documents(final, {"summary": {}, "rows": []})
    report = validate_output_contract(final, {"document": {"filename": "x.pdf"}, "ranges": {}})
    assert report["ok"] is True
    assert report["schema_version"] == "outputs.v1"
    assert report["required_sections_present"]["documento_correcao"] is True


def test_v56_enrichment_has_confidence_groups_not_evidence_payload():
    final = _sample_final()
    organize_lovable_output_documents(final, {"summary": {}, "rows": []})
    enrich = final["documento_enriquecimento"]
    assert "sugestoes_por_confianca" in enrich
    assert enrich["approval_policy"]["auto_apply_to_base_config"] is False
    assert "cascade_repairs" not in enrich
    assert "math_field_summary" not in enrich


def test_v56_base_config_layering_report_is_simple_and_has_conflict_policy():
    report = build_base_config_layering_report({}, {"admin_base_config_overlay": {"a": 1}, "user_base_config_overlay": {"b": 2}})
    assert report["practical_model"]["zip_is_not_mutated"] is True
    assert report["conflict_policy"]["conflicts_are_not_fatal"] is True
    assert report["effective_config_model"]["effective_config"]


def test_v56_manifest_can_be_built_after_normalization():
    final = _sample_final()
    final["documento_correcao"] = {}
    final["documento_evidencias"] = {}
    final["documento_enriquecimento"] = {}
    final["analise_orcamentaria"] = {}
    normalize_output_schema_documents(final)
    manifest = build_outputs_package_manifest(final)
    assert all("purpose" in d for d in manifest["documents"])
