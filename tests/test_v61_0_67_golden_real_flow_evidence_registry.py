from __future__ import annotations

import json
from pathlib import Path

from app.browser.pyodide_entry import run_core_extraction_accuracy_flow_file_json, run_real_flow_mandatory_recovery_file_json
from app.config.version import CURRENT_RELEASE
from app.parser.evidence_registry import apply_evidence_registry
from test_v61_0_62_composition_locking_budget_ownership import _result_with_blockers
from test_v61_0_64_integrity_orchestrator_real_flow import _write_problem_pages_pdf
from test_v61_0_66_band_locked_clean_contract import _options_with_bands


def _principais(out: dict) -> dict:
    comps = out.get("composicoes") or {}
    return comps.get("principais") or ((comps.get("sinapi_like") or {}).get("principais") or {})


def _run_real_flow(tmp_path: Path, payload: dict | None = None) -> dict:
    pdf_path = tmp_path / "critical-pages.pdf"
    _write_problem_pages_pdf(pdf_path)
    options = {"accuracy_profile": {"enable_physical_evidence_index": False}, **_options_with_bands()}
    payload = payload or _result_with_blockers()
    return json.loads(run_core_extraction_accuracy_flow_file_json(str(pdf_path), json.dumps(payload), json.dumps(options)))


def test_v61_0_67_real_flow_builds_central_evidence_registry(tmp_path: Path):
    payload = _result_with_blockers()
    payload.setdefault("documento_correcao", {})["correction_preliminary_resumo"] = {"quality_gate_ok": False, "stale": True}
    out = _run_real_flow(tmp_path, payload)

    assert out["status"] == "ok"
    assert out["meta"]["parser_version"] == CURRENT_RELEASE
    assert out["auditoria_final"]["quality_gate"]["ok"] is True

    registry = out["documento_evidencias"]["evidence_registry"]
    assert registry["version"] == CURRENT_RELEASE
    assert registry["entry_count"] > 0
    assert registry["row_lock_count"] > 0
    assert registry["open_row_count"] == 0
    assert registry["locked_row_count"] == out["quality_metrics"]["evidence_registry_locked_row_count"]
    assert out["quality_metrics"]["evidence_registry_entry_count"] == registry["entry_count"]

    fields = registry["field_registry"]
    assert any(e.get("field") == "total" and e.get("value") == "47,75" and e.get("codigo") == "00001297" for e in fields)
    assert any(e.get("field") == "valor_unit" and e.get("value") == "5,47" and e.get("codigo") == "89446" for e in fields)


def test_v61_0_67_golden_cases_still_close_after_registry(tmp_path: Path):
    out = _run_real_flow(tmp_path)
    comps = _principais(out)

    row_1297 = [r for r in comps["93391|SINAPI"]["insumos"] if r.get("codigo") == "00001297"][0]
    assert row_1297["und"] == "m²"
    assert row_1297["quant"] == "1,0571000"
    assert row_1297["valor_unit"] == "45,18"
    assert row_1297["total"] == "47,75"
    closure = comps["93391|SINAPI"]["detalhes"]["banded_composition_closure"]
    assert closure["all_rows_locked"] is True
    assert closure["free_fragments_after_closure"] == 0
    assert closure["fragment_ownership_policy"].startswith("locked_rows_own")

    p89446 = comps["89446|SINAPI"]["principal"]
    assert p89446["und"] == "M"
    assert p89446["quant"] == "1,0000000"
    assert p89446["valor_unit"] == "5,47"
    assert p89446["total"] == "5,47"

    root = out["orcamento_sintetico"]["itens_raiz"][0]
    assert root["custo_total"] == "52.365,69"
    assert "custo_total" not in root["filhos"][0]
    assert out["lovable_consumption_policy"]["do_not_recalculate_public_totals"] is True


def test_v61_0_67_post_organizer_flow_uses_same_registry(tmp_path: Path):
    pdf_path = tmp_path / "critical-pages.pdf"
    _write_problem_pages_pdf(pdf_path)
    out = json.loads(run_real_flow_mandatory_recovery_file_json(str(pdf_path), json.dumps(_result_with_blockers()), json.dumps(_options_with_bands())))
    assert out["status"] == "ok"
    assert out["documento_evidencias"]["evidence_registry"]["entry_count"] > 0
    assert "mandatory_real_flow_recovery_after_organizer" in out["meta"]["performance"]


def test_v61_0_67_registry_can_be_rebuilt_without_duplicate_entries(tmp_path: Path):
    out = _run_real_flow(tmp_path)
    first_count = out["documento_evidencias"]["evidence_registry"]["entry_count"]
    rep = apply_evidence_registry(out)
    assert rep["entry_count"] == first_count
    paths = [(e.get("path"), e.get("field"), e.get("value"), e.get("producer"), e.get("status")) for e in rep["field_registry"]]
    assert len(paths) == len(set(paths))
