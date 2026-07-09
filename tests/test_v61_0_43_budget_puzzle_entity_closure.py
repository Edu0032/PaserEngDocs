from __future__ import annotations

import json
from pathlib import Path

import fitz

from app.browser.pyodide_entry import enrich_physical_evidence_index_file_json
from app.parser.entity_relation_graph import build_entity_relation_graph
from app.parser.physical_evidence_index import build_physical_evidence_index
from app.parser.budget_puzzle_resolver import build_budget_puzzle_context


def _write_pdf(path: Path, pages: list[list[str]]) -> Path:
    doc = fitz.open()
    for lines in pages:
        page = doc.new_page(width=842, height=595)
        y = 72
        for line in lines:
            page.insert_text((40, y), line, fontsize=10)
            y += 18
    doc.save(path)
    doc.close()
    return path


def _final_puzzle_missing_total() -> dict:
    return {
        "orcamento_sintetico": {
            "itens_raiz": [
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
                            }
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
        "meta": {"performance": {}, "input_metadata": {"ranges": {"compositions": [1, 1], "budget": [1, 1]}}},
    }


def test_v43_entity_relation_graph_treats_budget_as_puzzle():
    graph = build_entity_relation_graph(_final_puzzle_missing_total())
    assert graph["entity_count"] >= 4
    rel_types = {r.get("type") for r in graph["relations"]}
    assert "budget_main_composition" in rel_types
    assert "contextual_auxiliary_global" in rel_types
    assert graph["by_key"]["89446|SINAPI"]
    assert graph["by_key"]["88267|SINAPI"]


def test_v43_physical_index_scans_outside_known_intervals_as_raw_context(tmp_path: Path):
    pdf = _write_pdf(
        tmp_path / "doc.pdf",
        [
            ["Página de composição sem ocorrência útil"],
            ["Memorial: Código 89446 SINAPI - TUBO PVC ESGOTO - Unidade m - Valor 14,27 - Total 14,27"],
        ],
    )
    index = build_physical_evidence_index(str(pdf), _final_puzzle_missing_total(), {"ranges": {"compositions": [1, 1], "budget": [1, 1]}})
    assert index["status"] == "ok"
    assert index["source_zone_counts"].get("outside_known_intervals", 0) >= 1
    bucket = index["keys"]["89446|SINAPI"]
    assert bucket["occurrences"][0]["source_zone"] == "outside_known_intervals"
    assert bucket["fields"]["und"]["values"][0]["value"] == "m"


def test_v43_mini_flow_runs_puzzle_resolver_and_closes_from_raw_physical_evidence(tmp_path: Path):
    pdf = _write_pdf(
        tmp_path / "doc.pdf",
        [
            ["Página de composição sem ocorrência útil"],
            ["Memorial: Código 89446 SINAPI - TUBO PVC ESGOTO - Unidade m - Valor 14,27 - Total 14,27"],
        ],
    )
    out = json.loads(enrich_physical_evidence_index_file_json(str(pdf), json.dumps(_final_puzzle_missing_total()), json.dumps({"ranges": {"compositions": [1, 1], "budget": [1, 1]}, "accuracy_profile": {"max_closure_rounds": 5}})))
    assert out.get("status") != "error"
    principal = out["composicoes"]["sinapi_like"]["principais"]["89446|SINAPI"]["principal"]
    assert principal["total"] == "14,27"
    closure = out["meta"]["performance"]["line_certainty_closure_after_physical_index"]
    assert "budget_puzzle_resolver" in closure
    assert closure["budget_puzzle_resolver"]["summary"]["entities"] >= 4
    assert closure["budget_puzzle_resolver"]["summary"]["relations"] >= 2
    assert out["documento_correcao"]["budget_puzzle_resolver"]["summary"]["entities"] >= 4


def test_v43_budget_puzzle_context_builds_fragment_ownership_graph(tmp_path: Path):
    pdf = _write_pdf(tmp_path / "doc.pdf", [["89446 SINAPI TUBO PVC ESGOTO m 1,0000000 14,27 14,27"]])
    final = _final_puzzle_missing_total()
    physical = build_physical_evidence_index(str(pdf), final, {"ranges": {"compositions": [1, 1]}})
    context = build_budget_puzzle_context(final, physical, [])
    assert context["summary"]["entities"] >= 4
    assert context["summary"]["fragments"] >= 1
    assert context["fragment_ownership_graph"]["fragment_count"] >= 1
