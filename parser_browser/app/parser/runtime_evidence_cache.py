from __future__ import annotations

"""Lightweight per-execution cache metadata (v61.0.41)."""

from dataclasses import dataclass, field
from typing import Any, Dict

VERSION = "v61.0.75-correction-output-contract-and-review-index"


@dataclass
class RuntimeEvidenceCache:
    values: Dict[str, Any] = field(default_factory=dict)
    hits: int = 0
    misses: int = 0

    def get(self, key: str, default: Any = None) -> Any:
        if key in self.values:
            self.hits += 1
            return self.values[key]
        self.misses += 1
        return default

    def set(self, key: str, value: Any) -> Any:
        self.values[key] = value
        return value

    def as_dict(self) -> Dict[str, Any]:
        return {"version": VERSION, "entries": len(self.values), "hits": self.hits, "misses": self.misses}
