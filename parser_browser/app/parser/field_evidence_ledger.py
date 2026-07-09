from __future__ import annotations

"""Evidence ledger used by the line certainty closure engine."""

from dataclasses import dataclass, field
from typing import Any, Dict, List

from app.parser.broken_line_recovery import codebank, pollution_reason, similarity, text_quality_score
from app.parser.code_value_classifier import clean_text, norm_text

VERSION = "v61.0.75-correction-output-contract-and-review-index"


@dataclass
class FieldEvidence:
    key: str
    field: str
    value: str
    source: str
    path: List[Any] = field(default_factory=list)
    confidence: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "field": self.field,
            "value": self.value,
            "source": self.source,
            "path": list(self.path),
            "confidence": round(float(self.confidence or 0.0), 4),
            "metadata": dict(self.metadata or {}),
        }


class FieldEvidenceLedger:
    def __init__(self) -> None:
        self._by_key_field: Dict[tuple[str, str], List[FieldEvidence]] = {}

    def add(self, codigo: Any, banco: Any, field: str, value: Any, *, source: str, path: List[Any] | None = None, confidence: float | None = None, metadata: Dict[str, Any] | None = None) -> None:
        key = codebank(str(codigo or ""), str(banco or ""))
        value_s = clean_text(value)
        if not key or not field or not value_s:
            return
        conf = float(confidence if confidence is not None else self._default_confidence(field, value_s, source))
        ev = FieldEvidence(key=key, field=field, value=value_s, source=source, path=list(path or []), confidence=conf, metadata=dict(metadata or {}))
        self._by_key_field.setdefault((key, field), []).append(ev)

    def _default_confidence(self, field: str, value: str, source: str) -> float:
        if field in {"descricao", "especificacao"}:
            if pollution_reason(value):
                return 0.15
            base = min(0.98, 0.45 + text_quality_score(value) / 5.0)
            if source.startswith("budget") or source.startswith("composition"):
                base += 0.08
            return min(0.99, base)
        return 0.86

    def candidates(self, key: str, field: str) -> List[FieldEvidence]:
        return list(self._by_key_field.get((key, field), []))

    def best(self, key: str, field: str, *, min_confidence: float = 0.70) -> FieldEvidence | None:
        candidates = [c for c in self.candidates(key, field) if c.confidence >= min_confidence]
        if not candidates:
            return None
        # Prefer repeated values and higher confidence.  Values are grouped by
        # normalized text so the same fact found in budget + composition wins.
        grouped: Dict[str, List[FieldEvidence]] = {}
        for c in candidates:
            grouped.setdefault(norm_text(c.value), []).append(c)
        scored: List[tuple[float, FieldEvidence]] = []
        for values in grouped.values():
            best = max(values, key=lambda x: x.confidence)
            sources = {v.source.split(".", 1)[0] for v in values}
            score = best.confidence + 0.18 * (len(values) - 1) + (0.22 if len(sources) >= 2 else 0.0)
            scored.append((score, best))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]

    def as_dict(self, *, limit: int = 200) -> Dict[str, Any]:
        entries = []
        for (key, field), values in self._by_key_field.items():
            for v in values[:8]:
                entries.append(v.as_dict())
                if len(entries) >= limit:
                    break
            if len(entries) >= limit:
                break
        return {"version": VERSION, "entries": entries, "entry_count": sum(len(v) for v in self._by_key_field.values())}
