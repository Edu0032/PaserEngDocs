from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple


def _norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^a-z0-9/%\.\s]+", " ", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s


def _contains_as_header_phrase(haystack: str, needle: str) -> bool:
    """Return True only for safe header phrase containment.

    v61.0.59: short aliases such as ``UN``/``UM`` must never match inside
    longer headers such as ``Valor Unit``.  Containment is still useful for
    variants like ``Valor Unit.`` or ``Custo Unitário (R$)``, but it must be
    bounded as a phrase/token match, not a raw substring match.
    """
    haystack = _norm(haystack)
    needle = _norm(needle)
    if not haystack or not needle or haystack == needle:
        return bool(haystack and needle and haystack == needle)
    # One/two-letter aliases are only safe on exact match.  This prevents
    # ``UN`` from capturing ``Valor Unit`` before the valor_unit alias is seen.
    if len(needle.replace(" ", "")) <= 2:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", haystack) is not None


def _best_match(header_cell: str, aliases: Dict[str, List[str]], min_similarity: float) -> Optional[str]:
    h = _norm(header_cell)
    if not h:
        return None

    normalized: List[Tuple[str, str]] = []
    for canonical, opts in aliases.items():
        for opt in opts:
            o = _norm(opt)
            if o:
                normalized.append((canonical, o))

    # 1) Exact matches are absolute and avoid dependence on alias order.
    for canonical, o in sorted(normalized, key=lambda item: len(item[1]), reverse=True):
        if h == o:
            return canonical

    # 2) Safe phrase containment.  Prefer the longest alias, so
    # ``valor unit`` beats any shorter incidental token.
    containment: List[Tuple[int, str]] = []
    for canonical, o in normalized:
        if _contains_as_header_phrase(h, o) or _contains_as_header_phrase(o, h):
            containment.append((len(o), canonical))
    if containment:
        containment.sort(reverse=True)
        return containment[0][1]

    # 3) Fuzzy fallback for OCR/header punctuation noise only.
    best_key = None
    best_score = 0.0
    for canonical, o in normalized:
        score = SequenceMatcher(None, h, o).ratio()
        if score > best_score:
            best_key, best_score = canonical, score

    if best_score >= float(min_similarity):
        return best_key
    return None


def resolve_header_map(
    header_cells: List[str],
    aliases: Dict[str, List[str]],
    required: List[str],
    min_similarity: float = 0.88,
) -> Tuple[Dict[str, int], List[str]]:
    mapping: Dict[str, int] = {}
    for idx, cell in enumerate(header_cells):
        key = _best_match(cell, aliases=aliases, min_similarity=min_similarity)
        if key and key not in mapping:
            mapping[key] = idx
    missing = [k for k in required if k not in mapping]
    return mapping, missing
