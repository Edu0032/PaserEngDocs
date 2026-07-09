from __future__ import annotations

from app.config.version import CURRENT_RELEASE
from app.parser.compact_correction_document import apply_compact_correction_document


def _base_result() -> dict:
    return {
        "status": "ok",
        "meta": {"parser_version": CURRENT_RELEASE},
        "orcamento_sintetico": {
            "itens_raiz": [
                {"tipo": "meta", "item": "1", "descricao": "META TESTE", "custo_total": "10,00", "filhos": [
                    {"tipo": "item", "item": "1.1", "codigo": "12345", "fonte": "SINAPI", "especificacao": "SERVICO", "und": "UN", "quant": "1,00", "custo_unitario_sem_bdi": "10,00", "custo_unitario_com_bdi": "10,00", "custo_parcial": "10,00"}
                ]}
            ]
        },
        "composicoes": {"principais": {
            "12345|SINAPI": {
                "item": "1.1",
                "pagina_inicio": 7,
                "pagina_fim": 8,
                "paginas": [7, 8],
                "principal": {"codigo": "12345", "banco": "SINAPI", "descricao": "SERVICO", "und": "UN", "quant": "1,0000000", "valor_unit": "10,00", "total": "10,00"},
                "insumos": [],
                "composicoes_auxiliares": [],
            }
        }},
        "auditoria_final": {"quality_gate": {"ok": True, "blocking_issue_count": 0, "issues": []}},
        "extraction_status": {"version": CURRENT_RELEASE, "ok": True, "status": "ok", "critical_issue_count": 0, "issues": []},
        "document_consistency_status": {
            "version": CURRENT_RELEASE,
            "ok": False,
            "status": "document_inconsistency_detected",
            "issue_count": 1,
            "public_values_preserved": True,
            "issues": [
                {"code": "document_math_inconsistency_pdf_values_preserved", "collection": "principais", "block": "12345|SINAPI", "math_status": {"status": "divergent", "principal_total": "10,00", "component_sum": "9,99"}}
            ],
        },
        "documento_correcao": {
            "targeted_recovery": {"attempted": True, "target_count": 2, "patches": [], "unresolved": [{"id": "x"}]},
            "possible_left_behind_lines": [
                {"id": "missing_pdf_occurrence::7::67890::SINAPI::1", "page": 7, "codigo_norm": "67890", "banco": "SINAPI", "match_reason": "no_code_bank_match", "parsed_columns": {"codigo": "67890", "banco": "SINAPI", "descricao_preview": "LINHA TESTE", "und": "UN", "quant": "1,0000000", "valor_unit": "2,00", "total": "2,00"}, "line_preview": "Insumo 67890 SINAPI LINHA TESTE Material UN 1,0000000 2,00 2,00", "possible_destination_candidates": [{"composition": "12345|SINAPI", "item": "1.1", "page_start": 7, "page_end": 8}], "crop_hint": {"page": 7, "ui_action": "open_page_and_focus_line"}}
            ],
        },
    }


def test_v61_0_75_correction_catalog_has_rich_locations_and_categories():
    result = _base_result()
    compact = apply_compact_correction_document(result)
    corr = result["documento_correcao"]
    assert corr["schema_version"] == "correction_document.v2.actionable_review"
    assert compact["schema_version"] == "correction_document.v2.actionable_review"
    assert compact["summary"]["problem_count"] == 2
    assert len(corr["problemas"]) == 2
    assert set(corr["problemas_por_categoria"]) >= {"document_consistency", "possible_left_behind_lines"}

    doc_issue = [p for p in corr["problemas"] if p["categoria"] == "document_consistency"][0]
    assert doc_issue["local"]["composicao"] == "12345|SINAPI"
    assert doc_issue["local"]["page_interval"]["page_start"] == 7
    assert doc_issue["local"]["page_interval"]["page_end"] == 8
    assert doc_issue["material_apoio"]["crop_hint"]["page"] == 7
    assert doc_issue["valor_pdf"] == "10,00"
    assert doc_issue["valor_calculado"] == "9,99"

    left = [p for p in corr["problemas"] if p["categoria"] == "left_behind_scan"][0]
    assert left["local"]["page"] == 7
    assert left["local"]["composicao_candidata"] == "12345|SINAPI"
    assert left["colunas_detectadas"]["total"] == "2,00"
    assert left["material_apoio"]["crop_hint"]["ui_action"]


def test_v61_0_75_debug_payload_is_moved_out_of_correction_root():
    result = _base_result()
    apply_compact_correction_document(result)
    assert "targeted_recovery" not in result["documento_correcao"]
    assert result["documento_correcao"]["debug_summary"]["targeted_recovery"]["debug_path"] == "analise_orcamentaria.debug_recovery.targeted_recovery"
    assert result["analise_orcamentaria"]["debug_recovery"]["targeted_recovery"]["attempted"] is True
