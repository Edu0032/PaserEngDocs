from __future__ import annotations

import json
from pathlib import Path

from app.browser.pyodide_entry import run_core_extraction_accuracy_flow_file_json, run_real_flow_mandatory_recovery_file_json
from app.config.version import CURRENT_RELEASE
from app.core.pdf_session import PdfDocumentSession
from app.parser.from_scratch_block_inventory import build_from_scratch_block_inventory
from app.parser.active_reextraction_engine import apply_active_reextraction_engine
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


def test_v61_0_70_from_scratch_inventory_scans_pdf_blocks_before_recovery():
    data = _result_with_blockers()
    rep = build_from_scratch_block_inventory(data, pdf_session=FakePdfSessionV62(), options={"target_blocks": ["93391|SINAPI", "89446|SINAPI"]})
    summary = rep["summary"]
    assert summary["block_count"] == 2
    assert summary["complete_block_count"] == 2
    assert summary["physical_rows_total"] >= 10
    blocks = {b["key"]: b for b in rep["blocks"]}
    assert blocks["93391|SINAPI"]["physical_row_count"] == 6
    assert blocks["93391|SINAPI"]["rows_with_numeric_tail"] == 6
    assert any(r["codigo"].strip() == "00001297" and r["tail"]["total"] == "47,75" for r in blocks["93391|SINAPI"]["row_samples"])
    assert blocks["89446|SINAPI"]["rows_with_numeric_tail"] == 5


def test_v61_0_70_active_reextraction_resolves_blocking_coverage_targets():
    data = _result_with_blockers()
    out, rep = apply_active_reextraction_engine(data, pdf_session=FakePdfSessionV62(), options={"mandatory_targeted": True})
    assert rep["pre_blocking_target_count"] > 0
    assert rep["post_blocking_target_count"] == 0
    assert rep["status"] == "ok"
    row_1297 = [r for r in out["composicoes"]["principais"]["93391|SINAPI"]["insumos"] if r.get("codigo") == "00001297"][0]
    assert row_1297["quant"] == "1,0571000"
    assert row_1297["valor_unit"] == "45,18"
    assert row_1297["total"] == "47,75"
    assert out["composicoes"]["principais"]["89446|SINAPI"]["principal"]["quant"] == "1,0000000"


def test_v61_0_70_real_flow_uses_inventory_and_active_reextraction(tmp_path: Path):
    out = _run_real(tmp_path)
    assert out["status"] == "ok"
    assert out["meta"]["parser_version"] == CURRENT_RELEASE
    perf = out["meta"]["performance"]
    assert "from_scratch_block_inventory" in perf
    assert "active_reextraction_engine" in out["documento_evidencias"]
    metrics = out["quality_metrics"]
    assert metrics["from_scratch_inventory_block_count"] >= 2
    assert metrics["from_scratch_inventory_complete_block_count"] >= 2
    assert metrics["active_reextraction_status"] in {"ok", "skipped"}
    assert metrics["coverage_post_recovery_blocking_targets"] == 0
    assert out["documento_evidencias"]["physical_block_coverage"]["summary"]["overall_status"] == "complete"

    comps = _principais(out)
    assert comps["93391|SINAPI"]["detalhes"]["banded_composition_closure"]["all_rows_locked"] is True
    assert comps["93391|SINAPI"]["detalhes"]["banded_composition_closure"]["free_fragments_after_closure"] == 0
    row_1297 = [r for r in comps["93391|SINAPI"]["insumos"] if r.get("codigo") == "00001297"][0]
    assert row_1297 == {**row_1297, "und": "m²", "quant": "1,0571000", "valor_unit": "45,18", "total": "47,75"}
    assert comps["89446|SINAPI"]["principal"]["total"] == "5,47"


def test_v61_0_70_worker_post_organizer_flow_keeps_new_safety_reports(tmp_path: Path):
    pdf_path = tmp_path / "critical-pages.pdf"
    _write_problem_pages_pdf(pdf_path)
    out = json.loads(run_real_flow_mandatory_recovery_file_json(str(pdf_path), json.dumps(_result_with_blockers()), json.dumps(_options_with_bands())))
    assert out["status"] == "ok"
    assert out["quality_metrics"]["active_reextraction_post_blocking_targets"] == 0
    assert out["quality_metrics"]["from_scratch_inventory_status"] == "complete"
    assert out["documento_correcao"]["resumo_final_curto"]["summary"]["quality_gate_ok"] is True


def test_v61_0_70_inventory_on_real_pdf_file_partial(tmp_path: Path):
    pdf_path = tmp_path / "critical-pages.pdf"
    _write_problem_pages_pdf(pdf_path)
    data = _result_with_blockers()
    with PdfDocumentSession(pdf_path.read_bytes()) as sess:
        rep = build_from_scratch_block_inventory(data, pdf_session=sess, options={"target_blocks": ["93391|SINAPI"]})
    block = rep["blocks"][0]
    assert block["key"] == "93391|SINAPI"
    assert block["inventory_status"] == "complete"
    assert block["physical_row_count"] == 6
    assert block["row_samples"][-1]["tail"]["total"] == "47,75"
