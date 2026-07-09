from __future__ import annotations

"""Description ownership resolver.

The resolver answers a simple but critical question: when a description candidate
contains text around a target row, does that text really belong to the target or
to the neighbouring row above/below?

It is intentionally evidence-based and conservative.  It never needs a
hardcoded document title or service name: it compares candidates with the
already extracted descriptions for the target/previous/next rows and returns
ownership penalties/bonuses that other recovery stages can consume.
"""

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Tuple

from app.parser.broken_line_recovery import pollution_reason, similarity
from app.parser.code_value_classifier import clean_text, norm_text

VERSION = "v61.0.75-correction-output-contract-and-review-index"


@dataclass(frozen=True)
class NeighborDescription:
    role: str
    codigo: str = ""
    banco: str = ""
    descricao: str = ""
    confirmed_description: str = ""
    item: str = ""

    @property
    def best_description(self) -> str:
        return clean_text(self.confirmed_description or self.descricao)


def _clean(value: Any) -> str:
    return clean_text(value)


def _norm(value: Any) -> str:
    return norm_text(value)


def _tokens(value: Any) -> List[str]:
    return [t for t in _norm(value).split() if t]


def token_sequence_ratio(container: Any, part: Any) -> float:
    """Return how much of *part* appears as an ordered contiguous token span."""
    c = _tokens(container)
    p = _tokens(part)
    if not c or not p:
        return 0.0
    if len(p) > len(c):
        return 1.0 if " ".join(c) in " ".join(p) else 0.0
    best = 0
    for i in range(0, len(c) - len(p) + 1):
        hit = 0
        for a, b in zip(c[i : i + len(p)], p):
            if a == b:
                hit += 1
        best = max(best, hit)
        if hit == len(p):
            return 1.0
    return best / max(len(p), 1)


def contains_description(candidate: Any, description: Any, *, min_tokens: int = 3, min_ratio: float = 0.82) -> bool:
    candidate_s = _clean(candidate)
    desc_s = _clean(description)
    if not candidate_s or not desc_s:
        return False
    desc_tokens = _tokens(desc_s)
    if len(desc_tokens) < min_tokens:
        return False
    if _norm(desc_s) in _norm(candidate_s):
        return True
    return token_sequence_ratio(candidate_s, desc_s) >= min_ratio or similarity(candidate_s, desc_s) >= 0.92


def _neighbor_from_obj(obj: Any, role: str) -> NeighborDescription | None:
    if not isinstance(obj, dict):
        return None
    desc = _clean(obj.get("confirmed_description") or obj.get("descricao") or obj.get("especificacao") or obj.get("description") or "")
    if not desc:
        return None
    return NeighborDescription(
        role=role,
        codigo=_clean(obj.get("codigo") or obj.get("code") or ""),
        banco=_clean(obj.get("banco") or obj.get("fonte") or ""),
        descricao=_clean(obj.get("descricao") or obj.get("especificacao") or obj.get("description") or ""),
        confirmed_description=_clean(obj.get("confirmed_description") or obj.get("confirmed") or ""),
        item=_clean(obj.get("item") or ""),
    )


def parse_neighbor_context(context: Dict[str, Any] | None) -> List[NeighborDescription]:
    context = context or {}
    out: List[NeighborDescription] = []
    for role in ("prev", "previous", "above", "next", "below"):
        item = _neighbor_from_obj(context.get(role), "prev" if role in {"prev", "previous", "above"} else "next")
        if item is not None:
            out.append(item)
    # Also accept explicit lists for future callers.
    for role, values in (("prev", context.get("previous_candidates")), ("next", context.get("next_candidates"))):
        if isinstance(values, list):
            for v in values:
                item = _neighbor_from_obj(v, role)
                if item is not None:
                    out.append(item)
    return out


