from __future__ import annotations

import json
from pathlib import Path

from app.browser.pyodide_entry import run_core_extraction_accuracy_flow_file_json, run_real_flow_mandatory_recovery_file_json
from app.config.version import CURRENT_RELEASE
from app.parser.row_inventory_proof import build_row_inventory_proof
from app.parser.physical_block_coverage import apply_physical_block_coverage_manifest
from app.parser.from_scratch_block_inventory import build_from_scratch_block_inventory
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
    return json.loads(run_core_extraction_accuracy_flow_file_json(str(pdf_path), json.dumps(payload or _result_with_blockers()), json.dumps(options)))


def test_v61_0_71_row_inventory_proof_marks_pre_recovery_open_rows():
    data = _result_with_blockers()
    apply_physical_block_coverage_manifest(data)
    proof = build_row_inventory_proof(data)
    summary = proof["summary"]
    assert summary["overall_status"] == "needs_review"
    assert summary["json_open_rows"] > 0
    assert any(s.get("key") == "93391|SINAPI" and s.get("row_destination_status") == "needs_review" for s in proof["needs_review_or_scope_samples"])


def test_v61_0_71_row_inventory_proof_reconciles_pdf_inventory_and_json_rows():
    data = _result_with_blockers()
    # Repair-like setup: use the existing PDF-first inventory and allow the real
    # flow test to verify patching; here the proof must be honest but not overly
    # strict before recovery.
    build_from_scratch_block_inventory(data, pdf_session=FakePdfSessionV62(), options={"target_blocks": ["93391|SINAPI", "89446|SINAPI"]})
    apply_physical_block_coverage_manifest(data)
    proof = build_row_inventory_proof(data)
    assert proof["summary"]["physical_inventory_scope"] == "full"
    assert proof["summary"]["physical_inventory_blocks_evaluated"] == proof["summary"]["composition_blocks_checked"]
    assert proof["summary"]["json_open_rows"] > 0


def test_v61_0_71_real_flow_runs_row_inventory_proof_without_regression(tmp_path: Path):
    out = _run_real(tmp_path)
    assert out["status"] == "ok"
    assert out["meta"]["parser_version"] == CURRENT_RELEASE
    metrics = out["quality_metrics"]
    assert metrics["row_inventory_proof_status"] == "complete"
    assert metrics["row_inventory_json_open_rows"] == 0
    assert metrics["row_inventory_orphan_numeric_fragments"] == 0
    assert metrics["row_inventory_physical_row_mismatch_count"] == 0
    proof = out["documento_evidencias"]["row_inventory_proof"]
    assert proof["summary"]["overall_status"] == "complete"
    assert proof["summary"]["composition_blocks_checked"] >= 2
    assert proof["summary"]["physical_inventory_scope"] in {"targeted", "full"}
    comps = _principais(out)
    row_1297 = [r for r in comps["93391|SINAPI"]["insumos"] if r.get("codigo") == "00001297"][0]
    assert row_1297["quant"] == "1,0571000"
    assert row_1297["total"] == "47,75"
    assert comps["89446|SINAPI"]["principal"]["quant"] == "1,0000000"


def test_v61_0_71_post_organizer_flow_preserves_row_inventory_proof(tmp_path: Path):
    pdf_path = tmp_path / "critical-pages.pdf"
    _write_problem_pages_pdf(pdf_path)
    out = json.loads(run_real_flow_mandatory_recovery_file_json(str(pdf_path), json.dumps(_result_with_blockers()), json.dumps(_options_with_bands())))
    assert out["status"] == "ok"
    assert out["documento_evidencias"]["row_inventory_proof"]["summary"]["overall_status"] == "complete"
    assert out["quality_metrics"]["row_inventory_json_open_rows"] == 0
    assert out["quality_metrics"]["coverage_post_recovery_blocking_targets"] == 0
