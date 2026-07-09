from __future__ import annotations

"""Annotate evidence entries with source authority and truth type.

No public values are changed here.  This module gives every final-flow consumer
one consistent interpretation of evidence vs. calculations: PDF-declared tokens
are public truth; calculations are audit-only and cannot overwrite public JSON.
"""

from typing import Any, Dict

from app.config.version import CURRENT_RELEASE


def _truth_type(entry: Dict[str, Any]) -> str:
    source = str(entry.get("source") or "").lower()
    status = str(entry.get("status") or "").lower()
    producer = str(entry.get("producer") or "").lower()
    if "calc" in source or "calculated" in status or "math" in producer:
        return "calculated_audit_only"
    if status in {"found", "applied_patch", "primary_physical_match"} or "pdf" in source or "physical" in source:
        return "pdf_declared"
    if status in {"not_found", "missing", "unknown"}:
        return "missing_or_unverified"
    return "supporting_evidence"


def _authority_rank(entry: Dict[str, Any]) -> int:
    section = str(entry.get("section") or "").lower()
    truth = entry.get("truth_type") or _truth_type(entry)
    if truth == "pdf_declared" and "composicoes" in section:
        return 100
    if truth == "pdf_declared" and "orcamento" in section:
        return 95
    if truth == "pdf_declared":
        return 90
    if truth == "supporting_evidence":
        return 50
    if truth == "calculated_audit_only":
        return 10
    return 0


def apply_evidence_conflict_resolver(result: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    evid = result.get("documento_evidencias") if isinstance(result.get("documento_evidencias"), dict) else {}
    registry = evid.get("evidence_registry") if isinstance(evid.get("evidence_registry"), dict) else {}
    fields = registry.get("field_registry") if isinstance(registry.get("field_registry"), list) else []
    truth_counts: Dict[str, int] = {}
    best_by_path: Dict[str, Dict[str, Any]] = {}
    for entry in fields:
        if not isinstance(entry, dict):
            continue
        truth = _truth_type(entry)
        entry["truth_type"] = truth
        entry["can_overwrite_public_value"] = False if truth == "calculated_audit_only" else bool(truth == "pdf_declared")
        entry["source_authority_rank"] = _authority_rank(entry)
        truth_counts[truth] = truth_counts.get(truth, 0) + 1
        path = str(entry.get("path") or "")
        if path:
            cur = best_by_path.get(path)
            if cur is None or int(entry.get("source_authority_rank") or 0) > int(cur.get("source_authority_rank") or 0):
                best_by_path[path] = entry
    report = {
        "version": CURRENT_RELEASE,
        "policy": "pdf_declared_values_are_public_truth_calculations_are_audit_only",
        "truth_type_counts": truth_counts,
        "field_paths_with_best_evidence": len(best_by_path),
        "authority_order": [
            "same_composition_block_band_pdf_declared",
            "same_budget_row_pdf_declared",
            "other_physical_pdf_supporting_evidence",
            "diagnostic_math_audit_only",
        ],
    }
    registry["conflict_resolution"] = report
    registry["truth_type_counts"] = truth_counts
    result.setdefault("documento_correcao", {})["evidence_conflict_resolution"] = report
    result.setdefault("meta", {}).setdefault("performance", {})["evidence_conflict_resolution"] = report
    return report
