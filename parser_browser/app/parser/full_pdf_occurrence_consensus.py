from __future__ import annotations

"""Consensus layer for full-PDF code+bank occurrence candidates (v61.0.40).

The browser worker/normalizer may return many candidate patches from document-wide
search.  This module groups them by row+field and only keeps candidates with
repeatable evidence or strong physical confidence.
"""

from collections import defaultdict
from typing import Any, Dict, Iterable, List, Tuple

from app.parser.field_patch_validators import validate_patch_candidate

VERSION = "v61.0.75-correction-output-contract-and-review-index"


def _key(p: Dict[str, Any]) -> Tuple[str, str, str]:
    return (str(p.get("row_id") or p.get("target_id") or ""), str(p.get("field") or ""), str(p.get("value") or ""))


def build_occurrence_consensus(patches: Iterable[Dict[str, Any]], *, min_confidence: float = 0.82) -> Dict[str, Any]:
    groups: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = defaultdict(list)
    for patch in patches or []:
        if not isinstance(patch, dict):
            continue
        if patch.get("strategy") != "full_pdf_code_bank_occurrence_sweep" and patch.get("source") not in {"full_pdf_code_bank_occurrence_sweep", "full_pdf_occurrence_consensus"}:
            continue
        groups[_key(patch)].append(patch)
    accepted: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for (row_id, field, value), items in groups.items():
        confidences = [float(i.get("confidence") or 0.0) for i in items]
        pages = sorted({i.get("page") for i in items if i.get("page") is not None})
        avg_conf = sum(confidences) / max(1, len(confidences))
        validation = validate_patch_candidate(field, value, {}, {})
        repeatable = len(items) >= 2 or len(pages) >= 2
        strong_single = avg_conf >= 0.94 and len(items) == 1
        consensus_score = min(0.99, avg_conf + (0.04 if repeatable else 0.0))
        record = {
            "row_id": row_id,
            "field": field,
            "value": value,
            "occurrence_count": len(items),
            "pages": pages,
            "confidence": round(consensus_score, 3),
            "source": "full_pdf_occurrence_consensus",
            "strategy": "full_pdf_code_bank_occurrence_sweep",
            "evidence": {"occurrences": items[:20], "repeatable": repeatable, "strong_single": strong_single},
            "validation": validation,
        }
        if validation.get("ok") and consensus_score >= min_confidence and (repeatable or strong_single):
            accepted.append(record)
        else:
            record["reason"] = "insufficient_consensus_or_invalid_candidate"
            rejected.append(record)
    return {"version": VERSION, "accepted": accepted, "rejected": rejected, "accepted_count": len(accepted), "rejected_count": len(rejected)}
