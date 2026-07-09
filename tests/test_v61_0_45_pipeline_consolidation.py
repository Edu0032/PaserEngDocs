from __future__ import annotations

import json
from pathlib import Path

import fitz

from app.browser.pyodide_entry import enrich_physical_evidence_index_file_json
from app.parser.pipeline_consolidation import build_pipeline_consolidation_report, consolidate_correction_document


def _write_pdf(path: Path, lines: list[str]) -> Path:
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    y = 72
    for line in lines:
        page.insert_text((40, y), line, fontsize=10)
        y += 18
    doc.save(path)
    doc.close()
    return path


def _final_v45() -> dict:
    return {
        "orcamento_sintetico": {
            "itens_raiz": [
                {
                    "item": "1",
                    "descricao": "SERVIÇOS",
                    "custo_total": "142,70",
                    "filhos": [
                        {
                            "item": "1.1",
                            "codigo": "89446",
                            "fonte": "SINAPI",
                            "especificacao": "TUBO PVC ESGOTO",
                            "und": "m",
                            "quant": "10,0000",
                            "custo_unitario_com_bdi": "14,27",
                            "custo_parcial": "142,70",
                        }
                    ],
                }
            ]
        },
        "composicoes": {
            "sinapi_like": {
                "principais": {
                    "89446|SINAPI": {
                        "principal": {
                            "codigo": "89446",
                            "banco": "SINAPI",
                            "descricao": "TUBO PVC ESGOTO",
                            "und": "m",
                            "quant": "1,0000000",
                            "valor_unit": "14,27",
                            "total": "",
                        },
                        "composicoes_auxiliares": [
                            {
                                "codigo": "88267",
                                "banco": "SINAPI",
                                "descricao": "",
                                "und": "h",
                                "quant": "0,1200000",
                                "valor_unit": "22,45",
                                "total": "2,69",
                            },
                            {
                                "codigo": "AUX-SEM-GLOBAL",
                                "banco": "SINAPI",
                                "descricao": "AUXILIAR REFERENCIADA SEM GLOBAL",
                                "und": "h",
                                "quant": "1,0000000",
                                "valor_unit": "11,58",
                                "total": "11,58",
                            },
                        ],
                        "insumos": [],
                    }
                },
                "auxiliares_globais": {
                    "88267|SINAPI": {
                        "principal": {
                            "codigo": "88267",
                            "banco": "SINAPI",
                            "descricao": "ENCANADOR COM ENCARGOS COMPLEMENTARES",
                            "und": "h",
                            "quant": "1,0000000",
                            "valor_unit": "22,45",
                            "total": "22,45",
                        }
                    }
                },
            },
            "sicro": {"principais": {}, "auxiliares_globais": {}},
        },
        "documento_correcao": {"resumo": {}, "warnings": []},
        "validacao": {"ocorrencias": []},
        "meta": {"performance": {}, "input_metadata": {"ranges": {"budget": [1, 1], "compositions": [1, 1]}}},
    }


def test_v45_consolidation_report_has_ordered_effective_pipeline():
    closure_report = {
        "summary": {"total_rows": 3, "closed_100": 2, "closed_by_strong_consensus": 1, "closed_with_warning": 0, "unresolved": 0, "repairs_applied": 2, "sicro_issues": 0},
        "rows": [{"row_id": "r1", "row_status": "closed_100"}, {"row_id": "r2", "row_status": "closed_by_strong_consensus"}],
        "repairs": [{"row_id": "r2", "field": "total", "after": "14,27", "reason": "field_consensus_resolution"}],
        "document_evidence_index": {"status": "ok", "key_count": 2, "evidence_value_count": 5, "occurrence_count": 2},
        "physical_evidence_index": {"status": "ok", "key_count": 1, "occurrence_count": 1},
        "field_consensus_engine": {"candidate_count": 1, "rejected": []},
        "budget_puzzle_resolver": {"summary": {"relations": 4, "chains": 1, "missing_global_auxiliaries": 0, "composition_cost_mismatches": 0, "budget_hierarchy_mismatches": 0, "chain_conflicts": 0}},
        "final_reconciliation_pass": {"issue_count": 0, "issues": []},
    }
    report = build_pipeline_consolidation_report(_final_v45(), closure_report)
    steps = [s["step"] for s in report["execution_order"]]
    assert steps.index("document_evidence_index") < steps.index("budget_puzzle_resolver") < steps.index("final_reconciliation_pass")
    assert report["summary"]["useful_repairs"] == 1
    assert report["pipeline_ok"] is True


def test_v45_consolidated_correction_document_dedupes_and_adds_actionable_sections():
    final = _final_v45()
    final["documento_correcao"]["warnings"] = [
        {"tipo": "x", "row_id": "r", "reason": "a"},
        {"tipo": "x", "row_id": "r", "reason": "a"},
    ]
    closure_report = {
        "summary": {"total_rows": 1, "closed_100": 0, "closed_by_strong_consensus": 0, "closed_with_warning": 0, "unresolved": 1, "repairs_applied": 0, "sicro_issues": 0},
        "rows": [{"row_id": "r", "row_status": "unresolved", "family": "sinapi_like", "codigo": "89446", "banco": "SINAPI", "missing_fields": ["total"], "reasons": ["missing_required_fields"]}],
        "budget_puzzle_resolver": {"summary": {"relations": 1, "chains": 1}},
        "final_reconciliation_pass": {"issue_count": 1, "issues": [{"code": "pending"}]},
    }
    report = consolidate_correction_document(final, closure_report)
    doc = final["documento_correcao"]
    assert len(doc["warnings"]) == 1
    assert "auditoria_consolidada" in doc
    assert doc["pendencias_para_resolucao"][0]["suggested_next_action"].startswith("procurar campo")
    from app.config.version import CURRENT_RELEASE
    assert final["analise_orcamentaria"]["pipeline_consolidation"]["version"] == CURRENT_RELEASE
    assert report["pipeline_ok"] is False


def test_v45_mini_flow_exports_consolidated_audit_and_execution_order(tmp_path: Path):
    pdf = _write_pdf(
        tmp_path / "doc.pdf",
        ["Memorial: Código 89446 SINAPI - TUBO PVC ESGOTO - Unidade m - Valor 14,27 - Total 14,27"],
    )
    out = json.loads(
        enrich_physical_evidence_index_file_json(
            str(pdf),
            json.dumps(_final_v45()),
            json.dumps({"ranges": {"budget": [1, 1], "compositions": [1, 1]}, "accuracy_profile": {"max_closure_rounds": 5}}),
        )
    )
    assert out.get("status") != "error"
    from app.config.version import CURRENT_RELEASE
    assert out["analise_orcamentaria"]["version"] == CURRENT_RELEASE
    assert "pipeline_consolidation" in out["analise_orcamentaria"]
    doc = out["documento_correcao"]
    assert "auditoria_consolidada" in doc
    assert "resumo_executivo" in doc
    assert "ordem_execucao_pipeline" in doc
    steps = [s["step"] for s in doc["ordem_execucao_pipeline"]]
    assert "physical_evidence_index" in steps
    assert "budget_reconstruction_graph" in steps
    assert "final_reconciliation_pass" in steps
    assert isinstance(doc.get("pendencias_para_resolucao"), list)
