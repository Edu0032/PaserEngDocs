from __future__ import annotations

import json
from pathlib import Path

from app.pipeline.stage_registry import build_lovable_contract_reference, build_stage_reference
from app.parser.output_documents_organizer import organize_lovable_output_documents
from app.parser.output_contract_validator import validate_output_contract
from app.parser.output_schema_stability import normalize_output_schema_documents

ROOT = Path(__file__).resolve().parents[1]


def _sample_final():
    return {
        "orcamento_sintetico": {"itens_raiz": []},
        "composicoes": {"sinapi_like": {"principais": {}, "auxiliares_globais": {}}, "sicro": {"principais": {}, "auxiliares_globais": {}}},
        "auditoria_final": {"quality_gate": {"ok": True}},
        "documento_correcao": {"resumo": {}, "warnings": []},
    }


def test_v56_docs_lovable_contracts_are_present_and_explain_core_topics():
    docs_dir = ROOT / "docs" / "lovable_contracts"
    expected = [
        "00_README_INTEGRACAO_LOVABLE.md",
        "01_INPUT_CONTRACT.md",
        "02_OUTPUTS_CONTRACT.md",
        "03_BASE_CONFIG_CONTRACT.md",
        "05_PIPELINE_STAGES.md",
        "08_COMPOSITIONS_AND_SICRO_ASSOCIATION.md",
        "AUTO_STAGE_REFERENCE.md",
    ]
    for name in expected:
        assert (docs_dir / name).exists(), name
    sicro_doc = (docs_dir / "08_COMPOSITIONS_AND_SICRO_ASSOCIATION.md").read_text(encoding="utf-8")
    assert "seção D" in sicro_doc
    assert "auxiliares" in sicro_doc
    assert "SICRO com item" in sicro_doc


def test_v56_stage_registry_is_exposed_in_analytics_outputs():
    final = _sample_final()
    organize_lovable_output_documents(final, {"summary": {}, "rows": []})
    normalize_output_schema_documents(final)
    ref = final["analise_orcamentaria"]["lovable_contract_reference"]
    assert ref["schema_version"] == "lovable_contracts.v1"
    assert ref["stage_reference"]["stage_count"] >= 10
    assert any(s["stage_id"] == "sicro_bridge" for s in ref["stage_reference"]["stages"])
    assert "section_d" in ref["sicro_association"]


def test_v56_json_schemas_and_examples_exist_and_are_valid_json():
    paths = [
        ROOT / "schemas" / "input" / "document_payload.schema.json",
        ROOT / "schemas" / "input" / "runtime_options.schema.json",
        ROOT / "schemas" / "input" / "base_config_overlay.schema.json",
        ROOT / "schemas" / "output" / "final_result.schema.json",
        ROOT / "examples" / "lovable" / "minimal_payload.json",
        ROOT / "examples" / "lovable" / "runtime_options.local.json",
    ]
    for path in paths:
        assert path.exists(), path
        json.loads(path.read_text(encoding="utf-8"))


def test_v56_contract_validator_rejects_runtime_config_inside_document_payload():
    final = _sample_final()
    organize_lovable_output_documents(final, {"summary": {}, "rows": []})
    bad_payload = {"document": {"filename": "x.pdf"}, "docling_timeout_ms": 240000}
    report = validate_output_contract(final, bad_payload)
    assert report["ok"] is False
    assert report["payload_boundary"]["forbidden_runtime_or_admin_keys"]


def test_v56_stage_reference_is_ordered_and_has_blocking_flags():
    ref = build_stage_reference()
    orders = [s["order"] for s in ref["stages"]]
    assert orders == sorted(orders)
    assert "input_prepare" in ref["blocking_stages"]
    contract = build_lovable_contract_reference()
    assert contract["base_config_model"]["formula"].startswith("effective_base_config")
