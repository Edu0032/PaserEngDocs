from __future__ import annotations

from typing import Any, Dict, List


def build_effective_column_bounds(column_schema: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return extraction bands using column x0 anchors.

    Columns marked as ignore_in_domain/structural_only must stay in the physical
    list because they delimit neighboring fields.
    """
    cols = []
    for col in list(column_schema or []):
        canonical = str(col.get("canonical_name") or col.get("canonical") or "").strip()
        if not canonical:
            continue
        x0 = col.get("x0")
        if x0 is None:
            continue
        try:
            x0f = float(x0)
        except (TypeError, ValueError):
            continue
        cols.append({**dict(col), "_x0": x0f})
    cols.sort(key=lambda c: (c["_x0"], int(c.get("physical_index") or 0)))
    out: List[Dict[str, Any]] = []
    for idx, col in enumerate(cols):
        x0 = float(col["_x0"])
        if idx + 1 < len(cols):
            x1 = float(cols[idx + 1]["_x0"])
        else:
            try:
                x1 = float(col.get("x1") or (x0 + float(col.get("width") or 24.0)))
            except Exception:
                x1 = x0 + 24.0
        if x1 <= x0:
            x1 = x0 + 1.0
        out.append({
            "canonical": str(col.get("canonical_name") or col.get("canonical") or ""),
            "physical_index": int(col.get("physical_index") or 0),
            "x0": round(x0, 3),
            "x1": round(x1, 3),
            "width": round(x1 - x0, 3),
            "ignore_in_domain": bool((col.get("metadata") or {}).get("ignore_in_domain") or col.get("ignore_in_domain")),
            "structural_only": bool((col.get("metadata") or {}).get("structural_only") or col.get("structural_only")),
            "source": (col.get("metadata") or {}).get("geometry_source") or col.get("geometry_source"),
        })
    return out
