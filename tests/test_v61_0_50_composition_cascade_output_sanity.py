from __future__ import annotations

from app.core.output_compact import _quality_gate_final
from app.parser.composition_principal_cascade_repair import apply_composition_principal_cascade_repair
from app.parser.output_documents_organizer import organize_lovable_output_documents


def _fixture_with_incomplete_composition():
    return {
        "orcamento_sintetico": {
            "itens_raiz": [
                {"tipo": "item", "item": "4.9.2", "codigo": "89446", "fonte": "SINAPI", "especificacao": "TUBO PVC", "und": "M", "quant": "61,00", "custo_unitario_sem_bdi": "5,47", "custo_unitario_com_bdi": "6,65", "custo_parcial": "405,65"}
            ]
        },
        "composicoes": {
            "principais": {
                "89446|SINAPI": {
                    "item": "4.9.2",
                    "principal": {"codigo": "89446", "banco": "SINAPI", "descricao": "TUBO PVC", "und": "M"},
                    "composicoes_auxiliares": [
                        {"codigo": "88248", "banco": "SINAPI", "descricao": "AUXILIAR", "und": "H", "quant": "0,0195", "valor_unit": "25,34", "total": "0,49"},
                        {"codigo": "88267", "banco": "SINAPI", "descricao": "ENCANADOR", "und": "H", "quant": "0,0195", "valor_unit": "31,03", "total": "0,60"},
                    ],
                    "insumos": [
                        {"codigo": "00009868", "banco": "SINAPI", "descricao": "TUBO", "und": "M", "quant": "1,0493", "valor_unit": "4,17", "total": "4,37"},
                        {"codigo": "00038383", "banco": "SINAPI", "descricao": "LIXA", "und": "UN", "quant": "0,0045", "valor_unit": "2,55", "total": "0,01"},
                    ],
                }
            }
        },
    }


def test_v61_0_50_does_not_recalculate_public_composition_principal_numbers():
    result, report = apply_composition_principal_cascade_repair(_fixture_with_incomplete_composition())
    principal = result["composicoes"]["principais"]["89446|SINAPI"]["principal"]
    assert "quant" not in principal
    assert "valor_unit" not in principal
    assert "total" not in principal
    assert principal.get("quant") != "61,00"
    assert report["summary"]["fields_repaired"] == 0
    assert report["summary"]["blocked"] == 1
    assert "public_numeric_repair_requires_physical_pdf_evidence" in str(report)


def test_v61_0_50_quality_gate_allows_internal_math_status_floats_but_not_public_float():
    final = _fixture_with_incomplete_composition()
    final["composicoes"]["principais"]["89446|SINAPI"]["detalhes"] = {"math_status": {"component_sum": 5.47, "delta": 0.0}}
    gate = _quality_gate_final(final)
    assert not [i for i in gate["issues"] if i.get("code") == "public_float_leaked"]
    final["composicoes"]["principais"]["89446|SINAPI"]["principal"]["total"] = 5.47
    gate = _quality_gate_final(final)
    assert any(i.get("code") == "public_float_leaked" for i in gate["issues"])


def test_v61_0_50_enrichment_scans_public_domain_not_audit_details():
    final = _fixture_with_incomplete_composition()
    final["meta"] = {"performance": {"fake": {"und": "SHOULD_NOT_APPEAR"}}}
    final["composicoes"]["principais"]["89446|SINAPI"]["detalhes"] = {"debug": {"und": "INTERNAL"}}
    organize_lovable_output_documents(final, {"rows": [], "summary": {}, "physical_evidence_index": {"keys": {}}})
    doc = final["documento_enriquecimento"]
    text = str(doc)
    assert "SHOULD_NOT_APPEAR" not in text
    assert "INTERNAL" not in text
    assert "M" in text
