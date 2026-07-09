from __future__ import annotations

"""Local line cascade repair for v61.0.47.

The parser already knows the identity of a row (codigo+banco), its family
(budget/composition), its current values and its math-only expectations.  This
module uses that context to look again in the physical/document indexes around
that same identity and produce safe repair candidates.

It deliberately does not invent values: a public numeric field is suggested only
when a value is present in the PDF-backed evidence or extracted evidence and, when
math can predict the missing field, the candidate matches the expected value.
"""

from typing import Any, Dict, Iterable, List, Tuple

from app.parser.document_evidence_index import code_bank_key
from app.parser.field_patch_validators import validate_patch_candidate

VERSION = "v61.0.75-correction-output-contract-and-review-index"

NUMERIC_FIELDS = {
    "quant",
    "valor_unit",
    "total",
    "custo_unitario_sem_bdi",
    "custo_unitario_com_bdi",
    "custo_parcial",
    "custo_total",
}
TEXT_FIELDS = {"descricao", "especificacao", "und"}


def _clean(v: Any) -> str:
    return " ".join(str(v or "").replace("\u00a0", " ").split())


def _empty(v: Any) -> bool:
    return v in (None, "")


def _row_key(row: Any) -> str:
    return code_bank_key(getattr(row, "codigo", ""), getattr(row, "banco", ""))


def _required_fields(row: Any) -> List[str]:
    family = str(getattr(row, "family", ""))
    if family == "budget":
        return [str(getattr(row, "field_name", "especificacao") or "especificacao"), "und", "quant", "custo_unitario_com_bdi", "custo_parcial"]
    if family == "sinapi_like":
        return ["descricao", "und", "quant", "valor_unit", "total"]
    return []


def _missing_fields(row: Any) -> List[str]:
    data = getattr(row, "row", {}) or {}
    return [f for f in _required_fields(row) if _empty(data.get(f))]


def _expectations_by_field(row: Any) -> Dict[str, List[str]]:
    data = getattr(row, "row", {}) or {}
    out: Dict[str, List[str]] = {}
    for exp in ((data.get("_calc") or {}).get("math_only_expectations") or []):
        if not isinstance(exp, dict):
            continue
        field = str(exp.get("field") or "")
        value = _clean(exp.get("expected_value"))
        if field and value:
            out.setdefault(field, []).append(value)
    return out


def _field_allowed_by_policy(field: str, rec: Dict[str, Any]) -> bool:
    # If a record comes from a section-aware physical index, respect its policy.
    if "field_public_write_allowed" in rec or rec.get("repair_allowed_fields") is not None:
        return bool(rec.get("field_public_write_allowed")) and field in set(rec.get("repair_allowed_fields") or [])
    return True


def _field_records_from_document_index(document_index: Dict[str, Any], key: str, field: str) -> List[Dict[str, Any]]:
    bucket = ((document_index.get("keys") or {}).get(key) or {}) if isinstance(document_index, dict) else {}
    fields = bucket.get("fields") or {}
    aliases = [field]
    if field == "descricao":
        aliases.append("especificacao")
    if field == "especificacao":
        aliases.append("descricao")
    # Numeric cross aliases are intentionally narrow.  Budget price and
    # composition price may confirm each other only when evidence policy and math
    # agree.
    if field == "valor_unit":
        # Composition unit price is comparable to budget sem-BDI cost, not the
        # BDI-included public budget cost.  Quantity remains contextual.
        aliases.append("custo_unitario_sem_bdi")
    if field == "custo_unitario_sem_bdi":
        aliases.append("valor_unit")
    out: List[Dict[str, Any]] = []
    for alias in aliases:
        data = fields.get(alias) or {}
        for val in data.get("values") or []:
            if isinstance(val, dict):
                out.append({**val, "source_field": alias})
    out.sort(key=lambda r: (r.get("count", 0), r.get("source_count", 0), r.get("max_confidence", 0.0)), reverse=True)
    return out


def _physical_bucket(physical_index: Dict[str, Any], key: str) -> Dict[str, Any]:
    if not isinstance(physical_index, dict):
        return {}
    return ((physical_index.get("keys") or {}).get(key) or {})


def _same_family_authoritative(row: Any, rec: Dict[str, Any]) -> bool:
    section = str(rec.get("document_section") or "")
    source_zone = str(rec.get("source_zone") or "")
    family = str(getattr(row, "family", ""))
    if family == "budget":
        return section in {"orcamento_sintetico", "declared_range_unknown_layout"} or source_zone == "known_budget_or_composition_interval"
    if family == "sinapi_like":
        return section in {"composicoes_analiticas", "declared_range_unknown_layout"} or source_zone == "known_budget_or_composition_interval"
    return False


