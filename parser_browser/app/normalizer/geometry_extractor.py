from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass(slots=True)
class WordBox:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    page: int

    def as_dict(self) -> Dict[str, Any]:
        return {"text": self.text, "x0": round(self.x0, 3), "y0": round(self.y0, 3), "x1": round(self.x1, 3), "y1": round(self.y1, 3), "page": self.page}


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()


def _norm(value: Any) -> str:
    s = _clean(value).upper()
    accents = str.maketrans({'Á':'A','À':'A','Â':'A','Ã':'A','É':'E','Ê':'E','Í':'I','Ó':'O','Ô':'O','Õ':'O','Ú':'U','Ç':'C'})
    return s.translate(accents)


def extract_page_geometry(pdf_bytes: bytes) -> Dict[int, Dict[str, Any]]:
    """Extract words and line clusters using PyMuPDF.

    Coordinates are kept in PDF points. This runs server-side, not in Pyodide.
    """
    try:
        import fitz  # PyMuPDF
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(f"PyMuPDF indisponível para Normalizer API: {exc}") from exc
    pages: Dict[int, Dict[str, Any]] = {}
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        for idx, page in enumerate(doc, start=1):
            raw_words = page.get_text("words") or []
            words: List[WordBox] = []
            for w in raw_words:
                if len(w) < 5:
                    continue
                x0, y0, x1, y1, text = w[:5]
                txt = _clean(text)
                if not txt:
                    continue
                words.append(WordBox(txt, float(x0), float(y0), float(x1), float(y1), idx))
            lines = _cluster_lines(words)
            pages[idx] = {
                "page": idx,
                "width": float(page.rect.width),
                "height": float(page.rect.height),
                "words": [w.as_dict() for w in words],
                "lines": lines,
                "text": "\n".join(line.get("text", "") for line in lines),
            }
    finally:
        doc.close()
    return pages


def _cluster_lines(words: List[WordBox], *, y_tolerance: float = 3.0) -> List[Dict[str, Any]]:
    if not words:
        return []
    ordered = sorted(words, key=lambda w: (w.y0, w.x0))
    buckets: List[List[WordBox]] = []
    for word in ordered:
        if not buckets:
            buckets.append([word]); continue
        last = buckets[-1]
        avg_y = sum(w.y0 for w in last) / max(1, len(last))
        if abs(word.y0 - avg_y) <= y_tolerance:
            last.append(word)
        else:
            buckets.append([word])
    lines: List[Dict[str, Any]] = []
    for i, bucket in enumerate(buckets):
        bucket.sort(key=lambda w: w.x0)
        text = " ".join(w.text for w in bucket)
        lines.append({
            "line_index": i,
            "text": text,
            "norm_text": _norm(text),
            "x0": round(min(w.x0 for w in bucket), 3),
            "y0": round(min(w.y0 for w in bucket), 3),
            "x1": round(max(w.x1 for w in bucket), 3),
            "y1": round(max(w.y1 for w in bucket), 3),
            "word_count": len(bucket),
            "words": [w.as_dict() for w in bucket],
        })
    return lines


def find_text_bbox(page_geometry: Dict[str, Any], text: str) -> Dict[str, Any] | None:
    """Find an approximate bbox for a payload sample/header on a page.

    Prefer exact token-sequence match; fallback to line containing normalized text.
    """
    target = _norm(text)
    if not target:
        return None
    target_tokens = [t for t in target.split() if t]
    lines = list(page_geometry.get("lines") or [])
    for line in lines:
        words = list(line.get("words") or [])
        norm_words = [_norm(w.get("text")) for w in words]
        if target_tokens and len(target_tokens) <= len(norm_words):
            for i in range(0, len(norm_words) - len(target_tokens) + 1):
                if norm_words[i:i+len(target_tokens)] == target_tokens:
                    matched = words[i:i+len(target_tokens)]
                    return {
                        "text": " ".join(w.get("text", "") for w in matched),
                        "x0": round(min(float(w.get("x0", 0)) for w in matched), 3),
                        "y0": round(min(float(w.get("y0", 0)) for w in matched), 3),
                        "x1": round(max(float(w.get("x1", 0)) for w in matched), 3),
                        "y1": round(max(float(w.get("y1", 0)) for w in matched), 3),
                        "line_text": line.get("text", ""),
                        "match_type": "token_sequence",
                    }
        if target in str(line.get("norm_text") or ""):
            # If exact sequence failed, return full line bbox but mark lower confidence.
            return {
                "text": text,
                "x0": line.get("x0"), "y0": line.get("y0"), "x1": line.get("x1"), "y1": line.get("y1"),
                "line_text": line.get("text", ""), "match_type": "line_contains",
            }
    return None