def ownership_report(
    candidate: Any,
    *,
    current_value: Any = "",
    target_confirmed: Any = "",
    neighbor_context: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Return ownership signals for a candidate.

    ``neighbor_hits`` means the candidate contains a confirmed/known description
    from the row above or below.  Those candidates must normally be rejected or
    strongly penalized because they are mixing row ownership.
    """
    cand = _clean(candidate)
    current = _clean(current_value)
    target_desc = _clean(target_confirmed)
    neighbors = parse_neighbor_context(neighbor_context)
    hits = []
    for n in neighbors:
        desc = n.best_description
        if desc and contains_description(cand, desc):
            hits.append({
                "role": n.role,
                "codigo": n.codigo,
                "banco": n.banco,
                "item": n.item,
                "description": desc,
                "similarity": round(similarity(cand, desc), 4),
            })
    current_inside = bool(current and contains_description(cand, current, min_tokens=2, min_ratio=0.86))
    target_inside = bool(target_desc and contains_description(cand, target_desc, min_tokens=3, min_ratio=0.86))
    starts_orphan = cand.lstrip().startswith("-")
    multi_af = len(re.findall(r"\bAF_\d{2}/\d{4}(?:_[A-Z]+)?\b", cand, flags=re.I)) >= 2
    polluted = pollution_reason(cand)
    score_delta = 0.0
    reasons: List[str] = []
    if hits:
        score_delta -= 2.5 + 1.0 * (len(hits) - 1)
        reasons.append("candidate_contains_neighbor_description")
    if starts_orphan:
        score_delta -= 0.9
        reasons.append("candidate_starts_with_orphan_fragment")
    if multi_af and not target_inside:
        score_delta -= 0.8
        reasons.append("candidate_has_multiple_service_anchors_without_target_confirmation")
    if polluted:
        score_delta -= 3.0
        reasons.append(f"pollution:{polluted}")
    if target_inside and not hits:
        score_delta += 1.15
        reasons.append("candidate_matches_target_confirmed_description")
    if current and cand and _norm(cand) == _norm(current):
        score_delta += 0.4
        reasons.append("candidate_preserves_current_value")
    return {
        "version": VERSION,
        "neighbor_hits": hits,
        "has_neighbor_hit": bool(hits),
        "current_inside_candidate": current_inside,
        "target_confirmed_inside_candidate": target_inside,
        "score_delta": round(score_delta, 4),
        "reasons": reasons,
        "safe_for_target": not hits and not polluted and not starts_orphan,
    }


def candidate_crosses_neighbor(candidate: Any, neighbor_context: Dict[str, Any] | None) -> bool:
    return bool(ownership_report(candidate, neighbor_context=neighbor_context).get("has_neighbor_hit"))


def choose_clean_subcandidate_from_current(current: Any, target_candidate: Any, neighbor_context: Dict[str, Any] | None) -> Dict[str, Any]:
    """Detect reverse repair: a clean target candidate lives inside polluted current.

    Example: current contains previous row + target + next row.  If the target
    candidate is clean and does not itself contain neighbour descriptions, it is
    a safe shorter replacement.
    """
    cur = _clean(current)
    cand = _clean(target_candidate)
    report = ownership_report(cand, current_value=cur, neighbor_context=neighbor_context)
    if not cur or not cand:
        return {"accepted": False, "reason": "empty"}
    if pollution_reason(cand) or report.get("has_neighbor_hit"):
        return {"accepted": False, "reason": "candidate_not_clean", "ownership": report}
    if _norm(cand) not in _norm(cur) and similarity(cur, cand) < 0.72:
        return {"accepted": False, "reason": "candidate_not_inside_current", "ownership": report}
    current_report = ownership_report(cur, current_value=cur, target_confirmed=cand, neighbor_context=neighbor_context)
    if not (current_report.get("has_neighbor_hit") or pollution_reason(cur) or cur.lstrip().startswith("-") or len(cur) > len(cand) + 45):
        return {"accepted": False, "reason": "current_not_proven_polluted", "ownership": current_report}
    return {
        "accepted": True,
        "reason": "reverse_repair_clean_candidate_inside_polluted_current",
        "candidate": cand,
        "ownership": current_report,
    }


def line_vertical_gap_profile(lines: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute document/page-relative vertical spacing thresholds."""
    ys: List[Tuple[float, float]] = []
    for line in lines or []:
        try:
            y0 = float(line.get("y0")); y1 = float(line.get("y1"))
        except Exception:
            continue
        ys.append((y0, y1))
    ys.sort()
    gaps = []
    for (_, prev_y1), (next_y0, _) in zip(ys, ys[1:]):
        gap = next_y0 - prev_y1
        if 0 <= gap < 80:
            gaps.append(gap)
    if not gaps:
        return {"median_gap": 8.0, "continuation_max_gap": 14.0, "item_gap_min": 18.0}
    gaps_sorted = sorted(gaps)
    median = gaps_sorted[len(gaps_sorted) // 2]
    small = sorted(g for g in gaps_sorted if g <= median) or [median]
    small_med = small[len(small) // 2]
    return {
        "median_gap": round(median, 3),
        "continuation_max_gap": round(max(8.0, small_med + 7.0, median * 1.75), 3),
        "item_gap_min": round(max(14.0, median * 2.15), 3),
    }


def cell_occupancy_ratio(text_bbox: Dict[str, Any] | None, band_x0: Any, band_x1: Any) -> float | None:
    try:
        bx0 = float(band_x0); bx1 = float(band_x1)
        tx0 = float((text_bbox or {}).get("x0")); tx1 = float((text_bbox or {}).get("x1"))
    except Exception:
        return None
    width = max(bx1 - bx0, 0.1)
    return round(max(0.0, min(1.5, (tx1 - tx0) / width)), 4)


def looks_complete_by_cell_occupancy(value: Any, occupancy: float | None) -> bool:
    text = _clean(value)
    if not text or occupancy is None:
        return False
    tail = (_norm(text).split() or [""])[-1]
    weak_tail = tail in {"DE", "DA", "DO", "DAS", "DOS", "PARA", "COM", "E", "EM", "A", "O"}
    if weak_tail:
        return False
    # Short descriptions that occupy less than about half the description cell
    # usually did not wrap; they should not attract neighbouring fragments.
    return occupancy <= 0.55 and len(text) >= 8 and not pollution_reason(text)