def _candidate_from_value_record(row: Any, field: str, vrec: Dict[str, Any], expected_values: List[str], context: Dict[str, Any]) -> Tuple[Dict[str, Any] | None, Dict[str, Any] | None]:
    value = _clean(vrec.get("value"))
    if not value:
        return None, {"field": field, "reason": "empty_value"}
    records = [r for r in (vrec.get("records") or []) if isinstance(r, dict)]
    if records and not any(_field_allowed_by_policy(field, r) for r in records):
        return None, {"field": field, "value": value, "reason": "section_policy_forbids_public_write", "records": records[:4]}
    if field in NUMERIC_FIELDS and expected_values and value not in set(expected_values):
        return None, {"field": field, "value": value, "reason": "candidate_does_not_match_math_expectation", "expected_values": expected_values}
    validation = validate_patch_candidate(field, value, getattr(row, "row", {}) or {}, context)
    if not validation.get("ok"):
        return None, {"field": field, "value": value, "reason": "validation_failed", "validation": validation}
    confidence = float(vrec.get("max_confidence") or 0.0)
    confidence += min(0.07, 0.02 * int(vrec.get("count") or 0))
    confidence += 0.08 if expected_values and value in expected_values else 0.0
    # Evidence found in the same family section is stronger than generic cross
    # evidence.  Still, do not overclaim closed_100 here; closure decides later.
    if records and any(_same_family_authoritative(row, r) for r in records):
        confidence += 0.05
    confidence = min(0.99, confidence)
    if confidence < (0.80 if field in TEXT_FIELDS else 0.84):
        return None, {"field": field, "value": value, "reason": "score_below_local_cascade_threshold", "confidence": round(confidence, 3)}
    return {
        "row_id": getattr(row, "row_id", ""),
        "path": list(getattr(row, "path", []) or []) + [field],
        "row_path": list(getattr(row, "path", []) or []),
        "family": getattr(row, "family", ""),
        "group": getattr(row, "group", ""),
        "collection": getattr(row, "collection", ""),
        "codigo": getattr(row, "codigo", ""),
        "banco": getattr(row, "banco", ""),
        "item": getattr(row, "item", ""),
        "field": field,
        "value": validation.get("normalized", value),
        "source": "local_line_cascade_repair",
        "evidence_grade": "local_same_identity_cascade_math_confirmed" if expected_values and value in expected_values else "local_same_identity_cascade",
        "confidence": round(confidence, 3),
        "reason": "local_line_neighborhood_cascade_repair",
        "math_confirmed": bool(expected_values and value in expected_values),
        "validation": validation,
        "quantity_policy": "quantity_only_from_same_identity_authoritative_or_math_checked",
        "evidence": {"value_record": {k: v for k, v in vrec.items() if k != "records"}, "records": records[:8]},
    }, None


def _candidate_from_expected_in_raw_occurrences(row: Any, field: str, expected: str, physical_index: Dict[str, Any], context: Dict[str, Any]) -> Tuple[Dict[str, Any] | None, Dict[str, Any] | None]:
    key = _row_key(row)
    bucket = _physical_bucket(physical_index, key)
    for occ in bucket.get("occurrences") or []:
        if not isinstance(occ, dict):
            continue
        line_text = _clean(occ.get("line_text") or occ.get("raw_text"))
        if not line_text or expected not in line_text:
            continue
        fields_detected = occ.get("fields_detected") if isinstance(occ.get("fields_detected"), dict) else {}
        # If the expected token appears only once and the physical extractor did
        # not identify it as the target field, it may simply be the sibling unit
        # price.  Keep the expectation under _calc instead of writing a public
        # total/custo field.
        if field in {"total", "custo_parcial", "custo_total"} and fields_detected.get(field) != expected and line_text.count(expected) < 2:
            return None, {"field": field, "value": expected, "reason": "math_expected_ambiguous_single_token_in_line", "line_text": line_text[:240]}
        policy = occ.get("evidence_policy") if isinstance(occ.get("evidence_policy"), dict) else {}
        allowed = set(policy.get("repair_allowed_fields") or [])
        if field not in allowed:
            return None, {"field": field, "value": expected, "reason": "expected_value_found_but_section_policy_forbids_field", "section": occ.get("document_section"), "line_text": line_text[:240]}
        validation = validate_patch_candidate(field, expected, getattr(row, "row", {}) or {}, context)
        if not validation.get("ok"):
            return None, {"field": field, "value": expected, "reason": "expected_value_validation_failed", "validation": validation}
        source_zone = str(occ.get("source_zone") or "")
        confidence = float(occ.get("confidence") or 0.0) + 0.10
        if _same_family_authoritative(row, occ):
            confidence += 0.08
        if policy.get("policy") == "labeled_raw_occurrence_context":
            confidence += 0.05
        confidence = min(0.99, confidence)
        if confidence < 0.84:
            continue
        return {
            "row_id": getattr(row, "row_id", ""),
            "path": list(getattr(row, "path", []) or []) + [field],
            "row_path": list(getattr(row, "path", []) or []),
            "family": getattr(row, "family", ""),
            "group": getattr(row, "group", ""),
            "collection": getattr(row, "collection", ""),
            "codigo": getattr(row, "codigo", ""),
            "banco": getattr(row, "banco", ""),
            "item": getattr(row, "item", ""),
            "field": field,
            "value": validation.get("normalized", expected),
            "source": "local_line_cascade_repair",
            "evidence_grade": "math_expected_value_found_in_local_physical_occurrence",
            "confidence": round(confidence, 3),
            "reason": "math_expected_value_found_near_same_codigo_banco",
            "math_confirmed": True,
            "validation": validation,
            "evidence": {"occurrence": {k: v for k, v in occ.items() if k not in {"raw_context"}}, "source_zone": source_zone},
        }, None
    return None, {"field": field, "value": expected, "reason": "math_expected_value_not_found_in_same_identity_physical_occurrences"}


