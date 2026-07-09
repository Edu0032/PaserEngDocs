from __future__ import annotations

from app.parser.line_certainty_closure import run_line_certainty_closure_engine


def test_closure_cross_repairs_budget_and_composition_fields():
    final = {
        "orcamento_sintetico": {
            "itens_raiz": [
                {
                    "tipo": "item",
                    "item": "1.1.1",
                    "codigo": "74209/001",
                    "fonte": "SINAPI",
                    "especificacao": "",
                    "und": "",
                    "quant": "2,00",
                    "custo_unitario_com_bdi": "",
                    "custo_parcial": "1.268,32",
                    "filhos": [],
                }
            ]
        },
        "composicoes": {
            "sinapi_like": {
                "principais": {
                    "74209/001|SINAPI": {
                        "item": "1.1.1",
                        "principal": {
                            "codigo": "74209/001",
                            "banco": "SINAPI",
                            "descricao": "PLACA DE OBRA EM CHAPA DE ACO GALVANIZADO",
                            "und": "m²",
                            "quant": "1,0000000",
                            "valor_unit": "634,16",
                            "total": "634,16",
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
        "meta": {"performance": {}},
    }
    out, report = run_line_certainty_closure_engine(final, apply=True)
    item = out["orcamento_sintetico"]["itens_raiz"][0]
    assert item["especificacao"] == "PLACA DE OBRA EM CHAPA DE ACO GALVANIZADO"
    assert item["und"] == "m²"
    assert item["custo_unitario_com_bdi"] == "634,16"
    assert report["summary"]["repairs_applied"] >= 3
    assert out["documento_correcao"]["line_certainty_closure"]["summary"]["total_rows"] >= 2


def test_closure_uses_aux_global_definition_but_preserves_context_quantity():
    final = {
        "orcamento_sintetico": {"itens_raiz": []},
        "composicoes": {
            "sinapi_like": {
                "principais": {
                    "12345|SINAPI": {
                        "principal": {"codigo": "12345", "banco": "SINAPI", "descricao": "SERVIÇO PRINCIPAL", "und": "UN", "quant": "1,0000000", "valor_unit": "12,25", "total": "12,25"},
                        "composicoes_auxiliares": [
                            {"codigo": "88267", "banco": "SINAPI", "descricao": "", "und": "", "quant": "0,5000000", "valor_unit": "", "total": ""}
                        ],
                        "insumos": [],
                    }
                },
                "auxiliares_globais": {
                    "88267|SINAPI": {
                        "principal": {"codigo": "88267", "banco": "SINAPI", "descricao": "ENCANADOR COM ENCARGOS COMPLEMENTARES", "und": "H", "quant": "1,0000000", "valor_unit": "24,50", "total": "24,50"},
                        "composicoes_auxiliares": [],
                        "insumos": [],
                    }
                },
            },
            "sicro": {"principais": {}, "auxiliares_globais": {}},
        },
        "documento_correcao": {"resumo": {}},
        "validacao": {"ocorrencias": []},
        "meta": {"performance": {}},
    }
    out, _ = run_line_certainty_closure_engine(final, apply=True)
    aux = out["composicoes"]["sinapi_like"]["principais"]["12345|SINAPI"]["composicoes_auxiliares"][0]
    assert aux["descricao"] == "ENCANADOR COM ENCARGOS COMPLEMENTARES"
    assert aux["und"] == "H"
    assert aux["valor_unit"] == "24,50"
    assert aux["quant"] == "0,5000000"  # quantidade contextual da principal, não da global
    assert aux["total"] == ""  # v61.0.40: math-only expectation is not written publicly
    assert aux["_calc"]["math_only_expectations"][0]["expected_value"] == "12,25"


def test_closure_enforces_sicro_collections_without_sinapi_validation():
    final = {
        "orcamento_sintetico": {"itens_raiz": []},
        "composicoes": {
            "sinapi_like": {"principais": {}, "auxiliares_globais": {}},
            "sicro": {
                "principais": {
                    "5503041|SICRO": {
                        "item": "",
                        "principal": {"codigo": "5503041", "banco": "SICRO3", "descricao": "Compactação", "und": "m³", "quant": "1,0000000", "valor_unit": "6,05", "total": "6,05"},
                        "sicro": {"secoes": {"A": {"linhas": [{"codigo": "E1", "banco": "SICRO", "equipamento": "Rolo"}]}}},
                    }
                },
                "auxiliares_globais": {},
            },
        },
        "documento_correcao": {"resumo": {}},
        "validacao": {"ocorrencias": []},
        "meta": {"performance": {}},
    }
    out, report = run_line_certainty_closure_engine(final, apply=True)
    assert "5503041|SICRO" not in out["composicoes"]["sicro"]["principais"]
    assert "5503041|SICRO" in out["composicoes"]["sicro"]["auxiliares_globais"]
    assert report["sicro_collection_enforcer"]["summary"]["moved"] == 1
    assert report["summary"]["sicro_issues"] == 0  # v61.0.42 leaves A-F contracts to the native sicro_only engine
    assert report["sicro_native_audit_bridge"]["mode"] == "native_sicro_only_engine_is_authoritative"
    assert any(w.get("tipo") == "sicro_collection_enforced" for w in out["documento_correcao"].get("warnings", []))


def test_closure_creates_deep_area_sweep_targets_for_unclosed_fields():
    final = {
        "orcamento_sintetico": {"itens_raiz": []},
        "composicoes": {
            "sinapi_like": {
                "principais": {
                    "89446|SINAPI": {
                        "pagina_inicio": 29,
                        "principal": {"codigo": "89446", "banco": "SINAPI", "descricao": "TUBO", "und": "", "quant": "", "valor_unit": "", "total": ""},
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
        "meta": {"performance": {}},
    }
    _out, report = run_line_certainty_closure_engine(final, apply=True)
    targets = report.get("deep_area_sweep_targets") or []
    assert any(t.get("codigo") == "89446" and t.get("field") in {"und", "quant", "valor_unit", "total"} for t in targets)


def test_workers_collect_line_certainty_targets():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for worker in [root / "parser_browser/browser/pyodide/pyodide-parser-worker.js", root / "parser_browser/browser/demo/pyodide/pyodide-parser-worker.js"]:
        text = worker.read_text(encoding="utf-8")
        assert "function addTargetsFromLineCertaintyClosure" in text
        assert "line_certainty_closure_engine" in text
        assert "line_certainty_target: true" in text
        assert "addTargetsFromLineCertaintyClosure(targets, finalResult)" in text
