from app.core.output_compact import prune_runtime_only_fields, refresh_quality_gate_after_repairs


def test_sicro_native_payload_wins_over_generic_cascade_mutation():
    result = {
        "status": "ok",
        "orcamento_sintetico": {"itens_raiz": []},
        "composicoes": {
            "principais": {
                "2003373|SICRO": {
                    "item": "3.3.1",
                    # polluted/generic principal that must not win
                    "principal": {
                        "codigo": "2003373",
                        "banco": "SICRO3",
                        "servico": "Meio-fio",
                        "unidade": "m",
                        "quantidade": "1,0000000",
                        "custo_unitario": 237361202575.61,
                        "custo_total": 237361202575.61,
                        "valor_unit": 237361202575.61,
                        "total": 237361202575.61,
                    },
                    "detalhes": {
                        "sicro": {
                            "principal": {
                                "codigo": "2003373",
                                "banco": "SICRO3",
                                "servico": "Meio-fio de concreto - MFC 03 - areia e brita comerciais - fôrma de madeira",
                                "unidade": "m",
                                "quantidade": "1,0000000",
                                "custo_unitario": "71,47",
                                "custo_total": "71,47",
                            },
                            "secoes": {
                                "D": {
                                    "nome": "Atividades Auxiliares",
                                    "linhas": [
                                        {
                                            "codigo": "1107892",
                                            "banco": "SICRO3",
                                            "atividade_auxiliar": "Concreto fck = 20 MPa",
                                            "unidade": "m³",
                                            "quantidade": "0,0420000",
                                            "preco_unitario": "678,8500",
                                            "custo": "28,5117",
                                            # generic/cascade pollution that must not be exported
                                            "valor_unit": 5648185100498.04,
                                            "total": 237223774220.92,
                                            "_cascaded_from": "1107892|SICRO",
                                        }
                                    ],
                                    "total_reportado": "71,4652",
                                }
                            },
                            "resumos": {"custo_total_atividades_auxiliares": "71,4652", "valor_com_bdi": "86,92"},
                            "validacao": {"ok": True},
                        }
                    },
                    "sicro_section_totals": {"D": 237361202575.61},
                }
            },
            "auxiliares_globais": {},
        },
    }
    cleaned = prune_runtime_only_fields(result)
    block = cleaned["composicoes"]["sicro"]["principais"]["2003373|SICRO"]
    principal = block["principal"]
    assert principal["custo_unitario"] == "71,47"
    assert principal["custo_total"] == "71,47"
    assert "valor_unit" not in principal
    assert "total" not in principal
    assert "sicro_section_totals" not in block

    row = block["secoes"]["D"]["linhas"][0]
    assert row["preco_unitario"] == "678,8500"
    assert row["custo"] == "28,5117"
    assert row["referencia"]["relacao"] == "secao_D_referencia_auxiliar_sem_mutacao_no_python"
    assert "_cascaded_from" not in row
    assert "valor_unit" not in row
    assert "total" not in row
    gate = refresh_quality_gate_after_repairs(cleaned)
    assert gate["ok"] is True
    assert gate["issues"] == []


def test_sicro_public_contract_contains_no_float_values_after_output_cleanup():
    result = {
        "composicoes": {
            "principais": {
                "1107892|SICRO": {
                    "principal": {"codigo": "1107892", "banco": "SICRO3", "servico": "Aux", "unidade": "m³", "quantidade": "1,0000000", "custo_unitario": "678,85", "custo_total": "678,85"},
                    "detalhes": {"sicro": {"principal": {"codigo": "1107892", "banco": "SICRO3", "servico": "Aux", "unidade": "m³", "quantidade": "1,0000000", "custo_unitario": "678,85", "custo_total": "678,85"}, "secoes": {}, "validacao": {"ok": True}}},
                }
            },
            "auxiliares_globais": {},
        }
    }
    cleaned = prune_runtime_only_fields(result)
    import json
    dumped = json.dumps(cleaned.get("composicoes", {}).get("sicro", {}), ensure_ascii=False)
    assert "678.85" not in dumped
    assert "678,85" in dumped
