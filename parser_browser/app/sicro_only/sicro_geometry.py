from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from .sicro_engine import clean
from .sicro_words_cache import GLOBAL_WORDS_CACHE, words_cache_report


@dataclass(frozen=True)
class WordBox:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    block_no: int = 0
    line_no: int = 0
    word_no: int = 0

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2.0

    @property
    def height(self) -> float:
        return max(0.0, self.y1 - self.y0)

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2.0

    def as_tuple(self) -> Tuple[float, float, float, float, str]:
        return (self.x0, self.y0, self.x1, self.y1, self.text)


@dataclass
class Line:
    page: int
    y: float
    x0: float
    x1: float
    text: str
    words: List[Tuple[float, float, float, float, str]] = field(default_factory=list)
    bbox: Tuple[float, float, float, float] | None = None
    source: str = "pymupdf_words"
    line_index: int = 0

    def evidence(self) -> Dict[str, Any]:
        return {
            "page": self.page,
            "y": round(self.y, 2),
            "bbox": [round(v, 2) for v in (self.bbox or (self.x0, self.y, self.x1, self.y))],
            "source": self.source,
            "word_count": len(self.words),
            "line_index": self.line_index,
        }


def _import_fitz():
    try:
        import pymupdf as fitz  # type: ignore
        return fitz
    except Exception:
        import fitz  # type: ignore
        return fitz


def _wordboxes_from_raw(raw_words: Iterable[Tuple[Any, ...]]) -> List[WordBox]:
    boxes: List[WordBox] = []
    for raw in raw_words or []:
        # PyMuPDF words normally: x0, y0, x1, y1, text, block_no, line_no, word_no
        x0, y0, x1, y1, text = raw[:5]
        block_no = int(raw[5]) if len(raw) > 5 else 0
        line_no = int(raw[6]) if len(raw) > 6 else 0
        word_no = int(raw[7]) if len(raw) > 7 else 0
        t = clean(text)
        if not t:
            continue
        boxes.append(WordBox(float(x0), float(y0), float(x1), float(y1), t, block_no, line_no, word_no))
    return boxes


def _wordboxes_from_page(page: Any) -> List[WordBox]:
    return _wordboxes_from_raw(page.get_text("words") or [])


def adaptive_line_tolerance(words: Sequence[WordBox]) -> float:
    heights = [w.height for w in words if w.height > 0]
    if not heights:
        return 2.5
    h = median(heights)
    # SICRO tables often use small fonts; 0.45 median height captures words on the same baseline
    # without merging adjacent table rows. Keep a floor for noisy PDFs.
    return max(2.0, min(4.2, h * 0.45))


def words_to_lines(words: Sequence[WordBox], page_no: int, tolerance: float | None = None) -> List[Line]:
    if not words:
        return []
    tol = adaptive_line_tolerance(words) if tolerance is None else tolerance
    groups: List[Tuple[float, List[WordBox]]] = []
    for w in sorted(words, key=lambda w: (w.cy, w.x0)):
        if not groups or abs(groups[-1][0] - w.cy) > tol:
            groups.append((w.cy, [w]))
        else:
            base, bucket = groups[-1]
            bucket.append(w)
            # keep the representative baseline stable but responsive to OCR/text drift
            groups[-1] = ((base * (len(bucket) - 1) + w.cy) / len(bucket), bucket)
    lines: List[Line] = []
    for idx, (cy, bucket) in enumerate(groups):
        ordered = sorted(bucket, key=lambda w: (w.x0, w.word_no))
        text = clean(" ".join(w.text for w in ordered))
        if not text:
            continue
        bbox = (
            min(w.x0 for w in ordered),
            min(w.y0 for w in ordered),
            max(w.x1 for w in ordered),
            max(w.y1 for w in ordered),
        )
        lines.append(Line(
            page=page_no,
            y=float(cy),
            x0=float(bbox[0]),
            x1=float(bbox[2]),
            text=text,
            words=[w.as_tuple() for w in ordered],
            bbox=bbox,
            line_index=idx,
        ))
    return lines


