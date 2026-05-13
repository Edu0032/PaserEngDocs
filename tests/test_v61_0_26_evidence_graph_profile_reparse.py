from __future__ import annotations

import re
from pathlib import Path

from app.core.schemas import BlocoComposicao, Composicoes, LinhaComposicao, OrcamentoItem, OrcamentoSintetico
from app.normalizer.field_recovery import recover_fields
from app.parser.code_value_classifier import looks_like_code, looks_like_ptbr_decimal_or_money
from app.parser.document_learning_layer import build_document_learning_profile
from app.parser.evidence_graph import build_evidence_graph, apply_evidence_graph_recheck


def test_evidence_graph_confirms_cross_table_description_and_repairs_budget_and_composition():
    complete = "ESCAVAÇÃO MANUAL DE VALA COM PROFUNDIDADE MENOR OU IGUAL A 1,30 M"
    orc = OrcamentoSintetico(itens_raiz=[
        OrcamentoItem(tipo="item", item="1.1", codigo="93358", fonte="SINAPI", especificacao="ESCAVAÇÃO MANUAL", und="M3"),
    ])
    comp = Composicoes(principais={
        "93358|SINAPI": BlocoComposicao(
            item="1.1",
            principal=LinhaComposicao(codigo="93358", banco="SINAPI", descricao=complete, und="M3", quant=1, valor_unit=10, total=10),
            composicoes_auxiliares=[LinhaComposicao(codigo="93358", banco="SINAPI", descricao="ESCAVAÇÃO MANUAL", und="M3")],
        )
    })
    graph = build_evidence_graph(orc, comp)
    assert graph["summary"]["confirmed"] == 1
    assert graph["entries"]["93358|SINAPI"]["locked_negative_evidence"] is True
    recheck = apply_evidence_graph_recheck(orc, comp, graph)
    assert recheck["metrics"]["repairs_applied"] >= 2
    assert orc.itens_raiz[0].especificacao == complete
    assert comp.principais["93358|SINAPI"].composicoes_auxiliares[0].descricao == complete


def test_selective_reparse_plan_tracks_budget_and_composition_weak_rows_without_mixing_profiles():
    orc = OrcamentoSintetico(itens_raiz=[OrcamentoItem(tipo="item", item="1.1", codigo="90777", fonte="SINAPI", especificacao="ENGENHEIRO CIVIL COM", und="H")])
    comp = Composicoes(principais={
        "90777|SINAPI": BlocoComposicao(item="1.1", principal=LinhaComposicao(codigo="90777", banco="SINAPI", descricao="ENGENHEIRO CIVIL COM", und="H"))
    })
    profile = build_document_learning_profile(orc, comp, context={
        "structured_tables": {
            "tables": {
                "budget": {"columns": [{"canonical": "descricao", "x0": 80, "x1": 310}]},
                "composition": {"family": "sinapi_like", "columns": [{"canonical": "descricao", "x0": 170, "x1": 450}]},
            }
        }
    })
    assert profile["budget_profile"]["column_bands"]["descricao"]["x0_median"] == 80
    assert profile["sinapi_like_profile"]["column_bands"]["descricao"]["x0_median"] == 170
    plan = profile["selective_reparse_plan"]
    assert plan["summary"]["budget_targets"] == 1
    assert plan["summary"]["composition_targets"] == 1


def test_code_classifier_accepts_dotted_letter_codes_but_not_ptbr_money():
    for value in ["CADM.01", "COMP.JCO.3", "ANP 01", "CP - 120", "74209/001", "103672-01"]:
        assert looks_like_code(value), value
        assert not looks_like_ptbr_decimal_or_money(value), value
    for value in ["1.234,56", "6,05", "100,0000"]:
        assert looks_like_ptbr_decimal_or_money(value), value
        assert not looks_like_code(value), value


def test_docling_payload_builder_preserves_header_canonical_mapping_and_stays_clean():
    worker = Path("parser_browser/browser/pyodide/pyodide-parser-worker.js").read_text(encoding="utf-8")
    assert "canonical_name: h.canonical_name || h.canonical" in worker
    assert "first_row_samples" in worker
    assert "docling_api_key: p.docling_api_key" not in worker
    assert "docling_api_url: p.docling_api_url" not in worker
    assert "Do not hardcode profession/service words" in worker


def _make_pdf(lines: list[tuple[float, float, str]]) -> bytes:
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=620, height=220)
    for x, y, text in lines:
        page.insert_text((x, y), text, fontsize=9)
    data = doc.tobytes()
    doc.close()
    return data


def test_hypothesis_recovery_reports_candidates_for_budget_fragment():
    pdf = _make_pdf([
        (45, 50, "1.1 90777 SINAPI"),
        (165, 50, "ENGENHEIRO CIVIL DE OBRA JUNIOR COM"),
        (165, 62, "ENCARGOS COMPLEMENTARES"),
    ])
    payload = {
        "page_map": {"1": 1},
        "targets": [{
            "target_id": "orcamento_sintetico.itens_raiz.0::especificacao",
            "path": ["orcamento_sintetico", "itens_raiz", 0, "especificacao"],
            "field": "especificacao",
            "family": "budget",
            "current_value": "ENGENHEIRO CIVIL DE OBRA JUNIOR COM",
            "codigo": "90777",
            "banco": "SINAPI",
            "page": 1,
            "issue": "possible_truncated_budget_description",
        }],
        "column_maps": {"budget": {"columns": [
            {"canonical": "codigo", "x0": 45, "x1": 90},
            {"canonical": "fonte", "x0": 95, "x1": 150},
            {"canonical": "descricao", "x0": 160, "x1": 455},
            {"canonical": "und", "x0": 460, "x1": 495},
        ]}},
        "apply_confidence_min": 0.85,
    }
    result = recover_fields(pdf, payload)
    assert result["summary"]["patches"] == 1, result
    patch = result["patches"][0]
    assert patch["value"].endswith("ENCARGOS COMPLEMENTARES")
    assert patch["evidence"]["hypotheses"]
    assert any(h["hypothesis"] == "target_plus_downward_fragments" for h in patch["evidence"]["hypotheses"])
