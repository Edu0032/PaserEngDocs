from __future__ import annotations

import json
from pathlib import Path

import fitz

from app.browser.pyodide_entry import run_output_contract_final_flow_file_json, organize_output_documents_json
from app.parser.output_documents_organizer import organize_lovable_output_documents


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


def _final_with_unit_and_missing_total() -> dict:
    return {
        "orcamento_sintetico": {
            "itens_raiz": [
                {
                    "item": "1.1",
                    "codigo": "95877",
                    "fonte": "SINAPI",
                    "especificacao": "TRANSPORTE COM CAMINHÃO BASCULANTE",
                    "und": "M3XKM",
                    "quant": "10,00",
                    "custo_unitario_com_bdi": "2,61",
                    "custo_parcial": "",
                },
                {
                    "item": "1.2",
                    "codigo": "ANP 01",
                    "fonte": "Próprio",
                    "especificacao": "AQUISIÇÃO DE ASFALTO DILUIDO CM-30",
                    "und": "t",
                    "quant": "1,50",
                    "custo_unitario_com_bdi": "9.544,40",
                    "custo_parcial": "14.316,60",
                },
            ]
        },
        "composicoes": {"sinapi_like": {"principais": {}, "auxiliares_globais": {}}, "sicro": {"principais": {}, "auxiliares_globais": {}}},
        "documento_correcao": {"resumo": {}, "warnings": []},
        "validacao": {"ocorrencias": []},
        "meta": {"performance": {}, "input_metadata": {"ranges": {"budget": [1, 1], "compositions": [1, 1]}}},
    }


def test_v48_separates_evidence_from_enrichment_and_repairs_math_field(tmp_path: Path):
    pdf = _write_pdf(tmp_path / "doc.pdf", [
        "ANEXO 1 - ORÇAMENTO SINTÉTICO",
        "1.1 95877 SINAPI TRANSPORTE COM CAMINHÃO BASCULANTE M3XKM 10,00 2,15 2,61 26,10",
        "1.2 ANP 01 Próprio AQUISIÇÃO DE ASFALTO DILUIDO CM-30 t 1,50 8.408,43 9.544,40 14.316,60",
    ])
    out = json.loads(run_output_contract_final_flow_file_json(str(pdf), json.dumps(_final_with_unit_and_missing_total()), json.dumps({"ranges": {"budget": [1, 1]}, "accuracy_profile": {"max_closure_rounds": 5}})))
    row = out["orcamento_sintetico"]["itens_raiz"][0]
    assert row["custo_parcial"] == "26,10"
    assert out["documento_evidencias"]["document_type"] == "documento_evidencias"
    assert out["documento_evidencias"]["cascade_repairs"]["applied_repairs"]
    enrichment = out["documento_enriquecimento"]
    assert enrichment["document_type"] == "documento_enriquecimento"
    assert enrichment["approval_policy"]["auto_apply_to_base_config"] is False
    assert "cascade_repairs" not in enrichment
    aliases = enrichment["bank_aliases_detected"]
    assert any(a["normalized"] == "PROPRIO" for a in aliases)
    assert any(p["pattern_type"] == "codigo_proprio_com_espaco" for p in enrichment["code_patterns_detected"])
    assert out["analise_orcamentaria"]["outputs_contract"]["evidence_document_path"] == "documento_evidencias"


def test_v48_enrichment_flags_suspicious_unit_without_polluting_base_config():
    final = {
        "orcamento_sintetico": {"itens_raiz": [{"codigo": "ANP 01", "fonte": "Próprio", "und": "CM-30"}]},
        "documento_correcao": {},
        "analise_orcamentaria": {},
    }
    organize_lovable_output_documents(final, {"summary": {"total_rows": 1, "closed_100": 0}})
    suspicious = final["documento_enriquecimento"]["unit_candidates"]["suspicious_unit_candidates"]
    assert any(x["value"] == "CM-30" for x in suspicious)
    assert not any(x.get("value") == "CM-30" for x in final["documento_enriquecimento"]["unit_candidates"]["new_unit_candidates"])


def test_v48_correction_document_has_human_review_queue_and_actions():
    final = {"documento_correcao": {}, "analise_orcamentaria": {}}
    closure = {
        "summary": {"total_rows": 1, "unresolved": 1},
        "rows": [
            {
                "row_id": "budget:95877|SINAPI",
                "closure_status": "unresolved",
                "family": "budget",
                "codigo": "95877",
                "banco": "SINAPI",
                "missing_fields": ["custo_parcial"],
                "math_status": {"status": "missing_values", "ok": False},
            }
        ],
        "local_line_cascade_repair": {"rejected": [{"row_id": "budget:95877|SINAPI", "field": "custo_parcial", "reason": "expected_value_not_found"}]},
    }
    organize_lovable_output_documents(final, closure)
    audit = final["documento_correcao"]["auditoria_humana"]
    assert audit["summary"]["review_queue_count"] == 1
    assert audit["queue"][0]["categories"] == ["campo_vazio", "campo_matematico_vazio", "matematica_incompleta"]
    assert "validar por fórmula" in audit["queue"][0]["suggested_action"]


def test_v48_organize_output_documents_json_rebuilds_after_late_changes():
    final = {"documento_correcao": {}, "analise_orcamentaria": {}, "meta": {"performance": {}}}
    closure = {"summary": {"total_rows": 0, "closed_100": 0}}
    out = json.loads(organize_output_documents_json(json.dumps(final), json.dumps(closure)))
    assert out["documento_evidencias"]["document_type"] == "documento_evidencias"
    assert out["documento_enriquecimento"]["document_type"] == "documento_enriquecimento"
    assert out["documento_correcao"]["manual_consumo_lovable_resumo"]["documento_evidencias"].startswith("provas")
