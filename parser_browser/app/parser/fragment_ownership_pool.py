from __future__ import annotations

"""Lightweight ownership pool for confirmed textual fragments.

The current browser parser does not persist every PyMuPDF word in the final JSON.
This module still provides useful ownership guarantees by registering confirmed
row descriptions/fields and checking whether a candidate for one row contains a
confirmed fragment owned by another row.
"""

from dataclasses import dataclass
from typing import Any, Dict, List

from app.parser.description_ownership_resolver import contains_description
from app.parser.code_value_classifier import clean_text, norm_text

VERSION = "v61.0.75-correction-output-contract-and-review-index"


@dataclass
class OwnedFragment:
    owner_id: str
    field: str
    text: str
    confidence: float
    path: List[Any]

    def as_dict(self) -> Dict[str, Any]:
        return {"owner_id": self.owner_id, "field": self.field, "text": self.text, "confidence": round(self.confidence, 4), "path": list(self.path)}


class FragmentOwnershipPool:
    def __init__(self) -> None:
        self.fragments: List[OwnedFragment] = []

    def register(self, owner_id: str, field: str, text: Any, *, confidence: float = 1.0, path: List[Any] | None = None) -> None:
        text_s = clean_text(text)
        if not owner_id or not text_s or len(norm_text(text_s).split()) < 3:
            return
        self.fragments.append(OwnedFragment(owner_id=owner_id, field=field, text=text_s, confidence=float(confidence), path=list(path or [])))

    def foreign_hits(self, candidate: Any, owner_id: str) -> List[Dict[str, Any]]:
        cand = clean_text(candidate)
        if not cand:
            return []
        hits: List[Dict[str, Any]] = []
        for frag in self.fragments:
            if frag.owner_id == owner_id:
                continue
            if frag.confidence < 0.90:
                continue
            if contains_description(cand, frag.text, min_tokens=3, min_ratio=0.86):
                hits.append(frag.as_dict())
        return hits

    def as_dict(self, *, limit: int = 120) -> Dict[str, Any]:
        return {"version": VERSION, "owned_count": len(self.fragments), "owned_preview": [f.as_dict() for f in self.fragments[:limit]]}
