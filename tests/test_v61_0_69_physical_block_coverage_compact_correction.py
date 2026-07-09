from __future__ import annotations

import json
from pathlib import Path

from app.browser.pyodide_entry import run_core_extraction_accuracy_flow_file_json, run_real_flow_mandatory_recovery_file_json
from app.config.version import CURRENT_RELEASE
from app.parser.physical_block_coverage import build_physical_block_coverage_manifest
from test_v61_0_62_composition_locking_budget_ownership import _result_with_blockers
from test_v61_0_64_integrity_orchestrator_real_flow import _write_problem_pages_pdf
from test_v61_0_66_band_locked_clean_contract import _options_with_bands


def _run_real(tmp_path: Path, payload: dict | None = None) -> dict:
    pdf_path = tmp_path / "critical-pages.pdf"
    _write_problem_pages_pdf(pdf_path)
    options = {"accuracy_profile": {"enable_physical_evidence_index": False}, **_options_with_bands()}
    payload = payload or _result_with_blockers()
    return json.loads(run_core_extraction_accuracy_flow_file_json(str(pdf_path), json.dumps(payload), json.dumps(options)))


def _principais(out: dict) -> dict:
    comps = out.get("composicoes") or {}
    return comps.get("principais") or ((comps.get("sinapi_like") or {}).get("principais") or {})


def test_v61_0_69_real_flow_has_compact_physical_block_coverage(tmp_path: Path):
    out = _run_real(tmp_path)
    assert out["status"] == "ok"
    assert out["meta"]["parser_version"] == CURRENT_RELEASE

    coverage = out["documento_evidencias"]["physical_block_coverage"]
    summary = coverage["summary"]
    assert summary["overall_status"] == "complete"
    assert summary["composition_incomplete_block_count"] == 0
    assert summary["composition_open_rows"] == 0
    assert summary["useful_orphan_fragments"] == 0
    assert summary["budget_leaf_missing_count"] == 0

    manifests = {m["key"]: m for m in coverage["composition_manifests"]}
    assert manifests["93391|SINAPI"]["coverage_status"] == "complete"
    assert manifests["93391|SINAPI"]["locked_rows"] == 6
    assert manifests["93391|SINAPI"]["open_rows"] == 0

    metrics = out["quality_metrics"]
    assert metrics["physical_block_coverage_status"] == "complete"
    assert metrics["physical_block_composition_incomplete_count"] == 0
    assert metrics["physical_block_composition_open_rows"] == 0


def test_v61_0_69_compact_correction_document_is_short_final_state(tmp_path: Path):
    out = _run_real(tmp_path)
    compact = out["documento_correcao"]["resumo_final_curto"]
    assert compact["purpose"] in {"short_final_state_correction_document", "clean_actionable_correction_document_for_lovable_review"}
    assert compact["summary"]["quality_gate_ok"] is True
    assert compact["summary"]["blocking_issue_count"] == 0
    assert compact["pending_errors"] == []
    assert compact["supporting_material"]["physical_block_coverage_path"] == "documento_evidencias.physical_block_coverage"
    # The correction doc gives compact pointers instead of copying raw page text.
    assert "composition_manifests" not in compact


def test_v61_0_69_real_flow_still_preserves_critical_pdf_tokens_and_owners(tmp_path: Path):
    out = _run_real(tmp_path)
    comps = _principais(out)
    row_1297 = [r for r in comps["93391|SINAPI"]["insumos"] if r.get("codigo") == "00001297"][0]
    assert row_1297["und"] == "m²"
    assert row_1297["quant"] == "1,0571000"
    assert row_1297["valor_unit"] == "45,18"
    assert row_1297["total"] == "47,75"
    assert comps["89446|SINAPI"]["principal"]["quant"] == "1,0000000"
    root = out["orcamento_sintetico"]["itens_raiz"][0]
    assert root["custo_total"] == "52.365,69"
    assert "custo_total" not in root["filhos"][0]
    assert out["extraction_status"]["ok"] is True
    assert out["lovable_consumption_policy"]["do_not_recalculate_public_totals"] is True


def test_v61_0_69_coverage_manifest_marks_open_rows_before_recovery():
    data = _result_with_blockers()
    manifest = build_physical_block_coverage_manifest(data)
    summary = manifest["summary"]
    assert summary["overall_status"] == "needs_review"
    assert summary["composition_incomplete_block_count"] >= 1
    open_rows = manifest["open_rows_compact"]
    assert any(r.get("block") == "93391|SINAPI" and r.get("codigo") == "00001297" for r in open_rows)


def test_v61_0_69_post_organizer_real_flow_keeps_block_coverage(tmp_path: Path):
    pdf_path = tmp_path / "critical-pages.pdf"
    _write_problem_pages_pdf(pdf_path)
    out = json.loads(run_real_flow_mandatory_recovery_file_json(str(pdf_path), json.dumps(_result_with_blockers()), json.dumps(_options_with_bands())))
    assert out["status"] == "ok"
    assert out["documento_evidencias"]["physical_block_coverage"]["summary"]["overall_status"] == "complete"
    assert out["documento_correcao"]["resumo_final_curto"]["summary"]["quality_gate_ok"] is True
