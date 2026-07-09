from __future__ import annotations

"""Field consensus over the Document Evidence Index (v61.0.41)."""

from typing import Any, Dict, Iterable, List, Optional

from app.parser.document_evidence_index import code_bank_key
from app.parser.extracted_relation_graph import relation_allows_field, relation_name
from app.parser.field_patch_validators import validate_patch_candidate

VERSION = "v61.0.75-correction-output-contract-and-review-index"

FIELD_ALIASES = {
    "descricao": ["descricao", "especificacao"],
    "especificacao": ["especificacao", "descricao"],
    "und": ["und"],
    "valor_unit": ["valor_unit", "custo_unitario_com_bdi"],
    "custo_unitario_com_bdi": ["custo_unitario_com_bdi", "valor_unit"],
    "custo_unitario_sem_bdi": ["custo_unitario_sem_bdi"],
    "custo_parcial": ["custo_parcial"],
    "custo_total": ["custo_total"],
    "total": ["total"],
}

NUMERIC_CONTEXT_FORBIDDEN = {"quant"}


def _clean(v: Any) -> str:
    return " ".join(str(v or "").replace("\u00a0", " ").split())


def _empty(v: Any) -> bool:
    return v in (None, "")


def _row_key(row: Any) -> str:
    return code_bank_key(getattr(row, "codigo", ""), getattr(row, "banco", ""))


def _field_plan(row: Any, missing_fields: Iterable[str]) -> List[str]:
    plan: List[str] = []
    for field in missing_fields or []:
        f = str(field or "")
        if not f:
            continue
        if f == "fonte":
            # fonte/banco are identity fields and should not be guessed here.
            continue
        if f == "banco":
            continue
        if f == "codigo":
            continue
        if f == "quant":
            # Contextual quantity is too dangerous to recover from a global index.
            continue
        plan.append(f)
    return list(dict.fromkeys(plan))


def _candidate_values(index: Dict[str, Any], key: str, target_field: str) -> List[Dict[str, Any]]:
    bucket = ((index.get("keys") or {}).get(key) or {}) if isinstance(index, dict) else {}
    fields = bucket.get("fields") or {}
    out: List[Dict[str, Any]] = []
    for source_field in FIELD_ALIASES.get(target_field, [target_field]):
        data = fields.get(source_field) or {}
        for value_rec in data.get("values") or []:
            rec = dict(value_rec)
            rec["source_field"] = source_field
            out.append(rec)
    out.sort(key=lambda d: (d.get("count", 0), d.get("source_count", 0), d.get("max_confidence", 0.0)), reverse=True)
    return out


def _relation_ok(row: Any, target_field: str, value_record: Dict[str, Any]) -> bool:
    records = value_record.get("records") or []
    if not records:
        # Ledger-only evidence: allow non-quantity if validation succeeds.
        return target_field not in NUMERIC_CONTEXT_FORBIDDEN
    for rec in records:
        relation = relation_name(str(getattr(row, "family", "")), str(getattr(row, "group", "")), str(rec.get("family") or ""), str(rec.get("group") or ""), str(rec.get("collection") or ""))
        if relation_allows_field(relation, target_field):
            return True
    return False



def _policy_allows_field(target_field: str, value_record: Dict[str, Any]) -> bool:
    records = value_record.get("records") or []
    if not records:
        return True
    # If a record explicitly carries section policy, only use records that allow
    # public writes for this field.  This blocks Memória/Curva ABC values from
    # overwriting budget/composition prices while still preserving them in the
    # correction evidence trail.
    policy_records = [rec for rec in records if isinstance(rec, dict) and ("field_public_write_allowed" in rec or rec.get("repair_allowed_fields") is not None)]
    if not policy_records:
        return True
    for rec in policy_records:
        allowed = set(rec.get("repair_allowed_fields") or [])
        if rec.get("field_public_write_allowed") is True and target_field in allowed:
            return True
    return False

