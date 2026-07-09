from __future__ import annotations

from copy import deepcopy

from app.core.output_compact import refresh_quality_gate_after_repairs
from app.parser.budget_total_ownership import apply_budget_total_ownership_repair
from app.parser.lovable_policy import apply_lovable_consumption_policy
from app.parser.physical_numeric_tail_recovery import apply_physical_numeric_tail_recovery


class FakePdfSessionV62:
    page_count = 40

    def get_page_text(self, page_no: int, *, engine: str = "auto") -> str:
        if page_no == 24:
            return """
 4.5.2 CódigoBanco Descrição Tipo Und Quant. Valor Unit Total
Composição 93391 SINAPI REVESTIMENTO CERÂMICO PARA PISO COM PLACAS TIPO ESMALTADA PADRÃO PISO - PISOS m² 1,0000000 69,88 69,88
POPULAR DE DIMENSÕES 35X35 CM APLICADA EM AMBIENTES DE ÁREA MAIOR QUE 10 M2. AF_02/2023_PE
Composição Auxiliar 88256 SINAPI AZULEJISTA OU LADRILHISTA COM ENCARGOS COMPLEMENTARES Livro SINAPI: Cálculos e H 0,2411000 31,60 7,61
Parâmetros
Composição Auxiliar 88316 SINAPI SERVENTE COM ENCARGOS COMPLEMENTARES Livro SINAPI: Cálculos e H 0,1290000 24,36 3,14
Parâmetros
Insumo 00001381 SINAPI ARGAMASSA COLANTE AC I PARA CERAMICAS Material KG 9,1325000 1,08 9,86
Insumo 00034357 SINAPI REJUNTE CIMENTICIO, QUALQUER COR Material KG 0,2410000 6,34 1,52
Insumo 00001297 SINAPI PISO EM CERAMICA ESMALTADA, COMERCIAL (PADRAO POPULAR), PEI MAIOR OU IGUAL Material m² 1,0571000 45,18 47,75
A 3, FORMATO MENOR OU IGUAL A 2025 CM2
MO sem LS 3,70 LS => 4,22MO com LS => 7,92
=>
Valor do BDI 15,11 Valor com BDI => 84,99
=>
 4.5.3 CódigoBanco Descrição Tipo Und Quant. Valor Unit Total
"""
        if page_no in (29, 30):
            return """
 4.9.2 CódigoBanco Descrição Tipo Und Quant. Valor Unit Total
Composição 89446 SINAPI TUBO, PVC, SOLDÁVEL, DE 25MM, INSTALADO EM PRUMADA DE ÁGUA - FORNECIMENTO Instalações Prediais de M 1,0000000 5,47 5,47
E INSTALAÇÃO. AF_06/2022 Água Fria em PVC
Composição Auxiliar 88248 SINAPI AUXILIAR DE ENCANADOR OU BOMBEIRO HIDRÁULICO COM ENCARGOS Livro SINAPI: Cálculos e H 0,0195000 25,34 0,49
COMPLEMENTARES Parâmetros
Composição Auxiliar 88267 SINAPI ENCANADOR OU BOMBEIRO HIDRÁULICO COM ENCARGOS COMPLEMENTARES Livro SINAPI: Cálculos e H 0,0195000 31,03 0,60
Parâmetros
Insumo 00009868 SINAPI TUBO PVC, SOLDAVEL, DE 25 MM, AGUA FRIA (NBR-5648) Material M 1,0493000 4,17 4,37
Insumo 00038383 SINAPI LIXA D'AGUA EM FOLHA, COR PRETA, GRAO 100 Material UN 0,0045000 2,55 0,01
"""
        return ""


