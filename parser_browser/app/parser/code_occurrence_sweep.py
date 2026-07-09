from __future__ import annotations

"""Full PDF code+bank occurrence sweep planning.

The actual PDF scan is intentionally a late fallback executed by the browser
worker/normalizer.  This module only emits explicit targets so the light
extracted-evidence resolver remains separate from heavy document-wide search.
"""

from typing import Any, Dict, List

VERSION = "v61.0.75-correction-output-contract-and-review-index"


def build_full_pdf_code_bank_occurrence_targets(closure_report: Dict[str, Any], *, max_targets: int = 40) -> List[Dict[str, Any]]:
    targets: List[Dict[str, Any]] = []
    for row in closure_report.get("rows") or []:
        if not isinstance(row, dict):
            continue
        if row.get("row_status") == "closed_100":
            continue
        codigo = str(row.get("codigo") or "").strip()
        banco = str(row.get("banco") or "").strip()
        missing = list(row.get("missing_fields") or [])
        if not codigo or not missing:
            continue
        targets.append({
            "target_id": f"full_pdf_code_bank::{row.get('row_id')}",
            "strategy": "full_pdf_code_bank_occurrence_sweep",
            "family": row.get("family"),
            "row_id": row.get("row_id"),
            "path": row.get("path") or [],
            "codigo": codigo,
            "banco": banco,
            "item": row.get("item"),
            "missing_fields": missing,
            "search_scope": "entire_pdf_after_light_and_local_sweeps",
            "priority": "late_fallback",
            "reason": "mandatory_global_code_bank_occurrence_stage_after_light_cross_and_local_sweeps",
            "consensus_required": True,
            "identity_policy": "codigo_plus_banco_is_id",
        })
        if len(targets) >= max_targets:
            return targets
    return targets
