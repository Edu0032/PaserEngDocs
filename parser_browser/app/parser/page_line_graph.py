from __future__ import annotations

import re
from typing import Any, Dict, List

from app.parser.code_value_classifier import clean_text, norm_text, looks_like_code, looks_like_ptbr_decimal_or_money

VERSION = "v61.0.75-correction-output-contract-and-review-index"

_BANK_WORDS = {"SINAPI", "SICRO", "SICRO2", "SICRO3", "DNIT", "PROPRIO", "PRÓPRIO", "ANP", "CAIXA"}
_START_MARKERS = {"COMPOSICAO", "COMPOSIÇÃO", "INSUMO", "AUXILIAR"}


def _as_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _line_text(line: Dict[str, Any]) -> str:
    return clean_text((line or {}).get("text") or " ".join(str(w.get("text") or "") for w in (line or {}).get("words") or []))


def _tokens(text: Any) -> List[str]:
    return [t for t in norm_text(text).split() if t]


def _money_tokens(text: Any) -> List[str]:
    raw = str(text or "")
    return re.findall(r"(?<![A-Z0-9])\d{1,3}(?:\.\d{3})*,\d{2,7}(?![A-Z0-9])", raw, flags=re.I)


def _starts_with_budget_item(text: str) -> bool:
    return bool(re.match(r"^\s*\d+(?:\.\d+)+\s+", text)) or bool(re.match(r"^\s*\d+\s+[A-Z0-9./-]{2,}", text, flags=re.I))


def _contains_bank_near_start(tokens: List[str]) -> bool:
    return any(t in _BANK_WORDS for t in tokens[:5])


def _contains_probable_code_near_start(tokens: List[str]) -> bool:
    head = " ".join(tokens[:4])
    if not re.search(r"\d", head):
        return False
    # Codes may contain slash, dash, dot and letters.  Decimal/money tokens are not codes.
    for t in tokens[:4]:
        if looks_like_ptbr_decimal_or_money(t):
            continue
        if looks_like_code(t) or re.search(r"\d", t):
            return True
    return False


def line_barrier_reason(line: Dict[str, Any], *, family: str = "composition") -> str:
    """Return why a line is a hard boundary for broken-line recovery.

    This is intentionally based on structural signals that occur across documents:
    item hierarchy, code+bank near the start, control markers and financial columns.
    It does not depend on document-specific service names.
    """
    text = _line_text(line)
    if not text:
        return ""
    normalized = norm_text(text)
    toks = normalized.split()
    if not toks:
        return ""
    if toks[0] in _START_MARKERS:
        return "composition_control_marker"
    if family == "budget" and _starts_with_budget_item(text):
        return "budget_item_boundary"
    if _contains_bank_near_start(toks) and _contains_probable_code_near_start(toks):
        return "code_bank_boundary"
    nums = _money_tokens(text)
    if len(nums) >= 2:
        return "financial_values_boundary"
    return ""


def line_profile(line: Dict[str, Any], *, family: str = "composition") -> Dict[str, Any]:
    text = _line_text(line)
    words = list((line or {}).get("words") or [])
    xs = [_as_float(w.get("x0")) for w in words if _as_float(w.get("x0")) is not None]
    xe = [_as_float(w.get("x1")) for w in words if _as_float(w.get("x1")) is not None]
    ys = [_as_float(w.get("y0")) for w in words if _as_float(w.get("y0")) is not None]
    ye = [_as_float(w.get("y1")) for w in words if _as_float(w.get("y1")) is not None]
    tokens = _tokens(text)
    return {
        "text": text,
        "norm_text": norm_text(text),
        "token_count": len(tokens),
        "has_bank_near_start": _contains_bank_near_start(tokens),
        "has_probable_code_near_start": _contains_probable_code_near_start(tokens),
        "money_token_count": len(_money_tokens(text)),
        "barrier_reason": line_barrier_reason(line, family=family),
        "x0": round(min(xs), 3) if xs else _as_float((line or {}).get("x0")),
        "x1": round(max(xe), 3) if xe else _as_float((line or {}).get("x1")),
        "y0": round(min(ys), 3) if ys else _as_float((line or {}).get("y0")),
        "y1": round(max(ye), 3) if ye else _as_float((line or {}).get("y1")),
    }


def build_page_line_graph(lines: List[Dict[str, Any]], *, family: str = "composition") -> Dict[str, Any]:
    profiled = []
    for idx, line in enumerate(lines or []):
        item = line_profile(line, family=family)
        item["index"] = idx
        profiled.append(item)
    floating = [l for l in profiled if not l.get("barrier_reason") and l.get("text") and l.get("money_token_count", 0) == 0]
    barriers = [l for l in profiled if l.get("barrier_reason")]
    return {
        "version": VERSION,
        "family": family,
        "line_count": len(profiled),
        "barrier_count": len(barriers),
        "floating_fragment_count": len(floating),
        "lines": profiled,
        "barriers": barriers[:50],
        "floating_fragments": floating[:50],
    }
