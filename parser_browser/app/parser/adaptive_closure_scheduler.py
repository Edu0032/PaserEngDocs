from __future__ import annotations

"""Adaptive closure scheduler (v61.0.41)."""

from typing import Any, Dict, Iterable, List

VERSION = "v61.0.75-correction-output-contract-and-review-index"


def classify_row_priority(row_report: Dict[str, Any]) -> str:
    if not isinstance(row_report, dict):
        return "P3"
    missing = list(row_report.get("missing_fields") or [])
    math_ok = bool((row_report.get("math_status") or {}).get("ok", True))
    row_status = str(row_report.get("row_status") or "")
    if row_status == "closed_100":
        return "P3"
    if missing:
        critical = {"descricao", "especificacao", "und", "quant", "valor_unit", "total", "custo_unitario_com_bdi", "custo_parcial"}
        if any(f in critical for f in missing):
            return "P0"
        return "P1"
    if not math_ok:
        return "P1"
    if any("description" in str(r) or "pollution" in str(r) for r in row_report.get("reasons") or []):
        return "P2"
    return "P3"


def build_adaptive_closure_schedule(row_reports: Iterable[Dict[str, Any]], *, max_rows: int = 400) -> Dict[str, Any]:
    buckets = {"P0": [], "P1": [], "P2": [], "P3": []}
    for row in list(row_reports or []):
        if not isinstance(row, dict):
            continue
        pr = classify_row_priority(row)
        entry = {
            "row_id": row.get("row_id"),
            "family": row.get("family"),
            "codigo": row.get("codigo"),
            "banco": row.get("banco"),
            "missing_fields": row.get("missing_fields") or [],
            "row_status": row.get("row_status"),
            "priority": pr,
            "recommended_actions": [],
        }
        if pr == "P0":
            entry["recommended_actions"] = ["field_consensus", "deep_area_sweep", "batch_code_bank_occurrence_index"]
        elif pr == "P1":
            entry["recommended_actions"] = ["numeric_expectation_search", "field_consensus", "deep_area_sweep"]
        elif pr == "P2":
            entry["recommended_actions"] = ["description_pollution_guard", "fragment_ownership_check"]
        else:
            entry["recommended_actions"] = ["protect_locked_evidence"]
        if len(buckets[pr]) < max_rows:
            buckets[pr].append(entry)
    return {
        "version": VERSION,
        "mode": "priority_based_closure_scheduler",
        "summary": {k: len(v) for k, v in buckets.items()},
        "buckets": buckets,
    }
