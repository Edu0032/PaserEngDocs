from __future__ import annotations

from app.core.output_compact import prune_runtime_only_fields
from app.parser.physical_numeric_tail_recovery import apply_physical_numeric_tail_recovery


class FakePdfSessionDetachedTail:
    page_count = 30

    def get_page_text(self, page_no: int, *, engine: str = "auto") -> str:
        assert page_no == 24
        # This simulates the extractor placing a wrapped description and the
        # numeric tail in a detached local context. The recovery must use the
        # known math delta only to select a physical token that is actually in
        # the PDF text, never to invent a value.
        return """
 4.5.2 Código Banco Descrição Und Quant. Valor Unit Total
Composição 93391 SINAPI REVESTIMENTO CERÂMICO PARA PISO COM PLACAS TIPO ESMALTADA PADRÃO PISO - PISOS m² 1,0000000 69,88 69,88
Composição Auxiliar 88256 SINAPI AZULEJISTA OU LADRILHISTA COM ENCARGOS COMPLEMENTARES Livro SINAPI: Cálculos e H 0,2411000 31,60 7,61
Composição Auxiliar 88316 SINAPI SERVENTE COM ENCARGOS COMPLEMENTARES Livro SINAPI: Cálculos e H 0,1290000 24,36 3,14
Insumo 00001381 SINAPI ARGAMASSA COLANTE AC I PARA CERAMICAS Material KG 9,1325000 1,08 9,86
Insumo 00034357 SINAPI REJUNTE CIMENTICIO, QUALQUER COR Material KG 0,2410000 6,34 1,52
Insumo 00001297 SINAPI PISO EM CERAMICA ESMALTADA, COMERCIAL (PADRAO POPULAR), PEI MAIOR OU IGUAL
A 3, FORMATO MENOR OU IGUAL A 2025 CM2 Material
m² 1,0571000 45,18 47,75
MO sem LS => 3,70 LS => 4,22 MO com LS => 7,92
 4.5.3 Código Banco Descrição Und Quant. Valor Unit Total
"""


def _problem_result():
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
                    "principal": {"codigo": "93391", "banco": "SINAPI", "descricao": "REVESTIMENTO", "und": "m²", "quant": "1,0000000", "valor_unit": "69,88", "total": "69,88"},
                    "composicoes_auxiliares": [
                        {"codigo": "88256", "banco": "SINAPI", "descricao": "AZULEJISTA", "und": "H", "quant": "0,2411000", "valor_unit": "31,60", "total": "7,61"},
                        {"codigo": "88316", "banco": "SINAPI", "descricao": "SERVENTE", "und": "H", "quant": "0,1290000", "valor_unit": "24,36", "total": "3,14"},
                    ],
                    "insumos": [
                        {"codigo": "00001381", "banco": "SINAPI", "descricao": "ARGAMASSA", "und": "KG", "quant": "9,1325000", "valor_unit": "1,08", "total": "9,86"},
                        {"codigo": "00034357", "banco": "SINAPI", "descricao": "REJUNTE", "und": "KG", "quant": "0,2410000", "valor_unit": "6,34", "total": "1,52"},
                        {"codigo": "00001297", "banco": "SINAPI", "descricao": "PISO EM CERAMICA ESMALTADA", "und": ""},
                    ],
                    "detalhes": {"math_status": {"status": "component_sum_lower_than_principal", "principal_total": 69.88, "component_sum": 22.13, "delta": 47.75, "missing_component_totals": 1}},
                }
            },
            "auxiliares_globais": {},
        },
    }


def test_v61_0_63_existing_recovery_uses_expected_value_as_physical_selector_only():
    result, report = apply_physical_numeric_tail_recovery(_problem_result(), pdf_session=FakePdfSessionDetachedTail())
    row = result["composicoes"]["principais"]["93391|SINAPI"]["insumos"][2]
    assert row["und"] == "m²"
    assert row["quant"] == "1,0571000"
    assert row["valor_unit"] == "45,18"
    assert row["total"] == "47,75"
    assert report["blocking_unresolved"] == []
    assert any((p.get("evidence") or {}).get("matched_delta_token") for p in report["patches"])
    assert any((p.get("evidence") or {}).get("recovery_strategy") in {"row_segment", "context_expected_value"} for p in report["patches"])


def test_v61_0_63_quality_gate_exposes_blocking_severity_for_unrecovered_financial_fields():
    cleaned = prune_runtime_only_fields(_problem_result())
    gate = cleaned["auditoria_final"]["quality_gate"]
    assert gate["ok"] is False
    assert gate["blocking_issue_count"] >= 1
    assert gate["severity_summary"]["blocking"] >= 1
    assert cleaned["status"] == "quality_gate_failed"
    resumo = cleaned["documento_correcao"]["resumo"]
    assert resumo["quality_gate_ok"] is False
    assert resumo["quality_gate_blocking_issue_count"] >= 1
