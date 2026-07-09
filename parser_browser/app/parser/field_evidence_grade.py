from __future__ import annotations

"""Evidence grading helpers for v61.0.40.

A public field can be considered closed only when its value is supported by a
traceable source.  Math-only values are useful as expectations, but are not
strong enough to become public JSON fields by themselves.
"""

from typing import Any, Dict, Iterable, List

VERSION = "v61.0.75-correction-output-contract-and-review-index"

PHYSICAL_SOURCES = {
    "deep_area_sweep",
    "normalizer_targeted_recovery",
    "full_pdf_code_bank_occurrence_sweep",
    "full_pdf_occurrence_consensus",
    "pdf_area_sweep",
    "physical_pdf_occurrence",
    "existing_extraction_or_cross",
    "initial_extraction",
}
CROSS_SOURCES = {
    "extracted_evidence_cross_resolver",
    "budget.main.composition",
    "budget.item",
    "sinapi_like.principais.principal",
    "sinapi_like.auxiliares_globais.principal",
    "sicro.principais.principal",
    "sicro.auxiliares_globais.principal",
}
MATH_ONLY_SOURCES = {"numeric_constraint_solver", "math_expected", "math_only_expected"}


def _source_text(evidence: Any) -> str:
    if isinstance(evidence, dict):
        parts: List[str] = []
        for key in ("source", "strategy", "reason", "rule"):
            if evidence.get(key):
                parts.append(str(evidence.get(key)))
        return " ".join(parts).lower()
    return str(evidence or "").lower()


def classify_evidence_grade(value: Any, *, evidence: Any = None, math_confirmed: bool = False, from_pdf: bool = False, from_cross: bool = False) -> str:
    if value in (None, ""):
        return "unresolved"
    source = _source_text(evidence)
    if from_pdf or any(s in source for s in PHYSICAL_SOURCES):
        return "physical_pdf_evidence_math_confirmed" if math_confirmed else "physical_pdf_evidence"
    if from_cross or any(s in source for s in CROSS_SOURCES):
        return "extracted_cross_evidence_math_confirmed" if math_confirmed else "extracted_cross_evidence"
    if any(s in source for s in MATH_ONLY_SOURCES):
        return "math_only_expected"
    if math_confirmed:
        return "math_confirmed_existing_value"
    return "weak_candidate"


def is_public_field_supported(grade: str) -> bool:
    return grade not in {"unresolved", "math_only_expected", "weak_candidate"}


def field_grade_record(field: str, value: Any, *, evidence: Any = None, math_status: Dict[str, Any] | None = None) -> Dict[str, Any]:
    math_confirmed = bool((math_status or {}).get("ok"))
    grade = classify_evidence_grade(value, evidence=evidence, math_confirmed=math_confirmed)
    return {
        "field": field,
        "value": value,
        "evidence_grade": grade,
        "public_supported": is_public_field_supported(grade),
        "math_confirmed": math_confirmed,
        "evidence": evidence or {},
    }