def _result_with_blockers():
    return {
        "status": "quality_gate_failed",
        "auditoria_final": {
            "quality_gate": {
                "ok": False,
                "issues": [
                    {"code": "sinapi_like_component_math_unclosed", "block": "93391|SINAPI", "severity": "blocking"},
                    {"code": "sinapi_like_public_numeric_missing", "block": "89446|SINAPI", "severity": "blocking"},
                ],
            }
        },
        "orcamento_sintetico": {
            "total": "698159,11",
            "itens_raiz": [
                {
                    "tipo": "meta",
                    "item": "1",
                    "descricao": "SERVIÇOS PRELIMINARES",
                    "filhos": [
                        {
                            "tipo": "submeta",
                            "item": "1.1",
                            "descricao": "PLACA DE OBRA",
                            "custo_total": "52.365,69",
                            "filhos": [
                                {"tipo": "item", "item": "1.1.1", "codigo": "74209/001", "fonte": "SINAPI", "custo_parcial": "3.804,96"}
                            ],
                        },
                        {"tipo": "submeta", "item": "1.2", "filhos": [{"tipo": "item", "item": "1.2.1", "codigo": "93207", "custo_parcial": "20.689,20"}, {"tipo": "item", "item": "1.2.2", "codigo": "93210", "custo_parcial": "7.036,31"}, {"tipo": "item", "item": "1.2.3", "codigo": "93212", "custo_parcial": "11.267,63"}, {"tipo": "item", "item": "1.2.4", "codigo": "41598", "custo_parcial": "2.963,96"}]},
                        {"tipo": "submeta", "item": "1.3", "filhos": [{"tipo": "item", "item": "1.3.1", "codigo": "00013244", "custo_parcial": "356,50"}, {"tipo": "item", "item": "1.3.2", "codigo": "COMP.JCO.3", "custo_parcial": "1.570,50"}]},
                        {"tipo": "submeta", "item": "1.4", "filhos": [{"tipo": "item", "item": "1.4.1", "codigo": "94296", "custo_parcial": "3.124,90"}, {"tipo": "item", "item": "1.4.2", "codigo": "101389", "custo_parcial": "1.551,73"}]},
                    ],
                }
            ],
        },
        "composicoes": {
            "principais": {
                "93391|SINAPI": {
                    "item": "4.5.2", "pagina_inicio": 24, "pagina_fim": 24, "paginas": [24],
                    "principal": {"codigo": "93391", "banco": "SINAPI", "descricao": "REVESTIMENTO", "und": "M²", "quant": "1", "valor_unit": "69,88", "total": "69,88"},
                    "composicoes_auxiliares": [
                        {"codigo": "88256", "banco": "SINAPI", "descricao": "AZULEJISTA", "und": "H", "quant": "0,2411", "valor_unit": "31,6", "total": "7,61"},
                        {"codigo": "88316", "banco": "SINAPI", "descricao": "SERVENTE", "und": "H", "quant": "0,129", "valor_unit": "24,36", "total": "3,14"},
                    ],
                    "insumos": [
                        {"codigo": "00001381", "banco": "SINAPI", "descricao": "ARGAMASSA", "und": "KG", "quant": "9,1325", "valor_unit": "1,08", "total": "9,86"},
                        {"codigo": "00034357", "banco": "SINAPI", "descricao": "REJUNTE", "und": "KG", "quant": "0,241", "valor_unit": "6,34", "total": "1,52"},
                        {"codigo": "00001297", "banco": "SINAPI", "descricao": "PISO EM CERAMICA ESMALTADA, COMERCIAL (PADRAO POPULAR), PEI MAIOR OU IGUAL", "und": ""},
                    ],
                    "detalhes": {"math_status": {"status": "component_sum_lower_than_principal", "principal_total": 69.88, "component_sum": 22.13, "delta": 47.75, "missing_component_totals": 1}},
                },
                "89446|SINAPI": {
                    "item": "4.9.2", "pagina_inicio": 29, "pagina_fim": 30, "paginas": [29, 30],
                    "principal": {"codigo": "89446", "banco": "SINAPI", "descricao": "TUBO, PVC, SOLDÁVEL", "und": "M"},
                    "composicoes_auxiliares": [
                        {"codigo": "88248", "banco": "SINAPI", "descricao": "AUXILIAR", "und": "H", "quant": "0,0195", "valor_unit": "25,34", "total": "0,49"},
                        {"codigo": "88267", "banco": "SINAPI", "descricao": "ENCANADOR", "und": "H", "quant": "0,0195", "valor_unit": "31,03", "total": "0,6"},
                    ],
                    "insumos": [
                        {"codigo": "00009868", "banco": "SINAPI", "descricao": "TUBO PVC", "und": "M", "quant": "1,0493", "valor_unit": "4,17", "total": "4,37"},
                        {"codigo": "00038383", "banco": "SINAPI", "descricao": "LIXA", "und": "UN", "quant": "0,0045", "valor_unit": "2,55", "total": "0,01"},
                    ],
                    "detalhes": {"math_status": {"status": "missing_values", "ok": False}},
                },
            },
            "auxiliares_globais": {},
        },
    }


def test_v61_0_63_mandatory_targeted_recovery_locks_and_closes_problem_blocks():
    data = _result_with_blockers()
    result, report = apply_physical_numeric_tail_recovery(data, pdf_session=FakePdfSessionV62(), options={"mandatory_targeted": True})
    assert report["target_blocks"] == ["89446|SINAPI", "93391|SINAPI"]
    assert report["blocks_scanned"] == 2
    assert report["blocking_unresolved"] == []
    block = result["composicoes"]["principais"]["93391|SINAPI"]
    assert block["insumos"][2]["und"] == "m²"
    assert block["insumos"][2]["quant"] == "1,0571000"
    assert block["insumos"][2]["valor_unit"] == "45,18"
    assert block["insumos"][2]["total"] == "47,75"
    assert block["detalhes"]["math_status"]["status"] == "ok"
    assert block["detalhes"]["math_status"]["missing_component_totals"] == 0
    assert block["detalhes"]["focused_composition_locking"]["all_rows_locked"] is True
    assert block["detalhes"]["focused_composition_locking"]["open_rows"] == 0
    block_89446 = result["composicoes"]["principais"]["89446|SINAPI"]
    assert block_89446["principal"]["quant"] == "1,0000000"
    assert block_89446["principal"]["valor_unit"] == "5,47"
    assert block_89446["principal"]["total"] == "5,47"


def test_v61_0_63_budget_total_ownership_moves_pdf_token_to_semantic_owner():
    result = _result_with_blockers()
    result, report = apply_budget_total_ownership_repair(result)
    root = result["orcamento_sintetico"]["itens_raiz"][0]
    assert report["patches_applied"] == 1
    assert root["custo_total"] == "52.365,69"
    assert "custo_total" not in root["filhos"][0]
    assert root["filhos"][0]["_audit"]["budget_total_ownership"][0]["action"] == "removed_wrong_owner_public_total"


def test_v61_0_63_final_policy_prevents_lovable_recalculation_contract():
    result = _result_with_blockers()
    result, _ = apply_physical_numeric_tail_recovery(result, pdf_session=FakePdfSessionV62(), options={"mandatory_targeted": True})
    result, _ = apply_budget_total_ownership_repair(result)
    apply_lovable_consumption_policy(result)
    gate = refresh_quality_gate_after_repairs(result)
    assert gate["ok"] is True or all(i.get("code") == "composition_family_split_missing" for i in gate.get("issues", []))
    policy = result["lovable_consumption_policy"]
    assert policy["do_not_recalculate_public_totals"] is True
    assert "overwrite_custo_parcial" in policy["forbidden_uses_of_math"]
