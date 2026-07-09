from __future__ import annotations

from app.parser.line_certainty_closure import run_line_certainty_closure_engine
from app.parser.output_documents_organizer import organize_lovable_output_documents
from app.parser.output_accuracy_report import build_output_accuracy_report
from app.parser.output_contract_validator import validate_output_contract


def _fixture():
    return {
        "orcamento_sintetico": {
            "total": "405,65",
            "itens_raiz": [
                {"tipo": "item", "item": "4.9.2", "codigo": "89446", "fonte": "SINAPI", "especificacao": "TUBO PVC", "und": "M", "quant": "61,00", "custo_unitario_sem_bdi": "5,47", "custo_unitario_com_bdi": "6,65", "custo_parcial": "405,65"}
            ],
        },
        "composicoes": {
            "principais": {
                "89446|SINAPI": {
                    "item": "4.9.2",
                    "principal": {"codigo": "89446", "banco": "SINAPI", "descricao": "TUBO PVC", "und": "M"},
                    "composicoes_auxiliares": [
                        {"codigo": "88248", "banco": "SINAPI", "descricao": "AUXILIAR", "und": "H", "quant": "0,0195", "valor_unit": "25,34", "total": "0,49"},
                        {"codigo": "88267", "banco": "SINAPI", "descricao": "ENCANADOR", "und": "H", "quant": "0,0195", "valor_unit": "31,03", "total": "0,60"},
                    ],
                    "insumos": [
                        {"codigo": "00009868", "banco": "SINAPI", "descricao": "TUBO", "und": "M", "quant": "1,0493", "valor_unit": "4,17", "total": "4,37"},
                        {"codigo": "00038383", "banco": "SINAPI", "descricao": "LIXA", "und": "UN", "quant": "0,0045", "valor_unit": "2,55", "total": "0,01"},
                    ],
                }
            },
            "auxiliares_globais": {},
            "sinapi_like": {"principais": {}, "auxiliares_globais": {}},
            "sicro": {"principais": {}, "auxiliares_globais": {}},
        },
        "documento_correcao": {"resumo": {}},
    }


def test_v61_0_53_accuracy_report_reflects_repaired_composition_and_budget_math():
    out, report = run_line_certainty_closure_engine(_fixture(), apply=True, max_rounds=2)
    organize_lovable_output_documents(out, report)
    acc = out["analise_orcamentaria"]["accuracy_report"]
    from app.config.version import CURRENT_RELEASE
    assert acc["version"] == CURRENT_RELEASE
    assert acc["budget"]["math_ok"] == 1
    # v61.0.59: component sums are audit-only and must not create public
    # principal numbers without physical PDF tokens.
    assert acc["compositions"]["principal_triplet_ok"] == 0
    principal = out["composicoes"]["principais"]["89446|SINAPI"]["principal"]
    assert "quant" not in principal
    assert "valor_unit" not in principal
    assert "total" not in principal
    assert report["composition_principal_cascade_repair"]["summary"]["blocked"] >= 1


def test_v61_0_53_correction_document_has_severity_buckets_and_lovable_panel():
    out, report = run_line_certainty_closure_engine(_fixture(), apply=True, max_rounds=2)
    out.setdefault("documento_correcao", {})["targeted_recovery"] = {
        "attempted": True,
        "target_count": 3,
        "patches": [],
        "unresolved": [
            {"target_id": "noop", "field": "descricao", "reason": "no_op_same_value", "current_value": "TUBO", "candidate_value": "TUBO"},
            {"target_id": "real", "field": "descricao", "issue": "possible_truncated_description", "reason": "target_line_not_found", "codigo": "X", "banco": "SINAPI", "current_value": "ABC"},
        ],
    }
    organize_lovable_output_documents(out, report)
    human = out["documento_correcao"]["auditoria_humana"]
    assert "bloqueantes" in human and "revisoes_recomendadas" in human and "avisos" in human
    assert human["summary"]["targeted_recovery_diagnostic_ignored"] == 1
    assert out["documento_correcao"]["painel_lovable"]["status"] in {"ok", "needs_review"}
    assert out["documento_correcao"]["resumo"]["total_registros_com_erro"] == human["summary"]["bloqueantes"]


def test_v61_0_53_output_contract_validator_rejects_runtime_payload_config():
    out, report = run_line_certainty_closure_engine(_fixture(), apply=True, max_rounds=2)
    organize_lovable_output_documents(out, report)
    ok_report = validate_output_contract(out, {"document": {"filename": "x.pdf"}, "ranges": {}})
    assert ok_report["ok"] is True
    bad_report = validate_output_contract(out, {"document": {}, "docling_timeout_ms": 1, "fixed_contract": {}})
    assert bad_report["ok"] is False
    assert len(bad_report["payload_boundary"]["forbidden_runtime_or_admin_keys"]) >= 2


def test_v61_0_53_enrichment_stays_domain_only_and_accuracy_report_export_works():
    final = _fixture()
    final["meta"] = {"performance": {"internal": {"und": "INTERNAL_SHOULD_NOT_APPEAR"}}}
    organize_lovable_output_documents(final, {"rows": [], "summary": {}, "physical_evidence_index": {"keys": {}}})
    assert "INTERNAL_SHOULD_NOT_APPEAR" not in str(final["documento_enriquecimento"])
    acc = build_output_accuracy_report(final, {})
    assert acc["budget"]["leaf_items"] == 1
