from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Dict, Iterable, List

_VALID_UNIT_TOKENS = {
    "M", "M2", "M3", "M²", "M³", "KG", "G", "UN", "UND", "UNID", "UNID.", "MES", "M/MES",
    "M3XKM", "M2XKM", "%", "T", "H", "HA", "L", "CJ", "VB", "KM", "CM", "MM", "ML",
    "PÇ", "PCA", "PC", "PÇS", "PAR", "PARES",
}
_DIMENSION_RE = re.compile(r"\b\d+(?:[\.,]\d+)?\s*[Xx]\s*\d+(?:[\.,]\d+)?(?:\s*[Xx]\s*\d+(?:[\.,]\d+)?)?")


def normalize_unit(value: Any) -> str:
    return str(value or "").strip().upper().replace(" ", "")


def is_valid_unit_token(value: Any) -> bool:
    return normalize_unit(value) in _VALID_UNIT_TOKENS


def looks_like_dimension_context(text: str) -> bool:
    up = str(text or "").upper()
    return bool(
        _DIMENSION_RE.search(up)
        or re.search(r"\bDN\s*\d+\s*MM\b", up)
        or re.search(r"\b\d+\s*MM\s*X\s*\d+/?\d*\b", up)
        or re.search(r"\b\d+\s*CM\b", up)
    )


def _candidate_score(unit: str, *, source_score: float, mapped: bool, specification: str, current_unit: str = "") -> float:
    unit_norm = normalize_unit(unit)
    if not is_valid_unit_token(unit_norm):
        return -999.0
    score = float(source_score or 0.0)
    if mapped:
        score += 1.2
    if unit_norm in {normalize_unit(current_unit)} and current_unit:
        score += 0.3
    if unit_norm in {"UN", "UND", "UNID", "%", "H", "KG", "M", "M²", "M³", "M2", "M3", "MES", "M3XKM", "M2XKM"}:
        score += 0.35
    if unit_norm in {"CM", "MM"} and looks_like_dimension_context(specification):
        score -= 6.0
    return score


def resolve_unit_candidates(
    current_unit: str,
    candidates: Iterable[Dict[str, Any]],
    *,
    specification: str = "",
) -> Dict[str, Any]:
    scored: List[Dict[str, Any]] = []
    aggregate = defaultdict(float)
    current_norm = normalize_unit(current_unit)
    for cand in candidates:
        unit = normalize_unit(cand.get("unit"))
        mapped = bool(cand.get("mapped"))
        score = _candidate_score(unit, source_score=float(cand.get("score") or 0.0), mapped=mapped, specification=specification, current_unit=current_norm)
        if score <= -100:
            continue
        entry = {
            "unit": unit,
            "score": round(score, 3),
            "mapped": mapped,
            "strategy": cand.get("strategy"),
            "page_no": cand.get("page_no"),
        }
        scored.append(entry)
        aggregate[unit] += score
    scored.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
    if not aggregate:
        return {
            "unit_final": current_unit,
            "changed": False,
            "candidates": scored,
            "reason": "no_candidates",
        }
    best_unit, best_total = sorted(aggregate.items(), key=lambda kv: kv[1], reverse=True)[0]
    # se o melhor é unidade dimensional suspeita, mas existe alternativa não dimensional próxima,
    # priorizamos a alternativa mais plausível.
    if best_unit in {"CM", "MM"} and looks_like_dimension_context(specification):
        alternatives = [(u, s) for u, s in aggregate.items() if u not in {"CM", "MM"}]
        if alternatives:
            alt_unit, alt_score = sorted(alternatives, key=lambda kv: kv[1], reverse=True)[0]
            if alt_score >= best_total - 0.5:
                best_unit, best_total = alt_unit, alt_score
    changed = normalize_unit(best_unit) != current_norm and bool(best_unit)
    return {
        "unit_final": best_unit or current_unit,
        "changed": changed,
        "candidates": scored,
        "reason": "consensus" if changed else "kept_current_or_consensus_same",
        "aggregate_scores": dict(sorted(aggregate.items(), key=lambda kv: kv[1], reverse=True)),
    }
