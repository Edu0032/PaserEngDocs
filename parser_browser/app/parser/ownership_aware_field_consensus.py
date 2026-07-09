from __future__ import annotations

"""Ownership-aware field consensus (v61.0.43).

Wraps the existing field consensus candidates with puzzle/ownership context.
The existing consensus remains the safe source of patches; this module upgrades
confidence and diagnostics when the same value is supported by owned physical
fragments or related budget entities.
"""

from typing import Any, Dict, List

VERSION = "v61.0.75-correction-output-contract-and-review-index"


def _clean(value: Any) -> str:
    return " ".join(str(value or "").replace("\u00a0", " ").split())


def enrich_consensus_with_ownership(consensus_report: Dict[str, Any] | None, ownership_graph: Dict[str, Any] | None, entity_graph: Dict[str, Any] | None = None) -> Dict[str, Any]:
    report = dict(consensus_report or {})
    fragments = list((ownership_graph or {}).get("fragments") or [])
    by_key_value_field = {}
    for frag in fragments:
        if not isinstance(frag, dict):
            continue
        key = (frag.get("key"), frag.get("field_hint"), _clean(frag.get("text")))
        by_key_value_field.setdefault(key, []).append(frag)
    enriched: List[Dict[str, Any]] = []
    for cand in report.get("candidates") or []:
        if not isinstance(cand, dict):
            continue
        key = f"{_clean(cand.get('codigo'))}|{_clean(cand.get('banco')).upper()}" if cand.get("codigo") else ""
        matches = by_key_value_field.get((key, cand.get("field"), _clean(cand.get("value")))) or []
        out = dict(cand)
        if matches:
            locked = any(m.get("ownership_status") == "locked" for m in matches)
            out["ownership_supported"] = True
            out["ownership_fragment_count"] = len(matches)
            out["evidence_grade"] = "ownership_aware_consensus_locked_fragment" if locked else "ownership_aware_consensus_candidate_fragment"
            out["confidence"] = min(0.995, float(out.get("confidence") or 0.0) + (0.06 if locked else 0.03))
            out.setdefault("evidence", {})["ownership_fragments"] = matches[:5]
        enriched.append(out)
    report["version"] = VERSION
    report["mode"] = "ownership_aware_field_consensus"
    report["candidates"] = enriched
    report["ownership_supported_candidates"] = sum(1 for c in enriched if c.get("ownership_supported"))
    return report
