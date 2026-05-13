from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


@dataclass
class WordsPageCache:
    """Small in-memory cache for PyMuPDF page words.

    The SICRO lab runs multiple extraction profiles and two/three passes over the
    same page range. In Pyodide, calling ``page.get_text('words')`` repeatedly is
    one of the most expensive operations. This cache stores normalized raw word
    tuples per PDF/page so all engines share the same extraction result.
    """

    enabled: bool = True
    max_pages: int = 256
    _store: Dict[Tuple[str, int, int, int], List[Tuple[Any, ...]]] = field(default_factory=dict)
    hits: int = 0
    misses: int = 0

    def _fingerprint(self, pdf_path: str | Path) -> Tuple[str, int, int]:
        p = Path(str(pdf_path))
        try:
            stat = p.stat()
            return (str(p.resolve()), int(stat.st_size), int(stat.st_mtime_ns))
        except Exception:
            return (str(pdf_path), 0, 0)

    def get(self, pdf_path: str | Path, page_index: int) -> List[Tuple[Any, ...]] | None:
        if not self.enabled:
            return None
        fp = self._fingerprint(pdf_path)
        key = (fp[0], fp[1], fp[2], int(page_index))
        if key in self._store:
            self.hits += 1
            return list(self._store[key])
        self.misses += 1
        return None

    def set(self, pdf_path: str | Path, page_index: int, words: Iterable[Tuple[Any, ...]]) -> None:
        if not self.enabled:
            return
        if len(self._store) >= self.max_pages:
            # deterministic and cheap FIFO-ish eviction for browser memory safety
            first_key = next(iter(self._store.keys()))
            self._store.pop(first_key, None)
        fp = self._fingerprint(pdf_path)
        key = (fp[0], fp[1], fp[2], int(page_index))
        self._store[key] = [tuple(w) for w in words]

    def clear(self) -> None:
        self._store.clear()
        self.hits = 0
        self.misses = 0

    def report(self) -> Dict[str, Any]:
        return {"enabled": self.enabled, "pages": len(self._store), "hits": self.hits, "misses": self.misses}


GLOBAL_WORDS_CACHE = WordsPageCache()


def clear_global_words_cache() -> None:
    GLOBAL_WORDS_CACHE.clear()


def words_cache_report() -> Dict[str, Any]:
    return GLOBAL_WORDS_CACHE.report()
