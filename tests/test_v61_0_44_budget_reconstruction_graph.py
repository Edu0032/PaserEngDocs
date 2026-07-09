from __future__ import annotations

import json
from pathlib import Path

import fitz

from app.browser.pyodide_entry import enrich_physical_evidence_index_file_json
from app.parser.budget_reconstruction_graph import build_budget_reconstruction_graph
from app.parser.budget_puzzle_resolver import build_budget_puzzle_context
from app.parser.composition_cost_reconciliation import build_composition_cost_reconciliation
from app.parser.budget_hierarchy_reconciliation import build_budget_hierarchy_reconciliation
from app.parser.entity_relation_graph import build_entity_relation_graph


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


def _final_v44() -> dict:
    return {
        "orcamento_sintetico": {
            "itens_raiz": [
                {
                    "item": "1",
                    "descricao": "SERVIÇOS",
                    "custo_total": "142,70",
                    "filhos": [
                        {
                            "item": "1.1",
                            "codigo": "89446",
                            "fonte": "SINAPI",
                            "especificacao": "TUBO PVC ESGOTO",
                            "und": "m",
                            "quant": "10,0000",
                            "custo_unitario_com_bdi": "14,27",
                            "custo_parcial": "142,70",
                        }
                    ],
                }
            ]
        },
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
                        "composicoes_auxiliares": [
                            {
                                "codigo": "88267",
                                "banco": "SINAPI",
                                "descricao": "",
                                "und": "h",
                                "quant": "0,1200000",
                                "valor_unit": "22,45",
                                "total": "2,69",
                            },
                            {
                                "codigo": "AUX-SEM-GLOBAL",
                                "banco": "SINAPI",
                                "descricao": "AUXILIAR REFERENCIADA SEM GLOBAL",
                                "und": "h",
                                "quant": "1,0000000",
                                "valor_unit": "11,58",
                                "total": "11,58",
                            },
                        ],
                        "insumos": [],
                    }
                },
                "auxiliares_globais": {
                    "88267|SINAPI": {
                        "principal": {
                            "codigo": "88267",
                            "banco": "SINAPI",
                            "descricao": "ENCANADOR COM ENCARGOS COMPLEMENTARES",
                            "und": "h",
                            "quant": "1,0000000",
                            "valor_unit": "22,45",
                            "total": "22,45",
                        }
                    }
                },
            },
            "sicro": {"principais": {}, "auxiliares_globais": {}},
        },
        "documento_correcao": {"resumo": {}},
        "validacao": {"ocorrencias": []},
        "meta": {"performance": {}, "input_metadata": {"ranges": {"budget": [1, 1], "compositions": [1, 1]}}},
    }


def test_v44_reconstruction_graph_links_budget_main_and_missing_global_auxiliary():
    final = _final_v44()
    entity_graph = build_entity_relation_graph(final)
    graph = build_budget_reconstruction_graph(final, entity_graph, {})
    assert graph["summary"]["chains"] == 1
    assert graph["summary"]["internal_rows"] == 2
    assert graph["summary"]["global_auxiliary_matches"] == 1
    assert graph["summary"]["missing_global_auxiliaries"] == 1
    issue = graph["missing_global_auxiliaries"][0]
    assert issue["code"] == "contextual_auxiliary_without_global_expansion"
    assert issue["severity"] == "warning"


def test_v44_composition_cost_reconciliation_validates_component_sum():
    report = build_composition_cost_reconciliation(_final_v44())
    row = [r for r in report["rows"] if r["block_key"] == "89446|SINAPI"][0]
    assert row["status"] == "ok"
    assert row["component_total_sum"] == 14.27
    assert report["summary"]["mismatch"] == 0


def test_v44_budget_hierarchy_reconciliation_validates_parent_subtotal():
    report = build_budget_hierarchy_reconciliation(_final_v44())
    assert report["summary"]["checked_parent_nodes"] == 1
    assert report["summary"]["ok"] == 1
    assert report["rows"][0]["child_sum"] == 142.7


def test_v44_budget_puzzle_context_contains_chain_reconciliations():
    ctx = build_budget_puzzle_context(_final_v44(), {}, [])
    assert ctx["summary"]["chains"] == 1
    assert ctx["summary"]["missing_global_auxiliaries"] == 1
    assert ctx["summary"]["composition_cost_mismatches"] == 0
    assert "budget_reconstruction_graph" in ctx
    assert "composition_cost_reconciliation" in ctx
    assert "budget_hierarchy_reconciliation" in ctx


def test_v44_mini_flow_exports_chain_analysis_and_correction_sections(tmp_path: Path):
    pdf = _write_pdf(
        tmp_path / "doc.pdf",
        ["Memorial: Código 89446 SINAPI - TUBO PVC ESGOTO - Unidade m - Valor 14,27 - Total 14,27"],
    )
    out = json.loads(
        enrich_physical_evidence_index_file_json(
            str(pdf),
            json.dumps(_final_v44()),
            json.dumps({"ranges": {"budget": [1, 1], "compositions": [1, 1]}, "accuracy_profile": {"max_closure_rounds": 5}}),
        )
    )
    assert out.get("status") != "error"
    from app.config.version import CURRENT_RELEASE
    assert out["analise_orcamentaria"]["version"] == CURRENT_RELEASE
    chain_summary = out["analise_orcamentaria"]["budget_reconstruction"]["summary"]
    assert chain_summary["chains"] == 1
    assert chain_summary["missing_global_auxiliaries"] == 1
    doc = out["documento_correcao"]
    assert "budget_reconstruction_graph" in doc
    assert "composition_cost_reconciliation" in doc
    assert "budget_hierarchy_reconciliation" in doc
    assert "entity_chain_conflict_resolver" in doc
    warning_types = {w.get("tipo") for w in doc.get("warnings", []) if isinstance(w, dict)}
    assert "contextual_auxiliary_without_global_expansion" in warning_types
