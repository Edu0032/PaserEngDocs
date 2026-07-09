from __future__ import annotations

import json
from pathlib import Path

from app.browser.pyodide_entry import run_core_extraction_accuracy_flow_file_json, run_real_flow_mandatory_recovery_file_json
from app.config.version import CURRENT_RELEASE
from app.core.output_compact import refresh_quality_gate_after_repairs
from app.parser.budget_total_ownership import apply_budget_total_ownership_repair
from app.parser.coverage_engine import build_coverage_targets
from app.parser.extraction_consistency_status import apply_extraction_consistency_status
from app.parser.physical_numeric_tail_recovery import apply_physical_numeric_tail_recovery
from test_v61_0_62_composition_locking_budget_ownership import FakePdfSessionV62, _result_with_blockers
from test_v61_0_64_integrity_orchestrator_real_flow import _write_problem_pages_pdf
from test_v61_0_66_band_locked_clean_contract import _options_with_bands


def _principais(out: dict) -> dict:
    comps = out.get("composicoes") or {}
    return comps.get("principais") or ((comps.get("sinapi_like") or {}).get("principais") or {})


def _run_real(tmp_path: Path, payload: dict | None = None) -> dict:
    pdf_path = tmp_path / "critical-pages.pdf"
    _write_problem_pages_pdf(pdf_path)
    options = {"accuracy_profile": {"enable_physical_evidence_index": False}, **_options_with_bands()}
    payload = payload or _result_with_blockers()
    return json.loads(run_core_extraction_accuracy_flow_file_json(str(pdf_path), json.dumps(payload), json.dumps(options)))


def test_v61_0_68_coverage_targets_are_resolved_in_real_flow(tmp_path: Path):
    payload = _result_with_blockers()
    pre = build_coverage_targets(payload, phase="pre_recovery")
    assert pre["blocking_target_count"] > 0
    assert any(t.get("block") == "93391|SINAPI" for t in pre["targets"])

    out = _run_real(tmp_path, payload)
    assert out["status"] == "ok"
    assert out["meta"]["parser_version"] == CURRENT_RELEASE
    assert out["extraction_status"]["ok"] is True
    assert out["document_consistency_status"]["ok"] is True
    assert out["quality_metrics"]["coverage_pre_recovery_targets"] > 0
    assert out["quality_metrics"]["coverage_post_recovery_blocking_targets"] == 0

    comps = _principais(out)
    row_1297 = [r for r in comps["93391|SINAPI"]["insumos"] if r.get("codigo") == "00001297"][0]
    assert row_1297["total"] == "47,75"
    assert comps["89446|SINAPI"]["principal"]["quant"] == "1,0000000"


def test_v61_0_68_document_math_error_is_not_parser_extraction_error():
    data = _result_with_blockers()
    data, _ = apply_physical_numeric_tail_recovery(data, pdf_session=FakePdfSessionV62(), options={"mandatory_targeted": True})
    data, _ = apply_budget_total_ownership_repair(data)
    # Deliberately simulate a PDF-declared value that would make the document not close.
    # All fields are present: this is a document-consistency warning, not a missing extraction target.
    data["composicoes"]["principais"]["93391|SINAPI"]["insumos"][2]["total"] = "50,00"
    refresh_quality_gate_after_repairs(data)
    report = apply_extraction_consistency_status(data)
    assert report["extraction_status"]["ok"] is True
    assert report["document_consistency_status"]["ok"] is False
    assert report["document_consistency_status"]["issues"][0]["code"] == "document_math_inconsistency_pdf_values_preserved"
    assert report["document_consistency_status"]["public_values_preserved"] is True


def test_v61_0_68_evidence_registry_has_truth_types_and_audit_math_policy(tmp_path: Path):
    out = _run_real(tmp_path)
    reg = out["documento_evidencias"]["evidence_registry"]
    conflict = reg["conflict_resolution"]
    assert conflict["policy"] == "pdf_declared_values_are_public_truth_calculations_are_audit_only"
    fields = reg["field_registry"]
    assert any(e.get("truth_type") == "pdf_declared" and e.get("field") == "total" and e.get("value") == "47,75" for e in fields)
    assert all(e.get("truth_type") != "calculated_audit_only" or e.get("can_overwrite_public_value") is False for e in fields)
    assert out["lovable_consumption_policy"]["if_document_consistency_not_ok"] == "show_document_warning_but_do_not_overwrite_pdf_values"


def test_v61_0_68_post_organizer_flow_keeps_extraction_and_consistency_status(tmp_path: Path):
    pdf_path = tmp_path / "critical-pages.pdf"
    _write_problem_pages_pdf(pdf_path)
    out = json.loads(run_real_flow_mandatory_recovery_file_json(str(pdf_path), json.dumps(_result_with_blockers()), json.dumps(_options_with_bands())))
    assert out["status"] == "ok"
    assert out["extraction_status"]["ok"] is True
    assert out["document_consistency_status"]["ok"] is True
    assert out["quality_metrics"]["extraction_status_ok"] is True
    assert out["quality_metrics"]["document_consistency_status_ok"] is True
    assert "mandatory_real_flow_recovery_after_organizer" in out["meta"]["performance"]
