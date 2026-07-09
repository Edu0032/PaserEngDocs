from __future__ import annotations

import json
from pathlib import Path

import fitz

from app.browser.pyodide_entry import enrich_physical_evidence_index_file_json
from app.parser.line_certainty_closure import run_line_certainty_closure_engine
from app.parser.physical_evidence_index import build_physical_evidence_index, merge_physical_evidence_into_document_index
from app.parser.document_evidence_index import build_document_evidence_index


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


def _final_missing_total() -> dict:
    return {
        "orcamento_sintetico": {"itens_raiz": []},
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
                        "composicoes_auxiliares": [],
                        "insumos": [],
                    }
                },
                "auxiliares_globais": {},
            },
            "sicro": {"principais": {}, "auxiliares_globais": {}},
        },
        "documento_correcao": {"resumo": {}},
        "validacao": {"ocorrencias": []},
        "meta": {"performance": {}, "input_metadata": {"ranges": {"compositions": [1, 1]}}},
    }


def test_v42_physical_evidence_index_finds_codigo_banco_occurrence_once(tmp_path: Path):
    pdf = _write_pdf(tmp_path / "doc.pdf", ["89446 SINAPI TUBO PVC ESGOTO m 1,0000000 14,27 14,27"])
    index = build_physical_evidence_index(str(pdf), _final_missing_total(), {"ranges": {"compositions": [1, 1]}})
    assert index["status"] == "ok"
    assert index["key_count"] == 1
    assert index["occurrence_count"] == 1
    bucket = index["keys"]["89446|SINAPI"]
    assert bucket["fields"]["und"]["values"][0]["value"] == "m"
    assert bucket["fields"]["total"]["values"][0]["value"] == "14,27"


def test_v42_physical_index_enriches_document_index_and_closes_missing_total(tmp_path: Path):
    pdf = _write_pdf(tmp_path / "doc.pdf", ["89446 SINAPI TUBO PVC ESGOTO m 1,0000000 14,27 14,27"])
    final = _final_missing_total()
    enriched_json = enrich_physical_evidence_index_file_json(str(pdf), json.dumps(final), json.dumps({"ranges": {"compositions": [1, 1]}, "accuracy_profile": {"max_closure_rounds": 4}}))
    out = json.loads(enriched_json)
    assert out.get("status") != "error"
    principal = out["composicoes"]["sinapi_like"]["principais"]["89446|SINAPI"]["principal"]
    assert principal["total"] == "14,27"
    assert out["meta"]["performance"]["physical_evidence_index"]["occurrence_count"] == 1
    closure = out["meta"]["performance"]["line_certainty_closure_after_physical_index"]
    assert closure["rounds"][0]["physical_index_used"] is True
    assert any(r.get("reason") in {"field_consensus_resolution", "local_line_neighborhood_cascade_repair", "math_expected_value_found_near_same_codigo_banco"} and r.get("field") == "total" for r in closure["repairs"])
    assert "physical_evidence_index" in out["documento_correcao"]


def test_v42_math_expected_value_only_writes_when_found_in_physical_index(tmp_path: Path):
    pdf_no_total = _write_pdf(tmp_path / "doc_no_total.pdf", ["89446 SINAPI TUBO PVC ESGOTO m 1,0000000 14,27"])
    out = json.loads(enrich_physical_evidence_index_file_json(str(pdf_no_total), json.dumps(_final_missing_total()), json.dumps({"ranges": {"compositions": [1, 1]}})))
    principal = out["composicoes"]["sinapi_like"]["principais"]["89446|SINAPI"]["principal"]
    assert principal["total"] == ""
    assert principal["_calc"]["math_only_expectations"][0]["expected_value"] == "14,27"


def test_v42_merge_physical_evidence_into_document_index_supplies_physical_source(tmp_path: Path):
    pdf = _write_pdf(tmp_path / "doc.pdf", ["89446 SINAPI TUBO PVC ESGOTO m 1,0000000 14,27 14,27"])
    physical = build_physical_evidence_index(str(pdf), _final_missing_total(), {"ranges": {"compositions": [1, 1]}})
    base = build_document_evidence_index([])
    merged = merge_physical_evidence_into_document_index(base, physical)
    assert merged["mode"] == "global_extracted_plus_physical_document_evidence_index"
    assert merged["physical_evidence_index"]["occurrence_count"] == 1
    assert merged["keys"]["89446|SINAPI"]["fields"]["total"]["values"][0]["sources"] == ["physical_pdf_index"]


def test_v42_main_parser_does_not_run_redundant_sicro_section_closure():
    final = {
        "orcamento_sintetico": {"itens_raiz": []},
        "composicoes": {
            "sinapi_like": {"principais": {}, "auxiliares_globais": {}},
            "sicro": {"principais": {}, "auxiliares_globais": {}},
        },
        "documento_correcao": {"resumo": {}},
        "validacao": {"ocorrencias": []},
        "meta": {"performance": {}},
    }
    _out, report = run_line_certainty_closure_engine(final, apply=True)
    assert report["sicro_native_audit_bridge"]["mode"] == "native_sicro_only_engine_is_authoritative"
    assert report["sicro_native_audit_bridge"]["status"] == "not_run_in_main_parser"
    assert "sicro_section_closure" not in report


def test_v42_worker_runs_physical_index_before_targeted_recovery_and_avoids_repeated_full_pdf_targets():
    root = Path(__file__).resolve().parents[1]
    for worker in [root / "parser_browser/browser/pyodide/pyodide-parser-worker.js", root / "parser_browser/browser/demo/pyodide/pyodide-parser-worker.js"]:
        text = worker.read_text(encoding="utf-8")
        assert "enrich_physical_evidence_index_file_json" in text
        assert "physical-evidence-index-started" in text
        assert "the mandatory whole-document code+bank scan has already run" in text
