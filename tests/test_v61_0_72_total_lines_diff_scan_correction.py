from __future__ import annotations

import json
from pathlib import Path

from app.browser.pyodide_entry import run_core_extraction_accuracy_flow_file_json
from app.config.version import CURRENT_RELEASE
from app.parser.budget_total_lines import apply_budget_total_lines
from app.parser.light_reextraction_diff_scan import build_light_reextraction_diff_scan_file
from test_v61_0_62_composition_locking_budget_ownership import _result_with_blockers
from test_v61_0_64_integrity_orchestrator_real_flow import _write_problem_pages_pdf
from test_v61_0_66_band_locked_clean_contract import _options_with_bands


def _principais(out: dict) -> dict:
    comps = out.get("composicoes") or {}
    return comps.get("principais") or ((comps.get("sinapi_like") or {}).get("principais") or {})


def test_v61_0_72_budget_total_lines_preserve_total_geral_token_and_owner():
    data = _result_with_blockers()
    budget = data["orcamento_sintetico"]
    budget["total"] = "698159,11"
    budget["itens_raiz"][0]["custo_total"] = "52.365,69"
    rep = apply_budget_total_lines(data)
    assert rep["has_total_geral"] is True
    assert budget["total"] == "698.159,11"
    assert "linhas_totais" not in budget
    assert budget["itens_raiz"][0]["custo_total"] == "52.365,69"
    assert any(l.get("item") == "1" and l.get("valor") == "52.365,69" for l in rep["total_index"])


def test_v61_0_72_light_diff_scan_runs_without_public_write(tmp_path: Path):
    pdf_path = tmp_path / "critical-pages.pdf"
    _write_problem_pages_pdf(pdf_path)
    data = _result_with_blockers()
    before = json.dumps(data, sort_keys=True, ensure_ascii=False)
    rep = build_light_reextraction_diff_scan_file(str(pdf_path), data, {"light_diff_scan_max_pages": 2})
    assert rep["attempted"] is True
    assert rep["scanned_pages"] > 0
    assert rep["policy"] == "only_detects_possible_left_behind_content_never_writes_public_fields"
    after = json.dumps({k: v for k, v in data.items() if k != "documento_evidencias" and k != "meta"}, sort_keys=True, ensure_ascii=False)
    before_main = json.dumps({k: v for k, v in _result_with_blockers().items() if k != "documento_evidencias" and k != "meta"}, sort_keys=True, ensure_ascii=False)
    assert after == before_main


def test_v61_0_72_real_flow_exports_total_lines_and_rich_correction(tmp_path: Path):
    pdf_path = tmp_path / "critical-pages.pdf"
    _write_problem_pages_pdf(pdf_path)
    payload = _result_with_blockers()
    payload["orcamento_sintetico"]["total"] = "698159,11"
    options = {"accuracy_profile": {"enable_physical_evidence_index": False}, **_options_with_bands()}
    out = json.loads(run_core_extraction_accuracy_flow_file_json(str(pdf_path), json.dumps(payload), json.dumps(options)))
    assert out["status"] == "ok"
    assert out["meta"]["parser_version"] == CURRENT_RELEASE
    assert out["orcamento_sintetico"]["total"] == "698.159,11"
    assert "linhas_totais" not in out["orcamento_sintetico"]
    assert out["orcamento_sintetico"]["itens_raiz"][0]["custo_total"] == "52.365,69"
    metrics = out["quality_metrics"]
    assert metrics["budget_has_total_geral"] is True
    assert metrics["budget_total_index_count"] >= 2
    assert metrics["light_diff_scan_status"] in {"ok", "needs_review", "skipped"}
    corr = out["documento_correcao"]["resumo_final_curto"]
    assert corr["supporting_material"]["light_diff_scan_path"] == "documento_evidencias.light_reextraction_diff_scan"
    assert corr["supporting_material"]["row_inventory_proof_path"] == "documento_evidencias.row_inventory_proof"
    assert isinstance(corr["applied_patches"], list)
    comp = _principais(out)["93391|SINAPI"]
    row_1297 = [r for r in comp["insumos"] if r.get("codigo") == "00001297"][0]
    assert row_1297["total"] == "47,75"
    assert _principais(out)["89446|SINAPI"]["principal"]["quant"] == "1,0000000"
