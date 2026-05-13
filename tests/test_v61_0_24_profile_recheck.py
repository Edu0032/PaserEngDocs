from __future__ import annotations

import fitz

from app.core.schemas import BlocoComposicao, Composicoes, LinhaComposicao, OrcamentoItem, OrcamentoSintetico
from app.normalizer.field_recovery import recover_fields
from app.parser.broken_line_recovery import (
    apply_registry_recheck_to_budget,
    apply_registry_recheck_to_compositions,
    build_description_registry,
    pollution_reason,
)
from app.parser.code_value_classifier import looks_like_code, looks_like_ptbr_decimal_or_money
from app.parser.document_learning_layer import build_document_learning_profile


def test_code_value_classifier_accepts_real_codes_and_rejects_money():
    assert looks_like_code("CADM.01")
    assert looks_like_code("COMP.JCO.3")
    assert looks_like_code("CP - 120")
    assert looks_like_code("74209/001")
    assert looks_like_code("103672-01")
    assert not looks_like_ptbr_decimal_or_money("CADM.01")
    assert looks_like_ptbr_decimal_or_money("1.234,56")
    assert looks_like_ptbr_decimal_or_money("6,05")


def test_pollution_veto_rejects_generic_repeated_labels():
    assert pollution_reason("Insumo Insumo Insumo Insumo") == "repeated_category_label"
    assert pollution_reason("Material Material Material") == "repeated_category_label"
    assert pollution_reason("Custo Total das Atividades => 123,45").startswith("pollution_term")


def test_registry_recheck_repairs_budget_and_composition_descriptions():
    complete = "ENGENHEIRO CIVIL DE OBRA JUNIOR COM ENCARGOS COMPLEMENTARES - HORISTA"
    orc = OrcamentoSintetico(itens_raiz=[
        OrcamentoItem(tipo="item", item="1.1", codigo="90777", fonte="SINAPI", especificacao="ENGENHEIRO CIVIL DE OBRA", und="H"),
    ])
    comp = Composicoes(principais={
        "90777|SINAPI": BlocoComposicao(
            item="1.1",
            principal=LinhaComposicao(codigo="90777", banco="SINAPI", descricao=complete, und="H"),
            composicoes_auxiliares=[LinhaComposicao(codigo="90777", banco="SINAPI", descricao="ENGENHEIRO CIVIL DE OBRA", und="H")],
        )
    })
    registry = build_description_registry(orc, comp)
    assert registry["90777|SINAPI"]["confirmed"] is True
    budget_audit = apply_registry_recheck_to_budget(orc, registry)
    comp_audit = apply_registry_recheck_to_compositions(comp, registry)
    assert budget_audit["metrics"]["repairs_applied"] == 1
    assert comp_audit["metrics"]["repairs_applied"] == 1
    assert orc.itens_raiz[0].especificacao == complete
    assert comp.principais["90777|SINAPI"].composicoes_auxiliares[0].descricao == complete


def test_document_learning_keeps_budget_and_composition_bands_separate():
    context = {
        "structured_tables": {
            "tables": {
                "budget": {"columns": [{"canonical": "descricao", "x0": 80, "x1": 320}]},
                "composition": {"columns": [{"canonical": "descricao", "x0": 170, "x1": 440}]},
            }
        }
    }
    profile = build_document_learning_profile(OrcamentoSintetico(), Composicoes(), context=context, config={})
    assert profile["budget_profile"]["column_bands"]["descricao"]["x0_median"] == 80
    assert profile["sinapi_like_profile"]["column_bands"]["descricao"]["x0_median"] == 170


def _make_pdf(lines: list[tuple[float, float, str]]) -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=600, height=200)
    for x, y, text in lines:
        page.insert_text((x, y), text, fontsize=9)
    data = doc.tobytes()
    doc.close()
    return data


