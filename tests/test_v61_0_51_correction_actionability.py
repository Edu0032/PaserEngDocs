from __future__ import annotations

from app.parser.line_certainty_closure import run_line_certainty_closure_engine
from app.core.output_compact import refresh_quality_gate_after_repairs
from app.parser.output_documents_organizer import organize_lovable_output_documents


def _minimal_result():
    return {
        "orcamento_sintetico": {
            "descricao": "Teste",
            "total": "405,65",
            "itens_raiz": [
                {
                    "tipo": "meta",
                    "item": "1",
                    "descricao": "HIDROSSANITÁRIO",
                    "filhos": [
                        {
                            "tipo": "item",
                            "item": "1.1",
                            "codigo": "89446",
                            "fonte": "SINAPI",
                            "especificacao": "TUBO, PVC, SOLDÁVEL, DE 25 MM",
                            "und": "M",
                            "quant": "61,00",
                            "custo_unitario_sem_bdi": "5,47",
                            "custo_unitario_com_bdi": "6,65",
                            "custo_parcial": "405,65",
                        }
                    ],
                }
            ],
        },
        "composicoes": {
            "principais": {
                "89446|SINAPI": {
                    "item": "1.1",
                    "principal": {
                        "codigo": "89446",
                        "banco": "SINAPI",
                        "descricao": "TUBO, PVC, SOLDÁVEL, DE 25 MM",
                        "und": "M",
                    },
                    "composicoes_auxiliares": [],
                    "insumos": [
                        {"codigo": "A", "banco": "SINAPI", "descricao": "A", "und": "UN", "quant": "1", "valor_unit": "2,00", "total": "2,00"},
                        {"codigo": "B", "banco": "SINAPI", "descricao": "B", "und": "UN", "quant": "1", "valor_unit": "3,47", "total": "3,47"},
                    ],
                    "detalhes": {"math_status": {"principal_total": 5.47, "component_sum": 5.47, "tolerance": 0.05}},
                }
            },
            "auxiliares_globais": {},
            "sinapi_like": {"principais": {}, "auxiliares_globais": {}},
            "sicro": {"principais": {}, "auxiliares_globais": {}},
        },
        "documento_correcao": {"resumo": {"total_registros_com_erro": 1, "total_quality_gate_issues": 50}},
        "validacao": {"resumo": {"total_erros": 1}, "ocorrencias": []},
    }


def test_v61_0_51_cascade_blocks_recalculated_public_numbers_and_keeps_audit_only():
    out, report = run_line_certainty_closure_engine(_minimal_result(), apply=True, max_rounds=2)
    principal = out["composicoes"]["principais"]["89446|SINAPI"]["principal"]
    assert principal.get("quant") != "61,00"
    assert principal.get("valor_unit") != "5,47"
    assert principal.get("total") != "5,47"
    assert report["composition_principal_cascade_repair"]["summary"]["fields_repaired"] == 0
    assert report["composition_principal_cascade_repair"]["summary"]["blocked"] >= 1
    assert "public_numeric_repair_requires_physical_pdf_evidence" in str(report)
    gate = out["auditoria_final"]["quality_gate"]
    assert not [issue for issue in gate["issues"] if issue.get("code") == "public_float_leaked"]


def test_v61_0_51_refresh_quality_ignores_internal_audit_floats_but_not_public_float():
    result = _minimal_result()
    result["composicoes"]["principais"]["89446|SINAPI"]["principal"]["total"] = 5.47
    gate = refresh_quality_gate_after_repairs(result)
    assert gate["ok"] is False
    assert any(issue["code"] == "public_float_leaked" and issue["field"] == "total" for issue in gate["issues"])
    result["composicoes"]["principais"]["89446|SINAPI"]["principal"]["total"] = "5,47"
    gate = refresh_quality_gate_after_repairs(result)
    assert gate["ok"] is True
    assert gate["issues"] == []


def test_v61_0_51_correction_document_separates_review_from_blocking_error():
    out, report = run_line_certainty_closure_engine(_minimal_result(), apply=True, max_rounds=2)
    # Simulate noisy targeted recovery diagnostics that should not become a blocking error.
    out.setdefault("documento_correcao", {})["targeted_recovery"] = {
        "attempted": True,
        "target_count": 2,
        "unresolved": [
            {"target_id": "a", "field": "descricao", "reason": "no_op_same_value", "current_value": "ABC", "candidate_value": "ABC"},
            {"target_id": "b", "field": "descricao", "issue": "polluted:=>", "reason": "target_line_not_found", "codigo": "X", "banco": "SINAPI", "page": 1, "current_value": "ABC =>"},
        ],
        "patches": [],
    }
    organize_lovable_output_documents(out, report)
    summary = out["documento_correcao"]["auditoria_humana"]["summary"]
    assert summary["targeted_recovery_diagnostic_ignored"] == 1
    assert summary["targeted_recovery_actionable_unresolved"] == 1
    assert out["documento_correcao"]["resumo"]["total_registros_com_erro"] == 0
    assert out["documento_correcao"]["resumo"]["total_pendencias_revisao"] >= 1
