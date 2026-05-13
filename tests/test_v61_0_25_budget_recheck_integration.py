from __future__ import annotations

import fitz

from app.browser.recovery_agent import apply_recovery_patches
from app.browser.service import merge_stages_browser
from app.normalizer.field_recovery import recover_fields
from app.parser.budget import _sanitize_orcamento_especificacao
from app.parser.compositions import _sanitize_description


def _make_pdf(lines: list[tuple[float, float, str]]) -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=620, height=220)
    for x, y, text in lines:
        page.insert_text((x, y), text, fontsize=9)
    data = doc.tobytes()
    doc.close()
    return data


def test_sanitizers_do_not_delete_engineer_service_descriptions():
    text = "ENGENHEIRO CIVIL DE OBRA JUNIOR COM ENCARGOS COMPLEMENTARES"
    assert _sanitize_orcamento_especificacao(text, [], []) == text
    assert _sanitize_description(text) == text


def test_budget_field_recovery_recovers_downward_broken_specification():
    pdf = _make_pdf([
        (45, 50, "1.1 90777 SINAPI"),
        (165, 50, "ENGENHEIRO CIVIL DE OBRA JUNIOR COM"),
        (165, 62, "ENCARGOS COMPLEMENTARES"),
    ])
    payload = {
        "page_map": {"1": 1},
        "targets": [{
            "target_id": "orcamento_sintetico.itens_raiz.0::especificacao",
            "path": ["orcamento_sintetico", "itens_raiz", 0, "especificacao"],
            "field": "especificacao",
            "family": "budget",
            "table_family": "budget",
            "current_value": "ENGENHEIRO CIVIL DE OBRA JUNIOR COM",
            "codigo": "90777",
            "banco": "SINAPI",
            "page": 1,
            "issue": "possible_truncated_budget_description",
            "item": "1.1",
        }],
        "column_maps": {
            "budget": {
                "columns": [
                    {"canonical": "item", "x0": 35, "x1": 44},
                    {"canonical": "codigo", "x0": 45, "x1": 90},
                    {"canonical": "fonte", "x0": 95, "x1": 150},
                    {"canonical": "descricao", "x0": 160, "x1": 455},
                    {"canonical": "und", "x0": 460, "x1": 495},
                ]
            }
        },
        "apply_confidence_min": 0.85,
    }
    result = recover_fields(pdf, payload)
    assert result["summary"]["patches"] == 1, result
    patch = result["patches"][0]
    assert patch["field"] == "especificacao"
    assert patch["evidence"]["target_family"] == "budget"
    assert patch["value"] == "ENGENHEIRO CIVIL DE OBRA JUNIOR COM ENCARGOS COMPLEMENTARES"


def test_budget_recovery_patch_commits_to_orcamento_sintetico():
    final = {
        "orcamento_sintetico": {
            "itens_raiz": [
                {"tipo": "item", "item": "1.1", "codigo": "90777", "fonte": "SINAPI", "especificacao": "ENGENHEIRO CIVIL DE OBRA JUNIOR COM"}
            ]
        },
        "composicoes": {"sinapi_like": {"principais": {}, "auxiliares_globais": {}}, "sicro": {"principais": {}, "auxiliares_globais": {}}},
    }
    recovery = {"patches": [{
        "target_id": "orcamento_sintetico.itens_raiz.0::especificacao",
        "path": ["orcamento_sintetico", "itens_raiz", 0, "especificacao"],
        "field": "especificacao",
        "family": "budget",
        "value": "ENGENHEIRO CIVIL DE OBRA JUNIOR COM ENCARGOS COMPLEMENTARES",
        "confidence": 0.92,
        "codigo": "90777",
        "banco": "SINAPI",
        "item": "1.1",
        "target_issue": "possible_truncated_budget_description",
        "evidence": {"candidate_strategy": "target_plus_downward_fragments"},
    }]}
    applied = apply_recovery_patches(final, recovery, min_confidence=0.85)
    assert len(applied["commits"]) == 1, applied
    assert applied["final_result"]["orcamento_sintetico"]["itens_raiz"][0]["especificacao"] == "ENGENHEIRO CIVIL DE OBRA JUNIOR COM ENCARGOS COMPLEMENTARES"


def test_noop_recovery_patch_is_rejected():
    final = {"composicoes": {"sinapi_like": {"principais": {"90777|SINAPI": {"principal": {"codigo": "90777", "banco": "SINAPI", "descricao": "ENGENHEIRO CIVIL"}}}}}}
    recovery = {"patches": [{
        "path": ["composicoes", "sinapi_like", "principais", "90777|SINAPI", "principal", "descricao"],
        "field": "descricao",
        "value": "ENGENHEIRO CIVIL",
        "confidence": 0.99,
        "codigo": "90777",
        "banco": "SINAPI",
        "target_issue": "possible_truncated_description",
    }]}
    applied = apply_recovery_patches(final, recovery, min_confidence=0.85)
    assert len(applied["commits"]) == 0
    assert applied["rejected"][0]["reason"] == "no_op_same_value"


def test_merge_preserves_document_learning_profile_in_final_meta_performance():
    budget_stage = {
        "orcamento_sintetico": {"itens_raiz": [], "itens_plano": []},
        "item_refs": [],
        "avisos": [],
        "erros": [],
        "divergencias": [],
        "ocorrencias": [],
        "_stage_meta": {"duration_ms": 1.0, "performance": {"pages": 1}},
    }
    comp_stage = {
        "composicoes": {"principais": {}, "auxiliares_globais": {}, "aliases_auxiliares": {}},
        "avisos": [],
        "erros": [],
        "ocorrencias": [],
        "_stage_meta": {"duration_ms": 1.0, "performance": {"pages": 1}},
    }
    options = {"orcamento_inicio": 1, "orcamento_fim": 1, "composicoes_inicio": 2, "composicoes_fim": 2, "base_id": "misto"}
    final = merge_stages_browser(budget_stage, comp_stage, options)
    perf = final.get("meta", {}).get("performance", {})
    assert "document_learning_profile" in perf
    assert "enrichment_report" in perf
    assert "profile_aware_recheck" in perf
