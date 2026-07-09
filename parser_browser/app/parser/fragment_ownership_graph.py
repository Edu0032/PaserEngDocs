from __future__ import annotations

"""Fragment ownership graph (v61.0.43).

Assigns physical/extracted fragments to likely budget entities and locks the
fragments that belong to rows already closed by the closure engine.  This is a
lightweight graph for Pyodide: it works from the physical/document indexes and
entity graph rather than storing every character object.
"""

from typing import Any, Dict, List

VERSION = "v61.0.75-correction-output-contract-and-review-index"


def _clean(value: Any) -> str:
    return " ".join(str(value or "").replace("\u00a0", " ").split())


def build_fragment_ownership_graph(entity_graph: Dict[str, Any] | None, physical_index: Dict[str, Any] | None, closure_rows: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
    entity_graph = entity_graph if isinstance(entity_graph, dict) else {}
    physical_index = physical_index if isinstance(physical_index, dict) else {}
    status_by_key: Dict[str, str] = {}
    row_by_key: Dict[str, str] = {}
    for row in closure_rows or []:
        if not isinstance(row, dict):
            continue
        key = f"{_clean(row.get('codigo'))}|{_clean(row.get('banco')).upper()}" if row.get("codigo") else ""
        if key and row.get("row_status") in {"closed_100", "closed_by_strong_consensus"}:
            status_by_key[key] = str(row.get("row_status"))
            row_by_key[key] = str(row.get("row_id") or "")
    fragments: List[Dict[str, Any]] = []
    by_owner: Dict[str, List[str]] = {}
    for key, bucket in (physical_index.get("keys") or {}).items():
        if not isinstance(bucket, dict):
            continue
        candidate_entities = list((entity_graph.get("by_key") or {}).get(key) or [])
        locked = key in status_by_key
        for occ_idx, occ in enumerate(bucket.get("occurrences") or []):
            if not isinstance(occ, dict):
                continue
            fields = occ.get("fields_detected") if isinstance(occ.get("fields_detected"), dict) else {}
            for field, value in fields.items():
                if value in (None, ""):
                    continue
                fid = f"{key}:p{occ.get('page')}:o{occ_idx}:{field}:{abs(hash(str(value))) % 1000000}"
                owner = row_by_key.get(key) or (candidate_entities[0] if candidate_entities else key)
                frag = {
                    "fragment_id": fid,
                    "key": key,
                    "text": _clean(value),
                    "field_hint": field,
                    "page": occ.get("page"),
                    "bbox": occ.get("bbox") or [],
                    "raw_line_text": occ.get("line_text") or "",
                    "candidate_entities": candidate_entities[:12],
                    "candidate_owner": owner,
                    "ownership_status": "locked" if locked else "candidate",
                    "owner_confidence": 0.98 if locked else float(occ.get("confidence") or 0.74),
                    "source_zone": occ.get("source_zone") or "unknown",
                }
                fragments.append(frag)
                by_owner.setdefault(owner, []).append(fid)
    locked_count = sum(1 for f in fragments if f.get("ownership_status") == "locked")
    return {"version": VERSION, "mode": "fragment_ownership_graph", "fragment_count": len(fragments), "locked_count": locked_count, "candidate_count": len(fragments) - locked_count, "fragments": fragments[:1200], "by_owner": {k: v[:120] for k, v in by_owner.items()}}


def compact_fragment_ownership_graph(graph: Dict[str, Any], *, max_fragments: int = 80) -> Dict[str, Any]:
    if not isinstance(graph, dict):
        return {"version": VERSION, "fragment_count": 0, "locked_count": 0}
    return {"version": VERSION, "mode": graph.get("mode"), "fragment_count": graph.get("fragment_count", 0), "locked_count": graph.get("locked_count", 0), "candidate_count": graph.get("candidate_count", 0), "sample_fragments": list(graph.get("fragments") or [])[:max_fragments]}
