from __future__ import annotations

from app.parser.full_pdf_occurrence_consensus import build_occurrence_consensus
from app.parser.line_certainty_closure import run_line_certainty_closure_engine
from app.parser.field_evidence_grade import classify_evidence_grade, is_public_field_supported
from app.parser.extracted_relation_graph import relation_allows_field


def _base_final_with_missing_total():
    return {
        "orcamento_sintetico": {"itens_raiz": []},
        "composicoes": {
            "sinapi_like": {
                "principais": {
                    "89446|SINAPI": {
                        "principal": {"codigo": "89446", "banco": "SINAPI", "descricao": "TUBO PVC", "und": "m", "quant": "1,0000000", "valor_unit": "14,27", "total": ""},
                        "composicoes_auxiliares": [],
                        "insumos": [],
                    }
                },
                "auxiliares_globais": {},
            },
            "sicro": {"principais": {}, "auxiliares_globais": {}},
        },
        "documento_correcao": {"resumo": {}},
        "validacao": {"ocorrencias": []},
        "meta": {"performance": {}},
    }


def test_v40_math_only_expectation_does_not_write_public_field():
    out, report = run_line_certainty_closure_engine(_base_final_with_missing_total(), apply=True)
    principal = out["composicoes"]["sinapi_like"]["principais"]["89446|SINAPI"]["principal"]
    assert principal["total"] == ""
    expectation = principal["_calc"]["math_only_expectations"][0]
    assert expectation["expected_value"] == "14,27"
    assert expectation["evidence_grade"] == "math_only_expected"
    assert expectation["public_write_allowed"] is False
    row = [r for r in report["rows"] if r["codigo"] == "89446"][0]
    assert row["field_evidence_grades"]["total"]["evidence_grade"] == "math_only_expected"


def test_v40_relation_contract_forbids_contextual_quantity_copying():
    assert relation_allows_field("budget_to_main_composition", "und") is True
    assert relation_allows_field("budget_to_main_composition", "quant") is False
    assert relation_allows_field("global_auxiliary_to_contextual_auxiliary", "valor_unit") is True
    assert relation_allows_field("global_auxiliary_to_contextual_auxiliary", "quant") is False


def test_v40_full_pdf_occurrence_consensus_requires_repeatable_or_strong_physical_evidence():
    weak = build_occurrence_consensus([
        {"row_id": "r1", "field": "und", "value": "m", "page": 3, "confidence": 0.83, "source": "full_pdf_code_bank_occurrence_sweep"}
    ])
    assert weak["accepted_count"] == 0
    strong = build_occurrence_consensus([
        {"row_id": "r1", "field": "und", "value": "m", "page": 3, "confidence": 0.84, "source": "full_pdf_code_bank_occurrence_sweep"},
        {"row_id": "r1", "field": "und", "value": "m", "page": 29, "confidence": 0.86, "source": "full_pdf_code_bank_occurrence_sweep"},
    ])
    assert strong["accepted_count"] == 1
    assert strong["accepted"][0]["source"] == "full_pdf_occurrence_consensus"


def test_v40_evidence_grades_distinguish_math_only_from_physical_pdf():
    assert classify_evidence_grade("14,27", evidence={"source": "math_only_expected"}) == "math_only_expected"
    assert is_public_field_supported("math_only_expected") is False
    grade = classify_evidence_grade("14,27", evidence={"source": "deep_area_sweep"}, math_confirmed=True)
    assert grade == "physical_pdf_evidence_math_confirmed"
    assert is_public_field_supported(grade) is True


def test_v40_final_reconciliation_and_correction_doc_are_present():
    out, report = run_line_certainty_closure_engine(_base_final_with_missing_total(), apply=True)
    doc = out["documento_correcao"]
    assert "final_reconciliation_pass" in doc
    assert "line_certainty_closure" in doc
    assert report["final_reconciliation_pass"]["unresolved_rows"] >= 1
    targets = doc["full_pdf_code_bank_occurrence_sweep"]["targets"]
    assert targets and targets[0]["consensus_required"] is True
