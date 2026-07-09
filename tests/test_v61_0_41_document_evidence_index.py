from __future__ import annotations

from pathlib import Path

from app.parser.adaptive_closure_scheduler import build_adaptive_closure_schedule
from app.parser.document_evidence_index import build_document_evidence_index, compact_index_report
from app.parser.field_consensus_engine import build_field_consensus_candidates
from app.parser.line_certainty_closure import run_line_certainty_closure_engine
from app.parser.batch_code_bank_occurrence_indexer import build_batch_code_bank_occurrence_targets


def _final_budget_with_duplicate_evidence():
    return {
        "orcamento_sintetico": {
            "itens_raiz": [
                {"tipo": "item", "item": "1.1", "codigo": "CP-01", "fonte": "PRÓPRIO", "especificacao": "SERVIÇO TESTE", "und": "m", "quant": "2,00", "custo_unitario_com_bdi": "10,00", "custo_parcial": "", "filhos": []},
                {"tipo": "item", "item": "1.2", "codigo": "CP-01", "fonte": "PRÓPRIO", "especificacao": "SERVIÇO TESTE", "und": "m", "quant": "2,00", "custo_unitario_com_bdi": "10,00", "custo_parcial": "20,00", "filhos": []},
            ]
        },
        "composicoes": {"sinapi_like": {"principais": {}, "auxiliares_globais": {}}, "sicro": {"principais": {}, "auxiliares_globais": {}}},
        "documento_correcao": {"resumo": {}},
        "validacao": {"ocorrencias": []},
        "meta": {"performance": {}},
    }


def test_v41_document_evidence_index_and_consensus_fill_missing_public_field_only_from_evidence():
    out, report = run_line_certainty_closure_engine(_final_budget_with_duplicate_evidence(), apply=True)
    first = out["orcamento_sintetico"]["itens_raiz"][0]
    assert first["custo_parcial"] == "20,00"
    assert any(r.get("reason") == "field_consensus_resolution" and r.get("field") == "custo_parcial" for r in report["repairs"])
    assert report["document_evidence_index"]["key_count"] >= 1
    assert report["field_consensus_engine"]["candidate_count"] >= 0
    assert "document_evidence_index" in out["documento_correcao"]
    assert "field_consensus_engine" in out["documento_correcao"]


def test_v41_math_expectation_remains_calc_when_document_index_has_no_matching_value():
    final = _final_budget_with_duplicate_evidence()
    final["orcamento_sintetico"]["itens_raiz"] = final["orcamento_sintetico"]["itens_raiz"][:1]
    out, report = run_line_certainty_closure_engine(final, apply=True)
    first = out["orcamento_sintetico"]["itens_raiz"][0]
    assert first["custo_parcial"] == ""
    assert first["_calc"]["math_only_expectations"][0]["expected_value"] == "20,00"
    assert report["rows"][0]["field_evidence_grades"]["custo_parcial"]["evidence_grade"] == "math_only_expected"


def test_v41_batch_code_bank_targets_group_unresolved_rows_by_identity():
    final = _final_budget_with_duplicate_evidence()
    final["orcamento_sintetico"]["itens_raiz"][1]["custo_parcial"] = ""
    _out, report = run_line_certainty_closure_engine(final, apply=True)
    targets = build_batch_code_bank_occurrence_targets(report)
    assert targets
    assert targets[0]["strategy"] == "batch_full_pdf_code_bank_occurrence_index"
    assert targets[0]["identity_policy"] == "codigo_plus_banco_is_id"
    assert targets[0]["mandatory"] is True
    assert targets[0]["row_target_count"] >= 1


def test_v41_adaptive_scheduler_prioritizes_missing_critical_fields():
    schedule = build_adaptive_closure_schedule([
        {"row_id": "r-open", "row_status": "unresolved", "missing_fields": ["und", "total"], "math_status": {"ok": False}},
        {"row_id": "r-ok", "row_status": "closed_100", "missing_fields": [], "math_status": {"ok": True}},
    ])
    assert schedule["summary"]["P0"] == 1
    assert schedule["summary"]["P3"] == 1
    assert "batch_code_bank_occurrence_index" in schedule["buckets"]["P0"][0]["recommended_actions"]


def test_v41_worker_and_bundle_source_expose_batch_occurrence_indexing():
    root = Path(__file__).resolve().parents[1]
    for worker in [root / "parser_browser/browser/pyodide/pyodide-parser-worker.js", root / "parser_browser/browser/demo/pyodide/pyodide-parser-worker.js"]:
        text = worker.read_text(encoding="utf-8")
        assert "full_pdf_code_bank_occurrence_batch_targets" in text
        assert "strategic_batch_index" in text
        assert "batch_full_pdf_code_bank_occurrence_target" in text
    assert not (root / "parser_browser/app/parser/sicro_section_contracts.py").exists()
    assert (root / "parser_browser/app/sicro_only/sicro_twopass.py").exists()