def build_local_line_cascade_candidates(rows: Iterable[Any], physical_index: Dict[str, Any], document_index: Dict[str, Any], *, context: Dict[str, Any] | None = None, max_candidates: int = 160) -> Dict[str, Any]:
    """Build repair candidates by looking again around each known row identity.

    This is the v61.0.47 accuracy hardening layer: it is more aggressive than
    the generic field consensus because it uses the row's own identity and math
    expectations, but it remains conservative about public writes.
    """
    context = context if isinstance(context, dict) else {}
    candidates: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    if not isinstance(physical_index, dict) or not (physical_index.get("keys") or {}):
        return {
            "version": VERSION,
            "mode": "local_line_neighborhood_cascade_repair",
            "status": "skipped",
            "reason": "physical_index_not_available",
            "rows_seen": 0,
            "candidate_count": 0,
            "rejected_count": 0,
            "math_expected_searches": 0,
            "candidates": [],
            "rejected": [],
        }
    rows_seen = 0
    math_expected_searches = 0
    for row in list(rows or []):
        if str(getattr(row, "family", "")) == "sicro" and str(getattr(row, "group", "")) == "section_row":
            continue
        key = _row_key(row)
        if not key:
            continue
        rows_seen += 1
        missing = _missing_fields(row)
        if not missing:
            continue
        expected_by_field = _expectations_by_field(row)
        for field in missing:
            # First, use explicit candidate fields already indexed for this id.
            chosen = None
            for vrec in _field_records_from_document_index(document_index, key, field)[:10]:
                cand, rej = _candidate_from_value_record(row, field, vrec, expected_by_field.get(field, []), context)
                if cand:
                    chosen = cand
                    break
                if rej:
                    rejected.append({"row_id": getattr(row, "row_id", ""), "codigo": getattr(row, "codigo", ""), "banco": getattr(row, "banco", ""), **rej})
            if chosen:
                candidates.append(chosen)
                if len(candidates) >= max_candidates:
                    break
                continue
            # Then, for math-missing numeric fields, search the exact expected
            # token in all same-codigo+banco physical occurrences, including raw
            # contexts outside known ranges when explicitly labelled.
            for expected in expected_by_field.get(field, []):
                math_expected_searches += 1
                cand, rej = _candidate_from_expected_in_raw_occurrences(row, field, expected, physical_index, context)
                if cand:
                    candidates.append(cand)
                    break
                if rej:
                    rejected.append({"row_id": getattr(row, "row_id", ""), "codigo": getattr(row, "codigo", ""), "banco": getattr(row, "banco", ""), **rej})
            if len(candidates) >= max_candidates:
                break
        if len(candidates) >= max_candidates:
            break
    return {
        "version": VERSION,
        "mode": "local_line_neighborhood_cascade_repair",
        "rows_seen": rows_seen,
        "candidate_count": len(candidates),
        "rejected_count": len(rejected),
        "math_expected_searches": math_expected_searches,
        "candidates": candidates,
        "rejected": rejected[:240],
    }
