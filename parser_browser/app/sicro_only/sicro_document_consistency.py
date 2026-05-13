from __future__ import annotations

"""Document-level SICRO consistency checks.

This module compares extracted SICRO analytical compositions with optional
references found in the synthetic budget. It is intentionally non-blocking:
auxiliary SICRO compositions often do not appear in the synthetic budget, and
description differences can be document inconsistencies rather than parser
errors. Numeric mismatches remain issues; description mismatches are warnings.
"""

import re
from decimal import Decimal
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List

from .sicro_engine import clean, key, parse_decimal
from .sicro_synthetic import SicroSyntheticReferenceExtractor, compare_compositions_with_synthetic


def _norm_text(value: Any) -> str:
    txt = clean(value)
    txt = re.sub(r"\s+", " ", txt)
    return txt.strip()


def _token_set(value: str) -> set[str]:
    return {t for t in re.split(r"[^0-9A-ZÀ-Ü]+", key(value)) if len(t) > 1}


def _text_similarity(a: str, b: str) -> Dict[str, Any]:
    a2, b2 = _norm_text(a), _norm_text(b)
    ka, kb = key(a2), key(b2)
    ratio = SequenceMatcher(None, ka, kb).ratio() if ka or kb else 1.0
    ta, tb = _token_set(a2), _token_set(b2)
    jaccard = (len(ta & tb) / len(ta | tb)) if (ta or tb) else 1.0
    return {"ratio": round(ratio, 4), "jaccard": round(jaccard, 4), "same_normalized": ka == kb}


def validate_document_consistency(
    result: Dict[str, Any],
    pdf_path: str | Path | None = None,
    synthetic_start_page: int = 1,
    synthetic_end_page: int = 6,
    description_ratio_threshold: float = 0.92,
    description_jaccard_threshold: float = 0.86,
) -> Dict[str, Any]:
    """Attach optional synthetic-budget consistency checks to a result.

    Returns a deep-ish updated object reference (mutates result in-place for
    speed and Pyodide friendliness). Numeric divergences are added as
    consistency issues. Description differences are warnings because the source
    document may genuinely disagree (e.g. Proctor normal vs intermediário).
    """
    refs: Dict[str, Dict[str, Any]] = {}
    if pdf_path is not None:
        try:
            refs = SicroSyntheticReferenceExtractor().extract_refs(pdf_path, synthetic_start_page, synthetic_end_page)
        except Exception as exc:  # pragma: no cover - defensive browser path
            result.setdefault("document_consistency", {})["extract_error"] = str(exc)
            refs = {}

    comparisons = compare_compositions_with_synthetic(result, refs) if refs else {"ok": True, "comparisons": {}, "issues": [], "reference_count": 0}
    warnings: List[Dict[str, Any]] = []
    issues: List[Dict[str, Any]] = []
    comps = result.get("composicoes") or {}
    for comp_key, comp in comps.items():
        principal = comp.get("principal") or {}
        code = str(principal.get("codigo") or "")
        ref = refs.get(code)
        comp_consistency: Dict[str, Any] = {"status": "sem_referencia_no_sintetico", "numeric_ok": None, "description_ok": None}
        if ref:
            cmp = (comparisons.get("comparisons") or {}).get(comp_key) or {}
            comp_consistency = {"status": cmp.get("status", "ok"), "reference": {k: v for k, v in ref.items() if not str(k).startswith("_")}}
            # Numeric status: existing compare_compositions function already checks
            # unit cost and quant*com_bdi=partial.
            numeric_issue = cmp.get("status") == "divergente"
            comp_consistency["numeric_ok"] = not numeric_issue
            if numeric_issue:
                issues.append({"type": "synthetic_numeric_divergence", "composition": comp_key, "details": cmp})
            sim = _text_similarity(ref.get("descricao"), principal.get("servico"))
            desc_ok = bool(sim.get("same_normalized")) or (sim["ratio"] >= description_ratio_threshold and sim["jaccard"] >= description_jaccard_threshold)
            comp_consistency["description_similarity"] = sim
            comp_consistency["description_ok"] = desc_ok
            if not desc_ok:
                warning = {
                    "type": "synthetic_description_divergence",
                    "composition": comp_key,
                    "codigo": code,
                    "synthetic_description": ref.get("descricao"),
                    "analytical_description": principal.get("servico"),
                    "values_match": not numeric_issue,
                    "similarity": sim,
                }
                warnings.append(warning)
                comp_consistency.setdefault("warnings", []).append(warning)
        comp["document_consistency"] = comp_consistency
        # Principal field scorer can use this lightweight numeric confirmation.
        if isinstance(principal, dict):
            principal["document_consistency"] = {k: v for k, v in comp_consistency.items() if k != "reference"}

    result["document_consistency"] = {
        "ok": not issues,
        "reference_count": len(refs),
        "synthetic_pages": [synthetic_start_page, synthetic_end_page],
        "issues": issues,
        "warnings": warnings,
        "comparisons": comparisons.get("comparisons") or {},
    }
    md = result.setdefault("metadata", {})
    md["document_consistency_ok"] = not issues
    md["document_consistency_warnings"] = len(warnings)
    md["document_consistency_issues"] = len(issues)
    md["synthetic_reference_count"] = len(refs)
    return result
