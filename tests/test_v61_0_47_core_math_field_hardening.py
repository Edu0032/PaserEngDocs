from __future__ import annotations

import json
from pathlib import Path

import fitz

from app.browser.pyodide_entry import run_core_extraction_accuracy_flow_file_json
from app.parser.line_certainty_closure import run_line_certainty_closure_engine
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


def _budget_missing_partial() -> dict:
    return {
        "orcamento_sintetico": {
            "itens_raiz": [
                {
                    "item": "1.1",
                    "codigo": "89446",
                    "fonte": "SINAPI",
                    "especificacao": "TUBO PVC ESGOTO",
                    "und": "m",
                    "quant": "10,00",
                    "custo_unitario_com_bdi": "14,27",
                    "custo_parcial": "",
                }
            ]
        },
        "composicoes": {"sinapi_like": {"principais": {}, "auxiliares_globais": {}}, "sicro": {"principais": {}, "auxiliares_globais": {}}},
        "documento_correcao": {"resumo": {}, "warnings": []},
        "validacao": {"ocorrencias": []},
        "meta": {"performance": {}, "input_metadata": {"ranges": {"budget": [1, 1], "compositions": [1, 1]}}},
    }


def _composition_missing_total() -> dict:
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
        "documento_correcao": {"resumo": {}, "warnings": []},
        "validacao": {"ocorrencias": []},
        "meta": {"performance": {}, "input_metadata": {"ranges": {"compositions": [1, 1]}}},
    }


def test_v47_local_cascade_finds_math_expected_value_near_known_budget_line(tmp_path: Path):
    pdf = _write_pdf(tmp_path / "budget.pdf", ["ANEXO 1 - ORÇAMENTO SINTÉTICO", "1.1 89446 SINAPI TUBO PVC ESGOTO m 10,00 12,00 14,27 142,70"])
    out = json.loads(run_core_extraction_accuracy_flow_file_json(str(pdf), json.dumps(_budget_missing_partial()), json.dumps({"ranges": {"budget": [1, 1], "compositions": [1, 1]}, "accuracy_profile": {"max_closure_rounds": 5}})))
    row = out["orcamento_sintetico"]["itens_raiz"][0]
    assert row["custo_parcial"] == "142,70"
    closure = out["meta"]["performance"]["line_certainty_closure_after_physical_index"]
    assert closure["rounds"][0]["local_line_cascade_candidates"] >= 1
    assert any(r.get("reason") in {"local_line_neighborhood_cascade_repair", "math_expected_value_found_near_same_codigo_banco"} and r.get("field") == "custo_parcial" for r in closure["repairs"])
    assert "documento_enriquecimento" in out
    assert out["documento_evidencias"]["cascade_repairs"]["applied_repairs"]


def test_v47_math_expected_value_is_not_written_from_memory_section_price_context(tmp_path: Path):
    pdf = _write_pdf(tmp_path / "memoria.pdf", ["ANEXO 2 - MEMÓRIA DE CÁLCULO", "1.1 89446 SINAPI TUBO PVC ESGOTO m 10,00 14,27 142,70"])
    out = json.loads(run_core_extraction_accuracy_flow_file_json(str(pdf), json.dumps(_budget_missing_partial()), json.dumps({"ranges": {"budget": [1, 1], "compositions": [1, 1]}, "accuracy_profile": {"max_closure_rounds": 5}})))
    row = out["orcamento_sintetico"]["itens_raiz"][0]
    assert row["custo_parcial"] == ""
    closure = out["meta"]["performance"]["line_certainty_closure_after_physical_index"]
    rejected = closure["local_line_cascade_repair"].get("rejected") or []
    assert any(r.get("reason") in {"expected_value_found_but_section_policy_forbids_field", "section_policy_forbids_public_write", "math_expected_ambiguous_single_token_in_line"} for r in rejected)


def test_v47_composition_total_closes_in_cascade_and_outputs_lovable_contracts(tmp_path: Path):
    pdf = _write_pdf(tmp_path / "comp.pdf", ["ANEXO 3 - COMPOSIÇÕES ANALÍTICAS", "Composição 89446 SINAPI TUBO PVC ESGOTO m 1,0000000 14,27 14,27"])
    out = json.loads(run_core_extraction_accuracy_flow_file_json(str(pdf), json.dumps(_composition_missing_total()), json.dumps({"ranges": {"compositions": [1, 1]}, "accuracy_profile": {"max_closure_rounds": 5}})))
    principal = out["composicoes"]["sinapi_like"]["principais"]["89446|SINAPI"]["principal"]
    assert principal["total"] == "14,27"
    assert out["analise_orcamentaria"]["outputs_contract"]["enrichment_document_path"] == "documento_enriquecimento"
    assert out["documento_correcao"]["manual_consumo_lovable_resumo"]["documento_evidencias"].startswith("provas") and "base_config" in out["documento_correcao"]["manual_consumo_lovable_resumo"]["documento_enriquecimento"]


def test_v47_output_organizer_is_safe_with_minimal_reports():
    final = {"documento_correcao": {}, "analise_orcamentaria": {}}
    organize_lovable_output_documents(final, {"summary": {"total_rows": 0, "closed_100": 0}})
    assert final["documento_evidencias"]["source_of_truth_policy"]["primary"][:2] == ["orcamento_sintetico", "composicoes_analiticas"]
    assert final["analise_orcamentaria"]["outputs_contract"]["correction_document_path"] == "documento_correcao"
