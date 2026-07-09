from __future__ import annotations

from app.core.base_rules import header_cfg, resolve_header_cells
from app.core.numeric_fidelity import numeric_source
from app.core.output_compact import prune_runtime_only_fields, refresh_quality_gate_after_repairs
from app.parser.composition_principal_cascade_repair import apply_composition_principal_cascade_repair
from app.parser.compositions import _DEFAULT_COMP_HEADER_ALIASES, _make_line


def test_v61_0_59_header_resolver_does_not_map_un_inside_valor_unit():
    cfg = header_cfg(
        {},
        key="composition_table_headers",
        default_aliases=_DEFAULT_COMP_HEADER_ALIASES,
        default_required=["codigo", "banco", "descricao"],
        default_similarity=0.82,
    )
    cells = ["CÓDIGO", "BANCO", "DESCRIÇÃO", "Tipo", "Und", "Quant.", "Valor Unit", "Total"]
    info = resolve_header_cells(cells, cfg)
    assert info["mapping"]["und"] == 4
    assert info["mapping"]["quant"] == 5
    assert info["mapping"]["valor_unit"] == 6
    assert info["mapping"]["total"] == 7


def test_v61_0_59_composition_tail_keeps_pdf_text_for_valor_unit_not_quant():
    cells = [
        "Composição",
        "93391",
        "SINAPI",
        "REVESTIMENTO CERÂMICO PARA PISO",
        "",
        "m²",
        "1,0000000",
        "69,88",
        "69,88",
    ]
    line, key = _make_line(cells, kind="COMPOSICAO")
    assert key == "93391|SINAPI"
    assert line.quant == 1.0
    assert line.valor_unit == 69.88
    assert line.total == 69.88
    assert line.detalhes["numeric_source"]["quant"]["source_text"] == "1,0000000"
    assert line.detalhes["numeric_source"]["valor_unit"]["source_text"] == "69,88"
    assert line.detalhes["numeric_source"]["total"]["source_text"] == "69,88"


def test_v61_0_59_public_output_reapplies_pdf_numeric_source_after_bad_mutation():
    result = {
        "status": "ok",
        "orcamento_sintetico": {
            "itens_raiz": [
                {
                    "tipo": "item",
                    "item": "4.5.2",
                    "codigo": "93391",
                    "fonte": "SINAPI",
                    "especificacao": "REVESTIMENTO CERÂMICO",
                    "und": "m²",
                    "quant": "128,53",
                    # simulated bad late mutation from recalculation
                    "custo_unitario_sem_bdi": "69,91",
                    "custo_unitario_com_bdi": "85,03",
                    "custo_parcial": "10.928,91",
                    "detalhes": {
                        "numeric_source": {
                            "quant": numeric_source("128,53"),
                            "custo_unitario_sem_bdi": numeric_source("69,88"),
                            "custo_unitario_com_bdi": numeric_source("84,99"),
                            "custo_parcial": numeric_source("10.923,76"),
                        }
                    },
                }
            ]
        },
        "composicoes": {
            "principais": {
                "93391|SINAPI": {
                    "item": "4.5.2",
                    "principal": {
                        "codigo": "93391",
                        "banco": "SINAPI",
                        "descricao": "REVESTIMENTO CERÂMICO",
                        "und": "m²",
                        "quant": 1.0,
                        # simulated bad late mutation from component sum
                        "valor_unit": 69.91,
                        "total": 69.91,
                        "detalhes": {
                            "numeric_source": {
                                "quant": numeric_source("1,0000000"),
                                "valor_unit": numeric_source("69,88"),
                                "total": numeric_source("69,88"),
                            }
                        },
                    },
                    "composicoes_auxiliares": [
                        {
                            "codigo": "88256",
                            "banco": "SINAPI",
                            "descricao": "AZULEJISTA",
                            "und": "H",
                            "quant": 0.2411,
                            "valor_unit": 0.2411,
                            "total": 7.61,
                            "detalhes": {
                                "numeric_source": {
                                    "quant": numeric_source("0,2411000"),
                                    "valor_unit": numeric_source("31,60"),
                                    "total": numeric_source("7,61"),
                                }
                            },
                        }
                    ],
                    "insumos": [
                        {
                            "codigo": "00001297",
                            "banco": "SINAPI",
                            "descricao": "PISO CERÂMICO",
                            "und": "m²",
                            "quant": 1.0571,
                            "valor_unit": 45.18,
                            "total": 47.75,
                            "detalhes": {
                                "numeric_source": {
                                    "quant": numeric_source("1,0571000"),
                                    "valor_unit": numeric_source("45,18"),
                                    "total": numeric_source("47,75"),
                                }
                            },
                        }
                    ],
                }
            },
            "auxiliares_globais": {},
        },
    }
    cleaned = prune_runtime_only_fields(result)
    budget = cleaned["orcamento_sintetico"]["itens_raiz"][0]
    assert budget["custo_unitario_sem_bdi"] == "69,88"
    assert budget["custo_unitario_com_bdi"] == "84,99"
    assert budget["custo_parcial"] == "10.923,76"

    block = cleaned["composicoes"]["sinapi_like"]["principais"]["93391|SINAPI"]
    assert block["principal"]["quant"] == "1,0000000"
    assert block["principal"]["valor_unit"] == "69,88"
    assert block["principal"]["total"] == "69,88"
    aux = block["composicoes_auxiliares"][0]
    assert aux["quant"] == "0,2411000"
    assert aux["valor_unit"] == "31,60"
    assert aux["total"] == "7,61"
    insumo = block["insumos"][0]
    assert insumo["quant"] == "1,0571000"
    assert insumo["valor_unit"] == "45,18"
    assert insumo["total"] == "47,75"

    dumped = str(cleaned)
    assert "69,91" not in dumped
    assert "85,03" not in dumped
    assert "10.928,91" not in dumped
    assert refresh_quality_gate_after_repairs(cleaned)["ok"] is True


def test_v61_0_59_component_sum_is_audit_only_when_pdf_principal_is_missing():
    result = {
        "orcamento_sintetico": {
            "itens_raiz": [
                {"tipo": "item", "item": "4.5.2", "codigo": "93391", "fonte": "SINAPI", "und": "m²", "quant": "128,53", "custo_unitario_sem_bdi": "69,88"}
            ]
        },
        "composicoes": {
            "principais": {
                "93391|SINAPI": {
                    "item": "4.5.2",
                    "principal": {"codigo": "93391", "banco": "SINAPI", "descricao": "REVESTIMENTO", "und": "m²"},
                    "composicoes_auxiliares": [
                        {"codigo": "A", "banco": "SINAPI", "descricao": "A", "und": "H", "quant": "1", "valor_unit": "22,16", "total": "22,16"},
                    ],
                    "insumos": [
                        {"codigo": "B", "banco": "SINAPI", "descricao": "B", "und": "m²", "quant": "1", "valor_unit": "47,75", "total": "47,75"},
                    ],
                }
            },
            "auxiliares_globais": {},
        },
    }
    out, report = apply_composition_principal_cascade_repair(result)
    principal = out["composicoes"]["principais"]["93391|SINAPI"]["principal"]
    assert "valor_unit" not in principal
    assert "total" not in principal
    assert "quant" not in principal
    assert report["summary"]["fields_repaired"] == 0
    assert report["summary"]["blocked"] >= 1
    assert out["composicoes"]["principais"]["93391|SINAPI"]["detalhes"]["_calc"]["component_sum_reported"] == "69,91"
