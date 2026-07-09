from __future__ import annotations

import json
from pathlib import Path
from functools import lru_cache

from app.parser.field_consensus_engine import build_field_consensus_candidates
from app.parser.line_certainty_closure import _collect_rows
from app.parser.physical_evidence_index import build_physical_evidence_index, merge_physical_evidence_into_document_index
from app.parser.real_document_regression import run_real_document_regression
from app.parser.document_evidence_index import build_document_evidence_index

FIXTURE = Path(__file__).parent / "fixtures" / "real_documents" / "deracre_casa_produtor.pdf"
EXPECTED = json.loads((Path(__file__).parent / "fixtures" / "real_documents" / "deracre_casa_produtor_expected_core.json").read_text(encoding="utf-8"))


def _final_for_real_pdf():
    return {
        "orcamento_sintetico": {
            "itens_raiz": [
                {"item": "1.1.1", "codigo": "74209/001", "fonte": "SINAPI", "especificacao": "", "und": "", "quant": "", "custo_unitario_com_bdi": "", "custo_parcial": ""},
                {"item": "3.2.7", "codigo": "ANP 01", "fonte": "Próprio", "especificacao": "", "und": "", "quant": "", "custo_unitario_com_bdi": "", "custo_parcial": ""},
                {"item": "4.9.2", "codigo": "89446", "fonte": "SINAPI", "especificacao": "", "und": "", "quant": "", "custo_unitario_com_bdi": "", "custo_parcial": ""},
            ]
        },
        "composicoes": {
            "sinapi_like": {
                "principais": {
                    "74209/001|SINAPI": {"principal": {"codigo": "74209/001", "banco": "SINAPI", "descricao": "", "und": "", "quant": "", "valor_unit": "", "total": ""}},
                    "89446|SINAPI": {"principal": {"codigo": "89446", "banco": "SINAPI", "descricao": "", "und": "", "quant": "", "valor_unit": "", "total": ""}},
                }
            }
        },
    }


def _options():
    return {"ranges": {"budget": {"start": 2, "end": 4}, "compositions": {"start": 9, "end": 148}}, "expected_core": EXPECTED}


@lru_cache(maxsize=1)
def _cached_index():
    return build_physical_evidence_index(str(FIXTURE), _final_for_real_pdf(), _options(), max_keys=20, max_occurrences_per_key=30)


def _top_values(index, key, field):
    return [v["value"] for v in (((index["keys"][key]["fields"].get(field) or {}).get("values") or [])[:5])]


def test_real_pdf_physical_index_is_section_aware_and_fuses_split_rows():
    index = _cached_index()
    assert index["status"] == "ok"
    assert index["document_section_counts"].get("orcamento_sintetico", 0) >= 3
    assert index["document_section_counts"].get("memoria_calculo", 0) >= 2
    assert index["document_section_counts"].get("curva_abc", 0) >= 1
    assert "405,65" in _top_values(index, "89446|SINAPI", "custo_parcial")
    assert "6,65" in _top_values(index, "89446|SINAPI", "custo_unitario_com_bdi")
    assert "61,00" in _top_values(index, "89446|SINAPI", "quant")
    # ANP contains CM-30 in the description; the unit must remain t, not cm.
    assert _top_values(index, "ANP 01|PROPRIO", "und")[0] == "t"
    assert "cm" not in _top_values(index, "ANP 01|PROPRIO", "und")


def test_memoria_and_curva_abc_are_not_allowed_to_pollute_public_price_fields():
    index = _cached_index()
    anp = index["keys"]["ANP 01|PROPRIO"]
    memoria_occ = [o for o in anp["occurrences"] if o.get("document_section") == "memoria_calculo"]
    assert memoria_occ, "expected ANP occurrences in calculation memory"
    assert all("valor_unit" not in (o.get("fields_detected") or {}) for o in memoria_occ)
    assert all("custo_parcial" not in (o.get("fields_detected") or {}) for o in memoria_occ)
    abc_occ = [o for b in index["keys"].values() for o in b["occurrences"] if o.get("document_section") == "curva_abc"]
    assert abc_occ, "expected diagnostic ABC occurrences"
    assert all((o.get("evidence_policy") or {}).get("diagnostic_only") for o in abc_occ)


def test_field_consensus_uses_budget_physical_values_but_respects_section_policy():
    final = _final_for_real_pdf()
    index = build_physical_evidence_index(str(FIXTURE), final, _options(), max_keys=20, max_occurrences_per_key=30)
    rows = _collect_rows(final)
    doc_index = merge_physical_evidence_into_document_index(build_document_evidence_index(rows, None), index)
    report = build_field_consensus_candidates(rows, doc_index)
    candidates = {(c["codigo"], c["field"], c["value"]) for c in report["candidates"]}
    assert ("89446", "custo_parcial", "405,65") in candidates
    assert ("89446", "custo_unitario_com_bdi", "6,65") in candidates
    # Calculation memory has quantities/dimensions; it must not feed price fields.
    rejected_reasons = {r.get("reason") for r in report.get("rejected", [])}
    assert "evidence_section_policy_forbids_public_write" in rejected_reasons or report["candidate_count"] > 0


def test_real_document_regression_expected_core_passes_on_uploaded_pdf():
    report = run_real_document_regression(str(FIXTURE), _final_for_real_pdf(), {**_options(), "physical_evidence_index": _cached_index()})
    assert report["status"] == "ok"
    assert report["summary"]["failed"] == 0
    assert report["summary"]["passed"] >= 14
    assert any(f["type"] == "section_policy_active" and f["section"] == "memoria_calculo" for f in report["tuning_findings"])
