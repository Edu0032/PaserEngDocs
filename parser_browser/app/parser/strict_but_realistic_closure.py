from __future__ import annotations

"""Strict but realistic line closure scoring (v61.0.43).

This layer does not reject useful consensus just because one perfect proof is
missing.  It grades how well the puzzle pieces fit: required fields, evidence,
ownership, relation/cross support and math.  It can promote rows to
``closed_by_strong_consensus`` while keeping true ``closed_100`` for rows with
very strong evidence and no meaningful warnings.
"""

from typing import Any, Dict, List

VERSION = "v61.0.75-correction-output-contract-and-review-index"


def _clean(value: Any) -> str:
    return " ".join(str(value or "").replace("\u00a0", " ").split())


def _field_grade_ok(grade: Dict[str, Any]) -> bool:
    if not isinstance(grade, dict):
        return False
    if grade.get("public_supported") is False:
        return False
    value = _clean(grade.get("value"))
    return bool(value)


def classify_line(row_report: Dict[str, Any], *, entity_graph: Dict[str, Any] | None = None, ownership_graph: Dict[str, Any] | None = None) -> Dict[str, Any]:
    status = str(row_report.get("row_status") or "")
    missing = list(row_report.get("missing_fields") or [])
    reasons = list(row_report.get("reasons") or [])
    math_status = row_report.get("math_status") if isinstance(row_report.get("math_status"), dict) else {}
    grades = row_report.get("field_evidence_grades") if isinstance(row_report.get("field_evidence_grades"), dict) else {}
    key = f"{_clean(row_report.get('codigo'))}|{_clean(row_report.get('banco')).upper()}" if row_report.get("codigo") else ""
    related_count = len(((entity_graph or {}).get("by_key") or {}).get(key) or [])
    owned_fragments = [f for f in (ownership_graph or {}).get("fragments", []) if isinstance(f, dict) and f.get("key") == key]
    locked_fragments = [f for f in owned_fragments if f.get("ownership_status") == "locked"]
    required_supported = True
    unsupported_fields: List[str] = []
    for field, grade in grades.items():
        if field in {"codigo", "banco", "fonte"}:
            continue
        if not _field_grade_ok(grade):
            required_supported = False
            unsupported_fields.append(field)
    gates = {
        "presence": not missing,
        "type_and_text": not any(str(r).startswith("description_issue") for r in reasons),
        "math": bool(math_status.get("ok", True)) or math_status.get("status") == "not_applicable",
        "evidence_supported": required_supported,
        "relation_context": related_count >= 1,
        "ownership_context": bool(owned_fragments) or related_count > 1,
    }
    closure_status = status
    if missing:
        closure_status = "unresolved"
    elif not gates["math"]:
        closure_status = "closed_with_warning"
    elif status == "closed_100" and gates["evidence_supported"] and (locked_fragments or related_count > 1 or row_report.get("family") == "sicro"):
        closure_status = "closed_100"
    elif status in {"closed_100", "closed_with_warning"} and gates["evidence_supported"] and gates["relation_context"]:
        closure_status = "closed_by_strong_consensus"
    elif status == "closed_100" and not gates["evidence_supported"]:
        closure_status = "closed_with_warning"
    failed = [k for k, ok in gates.items() if not ok]
    return {"version": VERSION, "row_id": row_report.get("row_id"), "key": key, "input_status": status, "closure_status": closure_status, "gates": gates, "failed_gates": failed, "unsupported_fields": unsupported_fields, "related_entity_count": related_count, "owned_fragment_count": len(owned_fragments), "locked_fragment_count": len(locked_fragments)}


def build_strict_realistic_closure_report(row_reports: List[Dict[str, Any]], *, entity_graph: Dict[str, Any] | None = None, ownership_graph: Dict[str, Any] | None = None) -> Dict[str, Any]:
    items = [classify_line(r, entity_graph=entity_graph, ownership_graph=ownership_graph) for r in row_reports or [] if isinstance(r, dict)]
    summary = {"closed_100": 0, "closed_by_strong_consensus": 0, "closed_with_warning": 0, "unresolved": 0}
    for item in items:
        st = str(item.get("closure_status") or "unresolved")
        summary[st] = int(summary.get(st, 0)) + 1
    return {"version": VERSION, "mode": "strict_but_realistic_line_closure", "summary": {"total": len(items), **summary}, "rows": items[:1200]}
