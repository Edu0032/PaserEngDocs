from __future__ import annotations

from app.parser.semantic_consistency import (
    apply_semantic_consistency_pass,
    build_component_mismatch_diagnostics,
    build_entity_confidence_report,
)
from app.parser.output_documents_organizer import organize_lovable_output_documents


def _composition_fixture(delta: bool = False):
    total = "9,00" if delta else "10,00"
    return {
        "orcamento_sintetico": {
            "itens_raiz": [
                {"tipo": "item", "item": "1.1", "codigo": "ABC 01", "fonte": "PRÓPRIO", "especificacao": "SERVIÇO", "und": "UN", "quant": "2,00", "custo_unitario_com_bdi": "5,00", "custo_parcial": "10,00", "custo_unitario_sem_bdi": "10,00"}
            ]
        },
        "composicoes": {
            "principais": {
                "ABC01|PROPRIO": {
                    "item": "1.1",
                    "principal": {"codigo": "ABC 01", "banco": "PRÓPRIO", "descricao": "SERVIÇO =>", "und": "UN", "quant": "1", "valor_unit": total, "total": total},
                    "insumos": [
                        {"codigo": "MAT1", "banco": "PRÓPRIO", "descricao": "MATERIAL", "und": "UN", "quant": "1", "valor_unit": "4,00", "total": "4,00"},
                        {"codigo": "MAT2", "banco": "PRÓPRIO", "descricao": "MATERIAL 2", "und": "UN", "quant": "1", "valor_unit": "6,00", "total": "6,00"},
                    ],
                }
            },
            "auxiliares_globais": {},
            "sinapi_like": {"principais": {}, "auxiliares_globais": {}},
            "sicro": {"principais": {}, "auxiliares_globais": {}},
        },
        "documento_correcao": {"resumo": {}, "targeted_recovery": {"attempted": True, "target_count": 1, "patches": [], "unresolved": [
            {"target_id": "x", "field": "descricao", "issue": "polluted:pollution_term:=>", "reason": "target_line_not_found", "current_value": "SERVIÇO =>", "candidate_value": ""}
        ]}},
    }


def test_v61_0_53_semantic_pass_removes_trailing_arrow_and_audits():
    data, report = apply_semantic_consistency_pass(_composition_fixture())
    assert report["summary"]["description_repairs"] == 1
    assert data["composicoes"]["principais"]["ABC01|PROPRIO"]["principal"]["descricao"] == "SERVIÇO"
    assert data["documento_correcao"]["semantic_consistency_pass"]["summary"]["description_repairs"] == 1


def test_v61_0_53_component_mismatch_diagnostic_finds_human_or_extraction_case():
    diag = build_component_mismatch_diagnostics(_composition_fixture(delta=True))
    assert diag["summary"]["mismatch"] == 1
    item = diag["diagnostics"][0]
    assert item["status"] == "math_mismatch_possible_extraction_or_pdf_human_error"
    assert "erro humano" in item["conclusion"]


def test_v61_0_53_organizer_reduces_targeted_recovery_noise_and_adds_confidence():
    data = _composition_fixture()
    organize_lovable_output_documents(data, {"rows": [], "summary": {}})
    human = data["documento_correcao"]["auditoria_humana"]
    assert human["summary"]["targeted_recovery_diagnostic_ignored"] == 1
    assert human["summary"]["review_queue_count"] == 0
    conf = data["analise_orcamentaria"]["entity_confidence_report"]
    assert conf["summary"]["high"] >= 1
    assert data["documento_correcao"]["painel_lovable"]["status"] == "ok"


def test_v61_0_53_entity_confidence_marks_mismatch_for_review():
    conf = build_entity_confidence_report(_composition_fixture(delta=True))
    composition_entries = [e for e in conf["entities"] if e["entity_type"] == "composition_principal"]
    assert composition_entries
    assert composition_entries[0]["confidence_level"] == "review"
    assert composition_entries[0]["component_diagnostic"]["status"].startswith("math_mismatch")
