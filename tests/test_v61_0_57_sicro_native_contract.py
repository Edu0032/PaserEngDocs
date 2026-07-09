from app.core.output_compact import prune_runtime_only_fields, refresh_quality_gate_after_repairs


def _sample_result():
    return {
        "status": "ok",
        "orcamento_sintetico": {"itens_raiz": []},
        "composicoes": {
            "principais": {
                "5503041|SICRO": {
                    "item": "3.1.5",
                    "principal": {
                        "codigo": "5503041",
                        "banco": "SICRO",
                        "servico": "Compactação de aterros a 100% do Proctor intermediário",
                        "unidade": "m³",
                        "quantidade": "1,0000000",
                        "custo_unitario": "6,05",
                        "custo_total": "6,05",
                        # pollution that must not survive the public contract
                        "descricao": "Compactação de aterros a 100% do Proctor intermediário",
                        "und": "m³",
                        "quant": "1",
                        "valor_unit": "6,05",
                        "total": "6,05",
                        "banco_coluna": "SICRO",
                        "banco_canonico": "SICRO",
                    },
                    "composicoes_auxiliares": [],
                    "insumos": [],
                    "detalhes": {
                        "sicro": {
                            "secoes": {
                                "D": {
                                    "nome": "Atividades Auxiliares",
                                    "linhas": [
                                        {
                                            "codigo": "1107892",
                                            "banco": "SICRO",
                                            "descricao": "Auxiliar D poluída",
                                            "atividade_auxiliar": "Compactação auxiliar",
                                            "unidade": "m³",
                                            "und": "m³",
                                            "quantidade": "0,5000",
                                            "quant": "0,5",
                                            "preco_unitario": "10,00",
                                            "valor_unit": "10,00",
                                            "custo_horario": "5,00",
                                            "total": "5,00",
                                            "banco_canonico": "SICRO",
                                            "detalhes": {"debug": True},
                                        }
                                    ],
                                }
                            },
                            "resumos": {"custo_total": "6,05"},
                            "validacao": {"ok": True},
                        }
                    },
                }
            },
            "auxiliares_globais": {},
        },
        "documento_correcao": {"resumo": {"total_registros_com_erro": 0, "total_divergencias_matematicas": 0}},
    }


def test_sicro_public_contract_uses_native_shape_without_sinapi_aliases():
    result = prune_runtime_only_fields(_sample_result())
    block = result["composicoes"]["sicro"]["principais"]["5503041|SICRO"]
    principal = block["principal"]

    assert "secoes" in block
    assert "sicro" not in block
    assert "detalhes" not in block
    assert "composicoes_auxiliares" not in block
    assert "insumos" not in block

    for field in ("descricao", "und", "quant", "valor_unit", "total", "banco_coluna", "banco_canonico", "natureza", "tipo"):
        assert field not in principal

    assert principal == {
        "codigo": "5503041",
        "banco": "SICRO",
        "servico": "Compactação de aterros a 100% do Proctor intermediário",
        "unidade": "m³",
        "quantidade": "1,0000000",
        "custo_unitario": "6,05",
        "custo_total": "6,05",
    }


def test_sicro_section_d_exposes_auxiliary_reference_without_generic_aliases():
    result = prune_runtime_only_fields(_sample_result())
    row = result["composicoes"]["sicro"]["principais"]["5503041|SICRO"]["secoes"]["D"]["linhas"][0]

    assert row["atividade_auxiliar"] == "Compactação auxiliar"
    assert row["unidade"] == "m³"
    assert row["quantidade"] == "0,5000"
    assert row["preco_unitario"] == "10,00"
    assert row["custo"] == "5,00"
    assert row["referencia"]["chave"] == "1107892|SICRO"
    assert row["referencia"]["tipo"] == "composicao_auxiliar_sicro"
    for field in ("descricao", "und", "quant", "valor_unit", "total", "banco_coluna", "banco_canonico", "detalhes"):
        assert field not in row


def test_quality_gate_accepts_clean_native_sicro_contract():
    result = prune_runtime_only_fields(_sample_result())
    gate = refresh_quality_gate_after_repairs(result)
    assert gate["ok"] is True
    assert gate["issues"] == []

from app.parser.sicro_native_bridge import merge_sicro_native_into_composicoes
from app.core.schemas import Composicoes, BlocoComposicao, LinhaComposicao


def test_sicro_native_bridge_does_not_inherit_budget_item_when_native_has_no_item():
    comp = Composicoes(
        principais={
            "5503041|SICRO": BlocoComposicao(
                item="3.1.5",
                principal=LinhaComposicao(codigo="5503041", banco="SICRO", descricao="Legacy", und="m³", quant=1, valor_unit=6.05, total=6.05),
            )
        },
        auxiliares_globais={},
    )
    native_payload = {
        "ok": True,
        "result": {"metadata": {"total_composicoes": 1}},
        "clean_result": {
            "composicoes": [
                {
                    "principal": {
                        "codigo": "5503041",
                        "banco": "SICRO",
                        "servico": "Compactação de aterros",
                        "unidade": "m³",
                        "quantidade": "1,0000000",
                        "custo_unitario": "6,05",
                        "custo_total": "6,05",
                    },
                    "secoes": {},
                    "validacao": {"ok": True},
                }
            ]
        },
    }
    merged, audit = merge_sicro_native_into_composicoes(comp, native_payload)
    assert "5503041|SICRO" not in merged.principais
    assert "5503041|SICRO" in merged.auxiliares_globais
    assert merged.auxiliares_globais["5503041|SICRO"].item == ""
