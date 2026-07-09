from __future__ import annotations

from app.core.output_compact import prune_runtime_only_fields
from app.parser.physical_numeric_tail_recovery import apply_physical_numeric_tail_recovery


class FakePdfSession:
    page_count = 30

    def get_page_text(self, page_no: int, *, engine: str = "auto") -> str:
        assert page_no == 24
        return """
 4.5.2 Código Banco Descrição Und Quant. Valor Unit Total
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
MO sem LS => 3,70 LS => 4,22 MO com LS => 7,92
 4.5.3 Código Banco Descrição Und Quant. Valor Unit Total
"""


def _sample_result():
    return {
        "status": "ok",
        "orcamento_sintetico": {"itens_raiz": []},
        "composicoes": {
            "principais": {
                "93391|SINAPI": {
                    "item": "4.5.2",
                    "pagina_inicio": 24,
                    "pagina_fim": 24,
                    "paginas": [24],
                    "principal": {
                        "codigo": "93391",
                        "banco": "SINAPI",
                        "descricao": "REVESTIMENTO CERÂMICO PARA PISO",
                        "und": "M²",
                        "quant": "1",
                        "valor_unit": "69,88",
                        "total": "69,88",
                    },
                    "composicoes_auxiliares": [
                        {"codigo": "88256", "banco": "SINAPI", "descricao": "AZULEJISTA OU LADRILHISTA COM ENCARGOS COMPLEMENTARES", "und": "H", "quant": "0,2411", "valor_unit": "31,6", "total": "7,61"},
                        {"codigo": "88316", "banco": "SINAPI", "descricao": "SERVENTE COM ENCARGOS COMPLEMENTARES", "und": "H", "quant": "0,129", "valor_unit": "24,36", "total": "3,14"},
                    ],
                    "insumos": [
                        {"codigo": "00001381", "banco": "SINAPI", "descricao": "ARGAMASSA COLANTE AC I PARA CERAMICAS", "und": "KG", "quant": "9,1325", "valor_unit": "1,08", "total": "9,86"},
                        {"codigo": "00034357", "banco": "SINAPI", "descricao": "REJUNTE CIMENTICIO, QUALQUER COR", "und": "KG", "quant": "0,241", "valor_unit": "6,34", "total": "1,52"},
                        {"codigo": "00001297", "banco": "SINAPI", "descricao": "PISO EM CERAMICA ESMALTADA, COMERCIAL (PADRAO POPULAR), PEI MAIOR OU IGUAL", "und": ""},
                    ],
                    "detalhes": {
                        "math_status": {"status": "component_sum_lower_than_principal", "principal_total": 69.88, "component_sum": 22.13, "delta": 47.75, "missing_component_totals": 1},
                    },
                }
            },
            "auxiliares_globais": {},
        },
    }


def test_v61_0_60_recovers_missing_numeric_tail_from_same_physical_block():
    result, report = apply_physical_numeric_tail_recovery(_sample_result(), pdf_session=FakePdfSession())
    assert report["patches_applied"] >= 8
    block = result["composicoes"]["principais"]["93391|SINAPI"]
    principal = block["principal"]
    assert principal["und"] == "m²"
    assert principal["quant"] == "1,0000000"
    assert principal["valor_unit"] == "69,88"
    aux = block["composicoes_auxiliares"][0]
    assert aux["quant"] == "0,2411000"
    assert aux["valor_unit"] == "31,60"
    insumo = block["insumos"][2]
    assert insumo["und"] == "m²"
    assert insumo["quant"] == "1,0571000"
    assert insumo["valor_unit"] == "45,18"
    assert insumo["total"] == "47,75"
    assert "A 3, FORMATO MENOR OU IGUAL A 2025 CM2" in insumo["descricao"]
    assert block["detalhes"]["math_status"]["status"] == "ok"


def test_v61_0_60_quality_gate_blocks_unrecovered_missing_financial_tail():
    cleaned = prune_runtime_only_fields(_sample_result())
    gate = cleaned["auditoria_final"]["quality_gate"]
    assert gate["ok"] is False
    assert cleaned["status"] == "quality_gate_failed"
    assert any(issue["code"] == "sinapi_like_public_numeric_missing" for issue in gate["issues"])


def test_v61_0_60_quality_gate_allows_recovered_physical_tail():
    result, _ = apply_physical_numeric_tail_recovery(_sample_result(), pdf_session=FakePdfSession())
    cleaned = prune_runtime_only_fields(result)
    gate = cleaned["auditoria_final"]["quality_gate"]
    assert gate["ok"] is True
    block = (cleaned["composicoes"].get("principais") or cleaned["composicoes"]["sinapi_like"]["principais"])["93391|SINAPI"]
    assert block["insumos"][2]["quant"] == "1,0571000"
    assert block["insumos"][2]["total"] == "47,75"
