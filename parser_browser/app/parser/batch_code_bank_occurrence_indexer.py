from __future__ import annotations

"""Batch planning for mandatory code+bank PDF occurrence indexing (v61.0.41)."""

from collections import defaultdict
from typing import Any, Dict, Iterable, List

VERSION = "v61.0.75-correction-output-contract-and-review-index"


def build_batch_code_bank_occurrence_targets(closure_report: Dict[str, Any], *, max_keys: int = 80) -> List[Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = {}
    for row in closure_report.get("rows") or []:
        if not isinstance(row, dict):
            continue
        if row.get("row_status") == "closed_100":
            continue
        codigo = str(row.get("codigo") or "").strip()
        banco = str(row.get("banco") or "").strip()
        if not codigo:
            continue
        key = f"{codigo}|{banco.upper()}"
        bucket = grouped.setdefault(key, {"codigo": codigo, "banco": banco, "row_targets": [], "missing_fields": set(), "families": set(), "pages": set()})
        bucket["row_targets"].append({"row_id": row.get("row_id"), "path": row.get("path") or [], "family": row.get("family"), "collection": row.get("collection"), "group": row.get("group"), "item": row.get("item"), "missing_fields": row.get("missing_fields") or []})
        for f in row.get("missing_fields") or []:
            bucket["missing_fields"].add(str(f))
        if row.get("family"):
            bucket["families"].add(str(row.get("family")))
        if row.get("page") is not None:
            try:
                bucket["pages"].add(int(row.get("page")))
            except Exception:
                pass
    targets: List[Dict[str, Any]] = []
    for key, b in list(grouped.items())[:max_keys]:
        targets.append({
            "target_id": f"batch_full_pdf_code_bank::{key}",
            "strategy": "batch_full_pdf_code_bank_occurrence_index",
            "codigo": b["codigo"],
            "banco": b["banco"],
            "identity_policy": "codigo_plus_banco_is_id",
            "mandatory": True,
            "priority": "strategic_batch_index_after_initial_closure",
            "search_scope": "entire_pdf_once_per_codigo_banco",
            "missing_fields": sorted(b["missing_fields"]),
            "families": sorted(b["families"]),
            "source_pages": sorted(b["pages"]),
            "row_targets": b["row_targets"][:30],
            "row_target_count": len(b["row_targets"]),
        })
    return targets
