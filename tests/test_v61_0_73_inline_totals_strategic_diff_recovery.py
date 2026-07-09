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


def test_v61_0_73_budget_totals_are_inline_not_detached_public_lines():
    data = _result_with_blockers()
    budget = data["orcamento_sintetico"]
    budget["total"] = "698159,11"
    budget["itens_raiz"][0]["custo_total"] = "52.365,69"
    rep = apply_budget_total_lines(data)
    assert rep["has_total_geral"] is True
    assert rep["public_budget_has_detached_total_lines"] is False
    assert budget["total"] == "698.159,11"
    assert "linhas_totais" not in budget
    assert budget["itens_raiz"][0]["custo_total"] == "52.365,69"
    assert budget["itens_raiz"][0]["_display"]["total_field"] == "custo_total"
    assert budget["display_policy"]["totals"]["meta_submeta_totals"] == "show_custo_total_inline_on_the_same_hierarchy_node"
    assert any(l.get("item") == "1" and l.get("valor") == "52.365,69" for l in rep["total_index"])


def test_v61_0_73_strategic_diff_scan_structures_left_behind_line(tmp_path: Path):
    pdf_path = tmp_path / "diff.pdf"
    # Use PyMuPDF through the helper style of project tests.
    import fitz  # type: ignore
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((50, 100), "Composição 99999 SINAPI SERVICO TESTE M 1,0000000 10,00 10,00", fontsize=8)
    doc.save(str(pdf_path))
    doc.close()
    data = {"orcamento_sintetico": {}, "composicoes": {"principais": {"88888|SINAPI": {"principal": {"codigo": "88888", "banco": "SINAPI"}, "pagina_inicio": 1, "pagina_fim": 1}}}}
    rep = build_light_reextraction_diff_scan_file(str(pdf_path), data, {})
    assert rep["status"] == "needs_review"
    assert rep["potential_missing_code_count"] >= 1
    sample = rep["potential_missing_lines"][0]
    assert sample["parsed_columns"]["codigo"] == "99999"
    assert sample["parsed_columns"]["banco"] == "SINAPI"
    assert sample["parsed_columns"]["und"] == "M"
    assert sample["possible_destination_candidates"]
    assert data["documento_correcao"]["possible_left_behind_lines"]


def test_v61_0_73_real_flow_keeps_inline_budget_total_and_clean_correction(tmp_path: Path):
    pdf_path = tmp_path / "critical-pages.pdf"
    _write_problem_pages_pdf(pdf_path)
    payload = _result_with_blockers()
    payload["orcamento_sintetico"]["total"] = "698159,11"
    options = {"accuracy_profile": {"enable_physical_evidence_index": False}, **_options_with_bands()}
    out = json.loads(run_core_extraction_accuracy_flow_file_json(str(pdf_path), json.dumps(payload), json.dumps(options)))
    assert out["status"] == "ok"
    assert out["meta"]["parser_version"] == CURRENT_RELEASE
    budget = out["orcamento_sintetico"]
    assert budget["total"] == "698.159,11"
    assert "linhas_totais" not in budget
    assert budget["itens_raiz"][0]["custo_total"] == "52.365,69"
    assert budget["display_policy"]["totals"]["do_not_render_documento_evidencias_total_index_as_public_rows"] is True
    metrics = out["quality_metrics"]
    assert metrics["budget_has_total_geral"] is True
    assert metrics["budget_public_detached_total_lines"] is False
    assert metrics["light_diff_scan_status"] in {"ok", "needs_review", "skipped"}
    corr = out["documento_correcao"]["resumo_final_curto"]
    assert corr["purpose"] == "clean_actionable_correction_document_for_lovable_review"
    assert "debug_recovery_path" in corr["supporting_material"]
    assert "targeted_recovery" not in out["documento_correcao"]
    comp = _principais(out)["93391|SINAPI"]
    row_1297 = [r for r in comp["insumos"] if r.get("codigo") == "00001297"][0]
    assert row_1297["total"] == "47,75"
    assert _principais(out)["89446|SINAPI"]["principal"]["quant"] == "1,0000000"