def _payload_for_target(current: str, codigo: str, banco: str, issue: str):
    return {
        "page_map": {"1": 1},
        "targets": [{
            "target_id": "t1",
            "path": ["composicoes", "sinapi_like", "principais", f"{codigo}|SINAPI", "principal", "descricao"],
            "field": "descricao",
            "current_value": current,
            "codigo": codigo,
            "banco": banco,
            "page": 1,
            "issue": issue,
            "collection": "principais",
            "comp_key": f"{codigo}|SINAPI",
            "row_group": "principal",
        }],
        "column_maps": {
            "composition": {
                "columns": [
                    {"canonical": "codigo", "x0": 45, "x1": 90},
                    {"canonical": "banco", "x0": 95, "x1": 150},
                    {"canonical": "descricao", "x0": 165, "x1": 450},
                    {"canonical": "und", "x0": 455, "x1": 490},
                ]
            }
        },
        "apply_confidence_min": 0.85,
    }


def test_field_recovery_recovers_downward_broken_line():
    pdf = _make_pdf([
        (50, 50, "90777 SINAPI"),
        (170, 50, "ENGENHEIRO CIVIL DE OBRA JUNIOR COM"),
        (170, 62, "ENCARGOS COMPLEMENTARES"),
    ])
    payload = _payload_for_target("ENGENHEIRO CIVIL DE OBRA JUNIOR COM", "90777", "SINAPI", "possible_truncated_description")
    result = recover_fields(pdf, payload)
    assert result["summary"]["patches"] == 1, result
    patch = result["patches"][0]
    assert patch["value"] == "ENGENHEIRO CIVIL DE OBRA JUNIOR COM ENCARGOS COMPLEMENTARES"
    assert patch["evidence"]["candidate_strategy"] in {"target_plus_downward_fragments", "upward_target_downward_fragments"}


def test_field_recovery_recovers_upward_broken_line():
    pdf = _make_pdf([
        (170, 50, "ESCAVAÇÃO"),
        (50, 64, "93358 SINAPI"),
        (170, 64, "MANUAL DE VALA COM PROFUNDIDADE MENOR"),
    ])
    current = "MANUAL DE VALA COM PROFUNDIDADE MENOR"
    payload = _payload_for_target(current, "93358", "SINAPI", "possible_broken_line_description")
    result = recover_fields(pdf, payload)
    assert result["summary"]["patches"] == 1, result
    patch = result["patches"][0]
    assert patch["value"] == "ESCAVAÇÃO MANUAL DE VALA COM PROFUNDIDADE MENOR"
    assert patch["evidence"]["candidate_strategy"] in {"upward_fragments_plus_target", "upward_target_downward_fragments"}


def test_recovery_agent_commits_upward_nonprefix_patch_to_nested_sinapi_like():
    from app.browser.recovery_agent import apply_recovery_patches
    final = {
        "composicoes": {
            "sinapi_like": {
                "principais": {
                    "93358|SINAPI": {
                        "principal": {"codigo": "93358", "banco": "SINAPI", "descricao": "MANUAL DE VALA COM PROFUNDIDADE MENOR"}
                    }
                }
            }
        }
    }
    patch = {
        "patches": [{
            "target_id": "t1",
            "path": ["composicoes", "sinapi_like", "principais", "93358|SINAPI", "principal", "descricao"],
            "field": "descricao",
            "value": "ESCAVAÇÃO MANUAL DE VALA COM PROFUNDIDADE MENOR",
            "confidence": 0.91,
            "codigo": "93358",
            "banco": "SINAPI",
            "target_issue": "possible_broken_line_description",
            "evidence": {"candidate_strategy": "upward_fragments_plus_target"},
        }]
    }
    applied = apply_recovery_patches(final, patch, min_confidence=0.85)
    assert len(applied["commits"]) == 1, applied
    assert applied["final_result"]["composicoes"]["sinapi_like"]["principais"]["93358|SINAPI"]["principal"]["descricao"] == "ESCAVAÇÃO MANUAL DE VALA COM PROFUNDIDADE MENOR"
