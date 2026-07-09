from __future__ import annotations

"""Generic code+bank physical occurrence search.

This helper is intentionally document-agnostic.  It is a small, reusable tool
for focused recovery stages: given a code/bank and a search scope, it returns
raw physical text windows where that pair appears.  Callers decide whether those
windows are authoritative for a specific field.  Public values are never written
by this module.
"""

import re
from typing import Any, Dict, Iterable, List, Tuple

from app.config.version import CURRENT_RELEASE
from app.core.pdf_session import PdfDocumentSession


def _clean(value: Any) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split()).strip()


def _norm(value: Any) -> str:
    import unicodedata
    text = _clean(value).upper()
    return "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))


def _code_regex(code: Any) -> str:
    text = _clean(code)
    if not text:
        return r"a^"
    parts: List[str] = []
    for ch in text:
        if ch.isspace():
            parts.append(r"\s*")
        elif ch in {"-", "/", "."}:
            parts.append(r"\s*" + re.escape(ch) + r"\s*")
        else:
            parts.append(re.escape(ch))
    return "".join(parts)


def _bank_regex(bank: Any) -> str:
    b = _norm(bank)
    if not b:
        return r"(?:SINAPI|Pr[óo]prio|PROPRIO|SICRO\s*3?|SICRO3|DNIT)?"
    if b in {"PROPRIO", "PRÓPRIO"}:
        return r"(?:Pr[óo]prio|PROPRIO|PRÓPRIO)"
    if b.startswith("SICRO"):
        return r"(?:SICRO\s*3?|SICRO3|DNIT)"
    return re.escape(_clean(bank))


def _window(text: str, center: int, left: int = 260, right: int = 900) -> str:
    return _clean(text[max(0, center - left): min(len(text), center + right)])


def _safe_pages(pdf_session: PdfDocumentSession, pages: Iterable[int] | None) -> List[int]:
    out: List[int] = []
    for p in list(pages or []):
        try:
            ip = int(p)
            if 1 <= ip <= pdf_session.page_count and ip not in out:
                out.append(ip)
        except Exception:
            pass
    return out


def search_code_bank_occurrences(
    pdf_session: PdfDocumentSession,
    *,
    code: Any,
    bank: Any = "",
    pages: Iterable[int] | None = None,
    all_pages_if_empty: bool = False,
    max_hits: int = 30,
    context_left: int = 260,
    context_right: int = 900,
) -> Dict[str, Any]:
    """Return physical text windows for code+bank occurrences.

    Search priority/scope is controlled by the caller.  For performance, this
    helper searches only the provided pages unless ``all_pages_if_empty`` is
    explicitly true.
    """
    selected = _safe_pages(pdf_session, pages)
    if not selected and all_pages_if_empty:
        selected = list(range(1, pdf_session.page_count + 1))
    code_pat = _code_regex(code)
    bank_pat = _bank_regex(bank)
    pair_pat = re.compile(code_pat + r"(?:\s+|.{0,45})" + bank_pat, flags=re.IGNORECASE | re.DOTALL)
    code_only_pat = re.compile(code_pat, flags=re.IGNORECASE)
    hits: List[Dict[str, Any]] = []
    for page in selected:
        try:
            text = pdf_session.get_page_text(page, engine="auto") or ""
        except Exception:
            continue
        for m in pair_pat.finditer(text):
            hits.append({
                "page": page,
                "match_type": "code_bank",
                "code": _clean(code),
                "bank": _clean(bank),
                "text": _window(text, m.start(), context_left, context_right),
                "confidence": 0.96,
            })
            if len(hits) >= max_hits:
                return {"version": CURRENT_RELEASE, "attempted": True, "hits": hits, "hit_count": len(hits), "pages": selected}
        # Soft fallback: code-only, but only after pair hits fail on that page.
        if not any(h.get("page") == page and h.get("match_type") == "code_bank" for h in hits):
            for m in code_only_pat.finditer(text):
                win = _window(text, m.start(), context_left, context_right)
                hits.append({
                    "page": page,
                    "match_type": "code_only",
                    "code": _clean(code),
                    "bank": _clean(bank),
                    "text": win,
                    "confidence": 0.78 if _norm(bank) and _norm(bank) in _norm(win) else 0.65,
                })
                if len(hits) >= max_hits:
                    return {"version": CURRENT_RELEASE, "attempted": True, "hits": hits, "hit_count": len(hits), "pages": selected}
    return {"version": CURRENT_RELEASE, "attempted": True, "hits": hits, "hit_count": len(hits), "pages": selected}
