from __future__ import annotations

import io
import json
import os
import re
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


_PAGE_TEXT_CACHE_LIMIT = 32
_TABLES_CACHE_LIMIT = 16
_SLICE_CACHE_LIMIT = 16
_WORDS_CACHE_LIMIT = 32
_FRAGMENTS_CACHE_LIMIT = 32

def is_pyodide_runtime() -> bool:
    return sys.platform == "emscripten" or "pyodide" in sys.modules

def _cache_put(cache: dict, key, value, *, limit: int) -> None:
    cache[key] = value
    while len(cache) > max(1, int(limit)):
        try:
            cache.pop(next(iter(cache)))
        except StopIteration:
            break

# pdfplumber is also lazy-loaded so importing the parser package stays light in
# Pyodide/Lovable and in API paths that only need pypdf/docling seed structures.
pdfplumber = None
_PDFPLUMBER_IMPORT_ATTEMPTED = False


def _get_pdfplumber():  # pragma: no cover - optional dependency
    global pdfplumber, _PDFPLUMBER_IMPORT_ATTEMPTED
    if pdfplumber is not None:
        return pdfplumber
    if _PDFPLUMBER_IMPORT_ATTEMPTED:
        return None
    _PDFPLUMBER_IMPORT_ATTEMPTED = True
    if os.getenv('API_PDF_DISABLE_PDFPLUMBER', '0').strip().lower() in {'1', 'true', 'yes', 'on'}:
        return None
    try:
        import pdfplumber as _pdfplumber  # type: ignore
        pdfplumber = _pdfplumber
        return pdfplumber
    except Exception:
        pdfplumber = None
        return None


# PyMuPDF is deliberately lazy-loaded. Some malformed PDFs make MuPDF emit
# hundreds of non-fatal structure-tree warnings, and some environments spend a
# long time importing fitz. Browser/Pyodide does not support PyMuPDF anyway.
fitz = None
_FITZ_IMPORT_ATTEMPTED = False


def _get_fitz():  # pragma: no cover - optional dependency
    global fitz, _FITZ_IMPORT_ATTEMPTED
    if fitz is not None:
        return fitz
    if _FITZ_IMPORT_ATTEMPTED:
        return None
    _FITZ_IMPORT_ATTEMPTED = True
    if os.getenv('API_PDF_ENABLE_PYMUPDF', '0').strip().lower() not in {'1', 'true', 'yes', 'on'}:
        return None
    try:
        import fitz as _fitz  # type: ignore
        try:
            tools = getattr(_fitz, 'TOOLS', None)
            if tools is not None:
                for method_name in ('mupdf_display_errors', 'mupdf_display_warnings'):
                    method = getattr(tools, method_name, None)
                    if callable(method):
                        method(False)
        except Exception:
            pass
        fitz = _fitz
        return fitz
    except Exception:
        fitz = None
        return None



@contextmanager
def _silence_mupdf_stderr(enabled: bool = True):
    if not enabled or is_pyodide_runtime() or not hasattr(os, 'dup') or not hasattr(os, 'dup2'):
        yield
        return
    old_fd = None
    devnull_fd = None
    try:
        old_fd = os.dup(2)
        devnull_fd = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull_fd, 2)
        yield
    except Exception:
        yield
    finally:
        try:
            if old_fd is not None:
                os.dup2(old_fd, 2)
        except Exception:
            pass
        for fd in (devnull_fd, old_fd):
            try:
                if fd is not None:
                    os.close(fd)
            except Exception:
                pass

# pypdf is lazy-loaded because Pyodide and API metadata paths import this
# module before they actually need to parse PDF bytes.
PdfReader = None
PdfWriter = None


def _get_pypdf_classes():
    global PdfReader, PdfWriter
    if PdfReader is not None and PdfWriter is not None:
        return PdfReader, PdfWriter
    from pypdf import PdfReader as _PdfReader, PdfWriter as _PdfWriter
    PdfReader = _PdfReader
    PdfWriter = _PdfWriter
    return PdfReader, PdfWriter


@dataclass(frozen=True)
class PdfSliceInfo:
    start_1based: int
    end_1based: int