def build_field_consensus_candidates(rows: Iterable[Any], document_index: Dict[str, Any], *, context: Dict[str, Any] | None = None, min_score: float = 0.82) -> Dict[str, Any]:
    context = context if isinstance(context, dict) else {}
    candidates: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for row in list(rows or []):
        if str(getattr(row, "family", "")) == "sicro" and str(getattr(row, "group", "")) == "section_row":
            continue
        key = _row_key(row)
        if not key:
            continue
        data = getattr(row, "row", {}) or {}
        if not isinstance(data, dict):
            continue
        missing_fields: List[str] = []
        if row.family == "budget":
            required = [getattr(row, "field_name", "especificacao"), "und", "quant", "custo_unitario_com_bdi", "custo_parcial"]
        elif row.family == "sinapi_like":
            required = ["descricao", "und", "quant", "valor_unit", "total"]
        else:
            required = []
        for f in required:
            if _empty(data.get(f)):
                missing_fields.append(f)
        # Math expectations are also candidates, but only when the same value is
        # present in the index for the target field.
        calc_expectations = []
        try:
            calc_expectations = list(((data.get("_calc") or {}).get("math_only_expectations") or []))
        except Exception:
            calc_expectations = []
        for field in _field_plan(row, missing_fields):
            values = _candidate_values(document_index, key, field)
            expected_values = {str(e.get("expected_value")) for e in calc_expectations if isinstance(e, dict) and e.get("field") == field and e.get("expected_value")}
            for vrec in values[:8]:
                value = _clean(vrec.get("value"))
                if not value:
                    continue
                validation = validate_patch_candidate(field, value, data, context)
                if not validation.get("ok"):
                    rejected.append({"row_id": row.row_id, "field": field, "value": value, "reason": "validation_failed", "validation": validation})
                    continue
                if not _relation_ok(row, field, vrec):
                    rejected.append({"row_id": row.row_id, "field": field, "value": value, "reason": "relation_contract_forbids_field"})
                    continue
                if not _policy_allows_field(field, vrec):
                    rejected.append({"row_id": row.row_id, "field": field, "value": value, "reason": "evidence_section_policy_forbids_public_write", "records": (vrec.get("records") or [])[:4]})
                    continue
                score = float(vrec.get("max_confidence") or 0.0)
                score += min(0.08, 0.02 * int(vrec.get("count") or 0))
                score += min(0.06, 0.03 * int(vrec.get("source_count") or 0))
                math_confirmed = False
                if expected_values:
                    if value in expected_values:
                        score += 0.08
                        math_confirmed = True
                    else:
                        # For numeric fields, a math expectation that disagrees is
                        # a strong rejection signal.
                        if field not in {"descricao", "especificacao", "und"}:
                            rejected.append({"row_id": row.row_id, "field": field, "value": value, "reason": "math_expectation_disagrees", "expected_values": sorted(expected_values)})
                            continue
                score = min(0.99, score)
                record = {
                    "row_id": row.row_id,
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
                    "source": "field_consensus_engine",
                    "evidence_grade": "document_evidence_index_consensus_math_confirmed" if math_confirmed else "document_evidence_index_consensus",
                    "confidence": round(score, 3),
                    "reason": "document_evidence_index_field_consensus",
                    "source_field": vrec.get("source_field"),
                    "source_count": vrec.get("source_count"),
                    "occurrence_count": vrec.get("count"),
                    "pages": vrec.get("pages") or [],
                    "math_confirmed": math_confirmed,
                    "validation": validation,
                    "quantity_policy": "never_copy_contextual_quantity",
                    "evidence": {"value_record": {k: v for k, v in vrec.items() if k != "records"}, "records": (vrec.get("records") or [])[:8]},
                }
                if score >= min_score:
                    candidates.append(record)
                    break
                rejected.append({**record, "reason": "score_below_threshold"})
    return {"version": VERSION, "candidate_count": len(candidates), "rejected_count": len(rejected), "candidates": candidates, "rejected": rejected[:200]}
