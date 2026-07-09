from __future__ import annotations

"""Deep area sweep recovery plan.

The actual geometric sweep runs in the Pyodide recovery agent when it receives a
mini-PDF.  This module creates precise, high-priority targets from the closure
engine so the worker can spend more time on the few rows that still failed to
close.
"""

from typing import Any, Dict, List

VERSION = "v61.0.75-correction-output-contract-and-review-index"


def build_deep_area_sweep_targets(closure_report: Dict[str, Any], *, max_targets: int = 80) -> List[Dict[str, Any]]:
    targets: List[Dict[str, Any]] = []
    for row in closure_report.get("rows") or []:
        if not isinstance(row, dict):
            continue
        if row.get("row_status") == "closed_100":
            continue
        missing = list(row.get("missing_fields") or [])
        if not missing:
            continue
        page = row.get("page") or row.get("pagina_inicio")
        if not page:
            continue
        for field in missing[:5]:
            targets.append({
                "target_id": f"closure::{row.get('row_id')}::{field}",
                "path": row.get("path") or [],
                "family": row.get("family"),
                "table_family": "budget" if row.get("family") == "budget" else "composition",
                "field": field,
                "codigo": row.get("codigo"),
                "banco": row.get("banco"),
                "item": row.get("item"),
                "page": page,
                "reason": "line_certainty_unclosed_field",
                "current_value": row.get("current_value") or "",
                "row_group": row.get("group"),
                "scan_mode": "deep_area_sweep_local",
                "priority": 0,
                "closure_status": row.get("row_status"),
            })
            if len(targets) >= max_targets:
                return targets
    return targets
