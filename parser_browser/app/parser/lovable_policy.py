from __future__ import annotations
from typing import Any, Dict

VERSION = "v61.0.75-correction-output-contract-and-review-index"


def apply_lovable_consumption_policy(result: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(result, dict):
        return result
    result["lovable_consumption_policy"] = {
        "version": VERSION,
        "public_values_are_pdf_declared": True,
        "do_not_recalculate_public_totals": True,
        "do_not_overwrite_public_values_with_chain_math": True,
        "composition_math_is_audit_only": True,
        "budget_totals_are_pdf_declared": True,
        "if_composition_math_status_not_ok": "show_needs_review_do_not_recalculate_budget_item",
        "if_quality_gate_failed": "do_not_recalculate_or_replace_public_values",
        "extraction_status_meaning": "ok means parser extracted/owned visible PDF public fields faithfully",
        "document_consistency_status_meaning": "not ok means the PDF-declared values may be mathematically inconsistent; preserve public values and show review",
        "if_extraction_status_not_ok": "needs_review_parser_could_not_prove_all_critical_pdf_fields",
        "if_document_consistency_not_ok": "show_document_warning_but_do_not_overwrite_pdf_values",
        "allowed_uses_of_math": ["audit", "ranking_recovery_candidates", "validation", "review_message"],
        "forbidden_uses_of_math": ["overwrite_total", "overwrite_custo_parcial", "overwrite_custo_total", "overwrite_valor_unit"],
    }
    return result