class PdfDocumentSession:
    """Cache leve por requisição para evitar reabrir/reler o mesmo PDF várias vezes."""

    def __init__(self, pdf_bytes: bytes, *, slice_info: PdfSliceInfo | None = None):
        self.pdf_bytes = pdf_bytes
        self.slice_info = slice_info
        self._reader: Optional[PdfReader] = None
        self._plumber: Optional[object] = None
        self._mupdf: Optional[object] = None
        self._page_count: Optional[int] = None
        self._page_text_cache: Dict[Tuple[str, int], str] = {}
        self._tables_cache: Dict[Tuple[int, str], List[List[List[str]]]] = {}
        self._pymupdf_tables_cache: Dict[Tuple[int, str], List[dict]] = {}
        self._words_cache: Dict[int, List[dict]] = {}
        self._slice_cache: Dict[Tuple[int, int], bytes] = {}
        self._pypdf_fragments_cache: Dict[int, List[dict]] = {}
        self._structured_tables_by_page: Dict[int, List[dict]] = {}

    def __enter__(self) -> "PdfDocumentSession":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    @property
    def page_count(self) -> int:
        if self._page_count is None:
            self._page_count = len(self.reader.pages)
        return self._page_count

    @property
    def reader(self) -> PdfReader:
        if self._reader is None:
            PdfReaderCls, _ = _get_pypdf_classes()
            self._reader = PdfReaderCls(io.BytesIO(self.pdf_bytes))
        return self._reader

    @property
    def plumber(self):
        plumber_mod = _get_pdfplumber()
        if plumber_mod is None:
            raise RuntimeError('pdfplumber indisponível neste ambiente.')
        if self._plumber is None:
            self._plumber = plumber_mod.open(io.BytesIO(self.pdf_bytes))
        return self._plumber

    @property
    def mupdf(self):
        fitz_mod = _get_fitz()
        if fitz_mod is None:
            raise RuntimeError('PyMuPDF indisponível ou desativado neste ambiente.')
        if self._mupdf is None:
            with _silence_mupdf_stderr(os.getenv('API_PDF_SUPPRESS_MUPDF_WARNINGS', '1').strip().lower() not in {'0','false','no','off'}):
                self._mupdf = fitz_mod.open(stream=self.pdf_bytes, filetype='pdf')
        return self._mupdf

    @property
    def has_pymupdf(self) -> bool:
        return _get_fitz() is not None

    @property
    def has_pdfplumber(self) -> bool:
        return _get_pdfplumber() is not None

    def close(self) -> None:
        if self._plumber is not None:
            try:
                self._plumber.close()
            except Exception:
                pass
        self._plumber = None
        if self._mupdf is not None:
            try:
                self._mupdf.close()
            except Exception:
                pass
        self._mupdf = None
        self._reader = None

    def get_page_text(self, page_no: int, *, engine: str = "auto") -> str:
        if page_no < 1 or page_no > self.page_count:
            raise ValueError(f"Página {page_no} fora do intervalo 1-{self.page_count}")
        resolved_engine = engine
        if resolved_engine == 'auto':
            resolved_engine = 'plumber' if self.has_pdfplumber else 'pypdf'
        if resolved_engine == 'plumber' and not self.has_pdfplumber:
            resolved_engine = 'pypdf'
        cache_key = (resolved_engine, page_no)
        cached = self._page_text_cache.get(cache_key)
        if cached is not None:
            return cached

        if resolved_engine == "plumber":
            text = self.plumber.pages[page_no - 1].extract_text() or ""
        elif resolved_engine == "pypdf":
            text = self.reader.pages[page_no - 1].extract_text() or ""
        else:
            raise ValueError(f"Engine de texto não suportada: {engine}")

        _cache_put(self._page_text_cache, cache_key, text, limit=_PAGE_TEXT_CACHE_LIMIT)
        return text

    def get_page_texts(self, start_1based: int, end_1based: int, *, engine: str = "auto") -> List[str]:
        if start_1based < 1 or end_1based < start_1based:
            raise ValueError("Intervalo de páginas inválido")
        if end_1based > self.page_count:
            raise ValueError(f"PDF tem {self.page_count} páginas, mas você pediu até {end_1based}")
        return [self.get_page_text(page_no, engine=engine) for page_no in range(start_1based, end_1based + 1)]

    def get_tables(self, page_no: int, *, table_settings: dict) -> List[List[List[str]]]:
        if page_no < 1 or page_no > self.page_count:
            raise ValueError(f"Página {page_no} fora do intervalo 1-{self.page_count}")
        if not self.has_pdfplumber:
            return []
        settings_key = json.dumps(table_settings, sort_keys=True, ensure_ascii=True)
        cache_key = (page_no, settings_key)
        cached = self._tables_cache.get(cache_key)
        if cached is not None:
            return cached
        tables = self.plumber.pages[page_no - 1].extract_tables(table_settings=table_settings) or []
        _cache_put(self._tables_cache, cache_key, tables, limit=_TABLES_CACHE_LIMIT)
        return tables

    def set_structured_tables(self, payload: dict | list | None) -> None:
        self._structured_tables_by_page = {}
        if payload is None:
            return
        if isinstance(payload, list):
            tables = payload
        else:
            raw_tables = (payload or {}).get("tables") or []
            tables = list(raw_tables.values()) if isinstance(raw_tables, dict) else raw_tables
        for raw in list(tables or []):
            if not isinstance(raw, dict):
                continue
            applies = raw.get("applies_to_range") or raw.get("page_range") or {}
            start = int(raw.get("page_start") or raw.get("page") or applies.get("start") or 0)
            end = int(raw.get("page_end") or applies.get("end") or start or 0)
            if start <= 0:
                continue
            normalized = dict(raw)
            normalized.setdefault("page_start", start)
            normalized.setdefault("page_end", end)
            for page_no in range(start, max(end, start) + 1):
                self._structured_tables_by_page.setdefault(page_no, []).append(normalized)

    def get_structured_tables(self, page_no: int, *, family: str | None = None) -> List[dict]:
        out = list(self._structured_tables_by_page.get(page_no) or [])
        if not family:
            return out
        family = str(family or "").strip().lower()
        filtered: List[dict] = []
        for table in out:
            table_family = str(table.get("family") or "").strip().lower()
            kind = str(table.get("kind") or "").strip().lower()
            if family == 'budget' and (table_family == 'budget' or kind == 'orcamento_sintetico'):
                filtered.append(table)
            elif family == 'composition' and (table_family in {'composition', 'sinapi_like'} or kind == 'composicao_sinapi_like'):
                filtered.append(table)
            elif family == 'sicro' and (table_family == 'sicro' or kind == 'composicao_sicro'):
                filtered.append(table)
        return filtered

    def get_pymupdf_tables(self, page_no: int, *, strategy: str = "lines") -> List[dict]:
        if page_no < 1 or page_no > self.page_count:
            raise ValueError(f"Página {page_no} fora do intervalo 1-{self.page_count}")
        if not self.has_pymupdf:
            return []
        cache_key = (page_no, str(strategy or "lines"))
        cached = self._pymupdf_tables_cache.get(cache_key)
        if cached is not None:
            return cached
        page = self.mupdf[page_no - 1]
        try:
            with _silence_mupdf_stderr(os.getenv('API_PDF_SUPPRESS_MUPDF_WARNINGS', '1').strip().lower() not in {'0','false','no','off'}):
                finder = page.find_tables(strategy=strategy or "lines")
        except Exception:
            _cache_put(self._pymupdf_tables_cache, cache_key, [], limit=_TABLES_CACHE_LIMIT)
            return []
        tables: List[dict] = []
        for table in getattr(finder, 'tables', []) or []:
            try:
                with _silence_mupdf_stderr(os.getenv('API_PDF_SUPPRESS_MUPDF_WARNINGS', '1').strip().lower() not in {'0','false','no','off'}):
                    rows = table.extract() or []
            except Exception:
                rows = []
            model = {
                'strategy': str(strategy or 'lines'),
                'bbox': list(getattr(table, 'bbox', ()) or ()),
                'row_count': int(getattr(table, 'row_count', 0) or 0),
                'col_count': int(getattr(table, 'col_count', 0) or 0),
                'rows': rows,
            }
            cells = getattr(table, 'cells', None)
            if cells is not None:
                model['cells'] = [list(cell) if isinstance(cell, (list, tuple)) else cell for cell in cells]
            try:
                hdr = getattr(getattr(table, 'header', None), 'names', None)
            except Exception:
                hdr = None
            if hdr:
                model['header_names'] = list(hdr)
            tables.append(model)
        _cache_put(self._pymupdf_tables_cache, cache_key, tables, limit=_TABLES_CACHE_LIMIT)
        return tables

    def get_words(self, page_no: int, *, x_tolerance: float = 1, y_tolerance: float = 2, keep_blank_chars: bool = False, use_text_flow: bool = True) -> List[dict]:
        if page_no < 1 or page_no > self.page_count:
            raise ValueError(f"Página {page_no} fora do intervalo 1-{self.page_count}")
        cached = self._words_cache.get(page_no)
        if cached is not None:
            return cached
        # Default to a no-hang browser-safe path. pdfplumber can be enabled for
        # local diagnostics, but Pyodide/Lovable does not need it and large PDFs
        # can stall while opening full page geometry.
        if os.getenv('API_PDF_ENABLE_PDFPLUMBER_WORDS', '0').strip().lower() in {'1', 'true', 'yes', 'on'}:
            plumber_mod = _get_pdfplumber()
            if plumber_mod is not None:
                try:
                    with plumber_mod.open(io.BytesIO(self.slice_bytes(page_no, page_no))) as single_page_pdf:
                        page = single_page_pdf.pages[0]
                        words = page.extract_words(
                            x_tolerance=x_tolerance,
                            y_tolerance=y_tolerance,
                            keep_blank_chars=keep_blank_chars,
                            use_text_flow=use_text_flow,
                        ) or []
                    _cache_put(self._words_cache, page_no, words, limit=_WORDS_CACHE_LIMIT)
                    return words
                except Exception:
                    pass
        # No positioned-word backend enabled. Return an empty list quickly; callers
        # will use the legacy text parser / pypdf fragments instead of stalling.
        words: List[dict] = []
        _cache_put(self._words_cache, page_no, words, limit=_WORDS_CACHE_LIMIT)
        return words


    def get_text_fragments(self, page_no: int) -> List[dict]:
        if page_no < 1 or page_no > self.page_count:
            raise ValueError(f"Página {page_no} fora do intervalo 1-{self.page_count}")
        cached = self._pypdf_fragments_cache.get(page_no)
        if cached is not None:
            return cached

        page = self.reader.pages[page_no - 1]
        page_height = float(page.mediabox.height or 0)
        fragments: List[dict] = []

        def _visitor_text(text, cm, tm, font_dict, font_size):
            raw = str(text or '')
            if not raw.strip():
                return
            x = float((tm[4] if len(tm) > 4 else 0) or 0)
            y = float((tm[5] if len(tm) > 5 else 0) or 0)
            top = page_height - y if page_height else 0.0
            fragments.append({
                'text': raw,
                'x0': x,
                'top': top,
                'font_size': float(font_size or 0),
            })

        try:
            page.extract_text(visitor_text=_visitor_text)
        except TypeError:
            # Compatibilidade defensiva com versões mais antigas do pypdf sem visitor_text
            _ = page.extract_text() or ''

        _cache_put(self._pypdf_fragments_cache, page_no, fragments, limit=_FRAGMENTS_CACHE_LIMIT)
        return fragments

    def slice_bytes(self, start_1based: int, end_1based: int) -> bytes:
        if start_1based < 1 or end_1based < start_1based:
            raise ValueError("Intervalo de páginas inválido")
        if end_1based > self.page_count:
            raise ValueError(f"PDF tem {self.page_count} páginas, mas você pediu até {end_1based}")
        cache_key = (start_1based, end_1based)
        cached = self._slice_cache.get(cache_key)
        if cached is not None:
            return cached

        _, PdfWriterCls = _get_pypdf_classes()
        writer = PdfWriterCls()
        for idx in range(start_1based - 1, end_1based):
            writer.add_page(self.reader.pages[idx])
        out = io.BytesIO()
        writer.write(out)
        result = out.getvalue()
        _cache_put(self._slice_cache, cache_key, result, limit=_SLICE_CACHE_LIMIT)
        return result

    def slice(self, start_1based: int, end_1based: int) -> "PdfDocumentSession":
        return PdfDocumentSession(
            self.slice_bytes(start_1based, end_1based),
            slice_info=PdfSliceInfo(start_1based=start_1based, end_1based=end_1based),
        )