def extract_pymupdf_lines(pdf_path: str | Path, start_page: int, end_page: int, tolerance: float | None = None) -> List[Line]:
    fitz = _import_fitz()
    doc = fitz.open(str(pdf_path))
    try:
        lines: List[Line] = []
        start = max(1, int(start_page))
        end = min(int(end_page), len(doc))
        for page_no in range(start, end + 1):
            page_index = page_no - 1
            raw_words = GLOBAL_WORDS_CACHE.get(pdf_path, page_index)
            if raw_words is None:
                page = doc[page_index]
                raw_words = [tuple(w) for w in (page.get_text("words") or [])]
                GLOBAL_WORDS_CACHE.set(pdf_path, page_index, raw_words)
            words = _wordboxes_from_raw(raw_words)
            lines.extend(words_to_lines(words, page_no, tolerance=tolerance))
        return lines
    finally:
        try:
            doc.close()
        except Exception:
            pass


def extract_pymupdf_text_lines(pdf_path: str | Path, start_page: int, end_page: int) -> List[Line]:
    """Diagnostic-only PyMuPDF text mode.

    It never becomes the winner over a zero-issue word-geometry result, but it is
    useful in the multi-engine report to spot divergences and missing blocks.
    """
    fitz = _import_fitz()
    doc = fitz.open(str(pdf_path))
    try:
        out: List[Line] = []
        start = max(1, int(start_page))
        end = min(int(end_page), len(doc))
        for page_no in range(start, end + 1):
            text = doc[page_no - 1].get_text("text") or ""
            for idx, raw in enumerate(text.splitlines()):
                t = clean(raw)
                if not t:
                    continue
                # No trustworthy bbox in text mode; expose source and line order only.
                out.append(Line(page=page_no, y=float(idx), x0=0.0, x1=0.0, text=t, words=[], bbox=None, source="pymupdf_text_diagnostic", line_index=idx))
        return out
    finally:
        try:
            doc.close()
        except Exception:
            pass


def union_bbox(lines: Iterable[Line]) -> Dict[str, Any]:
    selected = [ln for ln in lines if ln.bbox]
    if not selected:
        # preserve trace even for diagnostic engines without bboxes
        raw = [ln.evidence() for ln in lines]
        return {"source": raw[0]["source"] if raw else "unknown", "lines": raw} if raw else {}
    pages = sorted({ln.page for ln in selected})
    # For multi-page rows, expose per-line evidence and a union for the first page only.
    first_page = pages[0]
    first_page_lines = [ln for ln in selected if ln.page == first_page and ln.bbox]
    bbox = (
        min(ln.bbox[0] for ln in first_page_lines),
        min(ln.bbox[1] for ln in first_page_lines),
        max(ln.bbox[2] for ln in first_page_lines),
        max(ln.bbox[3] for ln in first_page_lines),
    )
    return {
        "source": selected[0].source,
        "pages": pages,
        "bbox_first_page": [round(v, 2) for v in bbox],
        "lines": [ln.evidence() for ln in selected],
    }


def smoke_test_pymupdf_pdf_bytes(pdf_path: str | Path, sample_page: int = 1) -> Dict[str, Any]:
    fitz = _import_fitz()
    pdf_bytes = Path(pdf_path).read_bytes()
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        page_no = max(1, min(sample_page, len(doc)))
        words = doc[page_no - 1].get_text("words")
        first = words[0] if words else None
        return {
            "ok": bool(words) and first is not None and len(first) >= 5,
            "pymupdf_version": getattr(fitz, "version", None),
            "page_count": len(doc),
            "sample_page": page_no,
            "word_count": len(words),
            "first_word_tuple_len": len(first) if first else 0,
            "can_open_pdf_from_bytes": True,
            "can_extract_words": bool(words),
            "words_cache": words_cache_report(),
        }
    finally:
        try:
            doc.close()
        except Exception:
            pass
