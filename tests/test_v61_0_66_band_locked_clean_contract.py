from __future__ import annotations

import json
from pathlib import Path

import fitz

from app.browser.pyodide_entry import run_core_extraction_accuracy_flow_file_json, run_real_flow_mandatory_recovery_file_json
from app.config.version import CURRENT_RELEASE
from app.parser.composition_banded_closure import apply_banded_composition_closure
from app.parser.integrity_orchestrator import run_final_integrity_orchestrator
from app.parser.public_numeric_evidence import build_public_numeric_evidence
from app.parser.token_fidelity import apply_public_token_fidelity
from test_v61_0_62_composition_locking_budget_ownership import FakePdfSessionV62, _result_with_blockers
from test_v61_0_64_integrity_orchestrator_real_flow import _write_problem_pages_pdf


def _principais(out: dict) -> dict:
    comps = out.get("composicoes") or {}
    return comps.get("principais") or ((comps.get("sinapi_like") or {}).get("principais") or {})


def _options_with_bands():
    return {
        "structured_tables": {
            "tables": [
                {
                    "family": "composition",
                    "kind": "composicao_sinapi_like",
                    "page_start": 24,
                    "page_end": 29,
                    "columns": [
                        {"canonical": "controle_linha", "x0": 35, "x1": 90, "physical_index": 0},
                        {"canonical": "codigo", "x0": 91, "x1": 113, "physical_index": 1},
                        {"canonical": "banco", "x0": 114, "x1": 148, "physical_index": 2},
                        {"canonical": "descricao", "x0": 149, "x1": 420, "physical_index": 3},
                        {"canonical": "tipo", "x0": 421, "x1": 427, "physical_index": 4, "metadata": {"ignore_in_domain": True}},
                        {"canonical": "und", "x0": 428, "x1": 450, "physical_index": 5},
                        {"canonical": "quant", "x0": 451, "x1": 490, "physical_index": 6},
                        {"canonical": "valor_unit", "x0": 491, "x1": 530, "physical_index": 7},
                        {"canonical": "total", "x0": 531, "x1": 570, "physical_index": 8},
                    ],
                }
            ]
        }
    }


def test_v61_0_66_token_fidelity_restores_pdf_public_tokens():
    data = _result_with_blockers()
    # Existing bad-format values are numerically right but not faithful tokens.
    data["composicoes"]["principais"]["93391|SINAPI"]["principal"]["quant"] = "1"
    data["composicoes"]["principais"]["93391|SINAPI"]["composicoes_auxiliares"][0]["valor_unit"] = "31,6"
    out, rep = apply_public_token_fidelity(data, pdf_session=FakePdfSessionV62(), options={**_options_with_bands(), "target_blocks": ["93391|SINAPI"]})
    block = out["composicoes"]["principais"]["93391|SINAPI"]
    assert block["principal"]["quant"] == "1,0000000"
    assert block["composicoes_auxiliares"][0]["valor_unit"] == "31,60"
    assert rep["patches_applied"] >= 2


def test_v61_0_66_banded_closure_uses_available_bands_and_locks_rows():
    data = _result_with_blockers()
    # Close first using existing PDF recovery, then check band closure contract.
    from app.parser.physical_numeric_tail_recovery import apply_physical_numeric_tail_recovery
    data, _ = apply_physical_numeric_tail_recovery(data, pdf_session=FakePdfSessionV62(), options={"mandatory_targeted": True})
    report = apply_banded_composition_closure(data, _options_with_bands())
    assert report["blocks_scanned"] >= 2
    closure = data["composicoes"]["principais"]["93391|SINAPI"]["detalhes"]["banded_composition_closure"]
    assert closure["status"] == "ok"
    assert closure["all_rows_locked"] is True
    assert closure["band_profile"]["source"] == "options_structured_tables"
    assert "quant" in closure["band_profile"]["effective_columns"]


def test_v61_0_66_public_evidence_reports_advisory_vs_blocking_modes():
    data = _result_with_blockers()
    out, report = build_public_numeric_evidence(data, pdf_session=FakePdfSessionV62(), options={"strict_public_evidence_required": False})
    assert report["evidence_gate_mode"] == "advisory_non_blocking"
    assert all(not m.get("blocks_json_ok") for m in report.get("missing_evidence", []) if m.get("field"))
    out2, report2 = build_public_numeric_evidence(data, pdf_session=FakePdfSessionV62(), options={"strict_public_evidence_required": True})
    assert report2["evidence_gate_mode"] == "strict_blocking"
    assert report2["blocking_missing_evidence"] or report2["public_numeric_without_evidence_count"] == 0


def test_v61_0_66_real_flow_cleans_contract_and_preserves_tokens(tmp_path: Path):
    pdf_path = tmp_path / "critical-pages.pdf"
    _write_problem_pages_pdf(pdf_path)
    payload = _result_with_blockers()
    payload.setdefault("documento_correcao", {})["correction_preliminary_resumo"] = {"quality_gate_ok": False}
    payload["composicoes"]["principais"]["93391|SINAPI"]["principal"]["quant"] = "1"
    options = {"accuracy_profile": {"enable_physical_evidence_index": False}, **_options_with_bands()}
    out = json.loads(run_core_extraction_accuracy_flow_file_json(str(pdf_path), json.dumps(payload), json.dumps(options)))
    assert out["status"] == "ok"
    assert out["meta"]["parser_version"] == CURRENT_RELEASE
    assert "correction_preliminary_resumo" not in out["documento_correcao"]
    assert out["analise_orcamentaria"]["pre_repair_snapshots"]["correction_preliminary_resumo"]["quality_gate_ok"] is False
    comp = _principais(out)["93391|SINAPI"]
    assert comp["principal"]["quant"] == "1,0000000"
    assert comp["detalhes"]["banded_composition_closure"]["all_rows_locked"] is True
    assert out["quality_metrics"]["public_numeric_evidence_gate_mode"] in {"advisory_non_blocking", "strict_blocking"}
    assert out["lovable_consumption_policy"]["do_not_recalculate_public_totals"] is True


def test_v61_0_66_worker_final_recovery_uses_same_real_flow(tmp_path: Path):
    pdf_path = tmp_path / "critical-pages.pdf"
    _write_problem_pages_pdf(pdf_path)
    options = _options_with_bands()
    out = json.loads(run_real_flow_mandatory_recovery_file_json(str(pdf_path), json.dumps(_result_with_blockers()), json.dumps(options)))
    assert out["status"] == "ok"
    assert _principais(out)["89446|SINAPI"]["principal"]["quant"] == "1,0000000"
    assert out["meta"]["performance"]["mandatory_real_flow_recovery_after_organizer"]["version"] == CURRENT_RELEASE
