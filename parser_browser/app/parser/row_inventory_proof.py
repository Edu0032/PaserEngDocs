from __future__ import annotations

"""Compact row-inventory proof for final real flow.

This module does not extract public values.  It reconciles the public JSON row
coverage with the compact PDF-first inventory/physical-block coverage generated
by existing tools.  Its goal is process proof: every known SINAPI-like row is
accounted for as locked, open/needs review, or outside the evaluated PDF scope.

It is intentionally not overly strict: when the PDF-first inventory was not run
for all blocks, the manifest reports that scope honestly instead of blocking
otherwise-correct results.  Blocking remains the job of coverage/quality gate
for missing critical public fields.
"""

from typing import Any, Dict, List

from app.config.version import CURRENT_RELEASE


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _inventory_blocks(result: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    evid = _as_dict(result.get("documento_evidencias"))
    inv = _as_dict(evid.get("from_scratch_block_inventory"))
    blocks = inv.get("blocks") if isinstance(inv.get("blocks"), list) else []
    out: Dict[str, Dict[str, Any]] = {}
    for b in blocks:
        if isinstance(b, dict) and b.get("key"):
            out[str(b.get("key"))] = b
    return out


def _coverage_blocks(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    evid = _as_dict(result.get("documento_evidencias"))
    cov = _as_dict(evid.get("physical_block_coverage"))
    blocks = cov.get("composition_manifests") if isinstance(cov.get("composition_manifests"), list) else []
    return [b for b in blocks if isinstance(b, dict)]


def build_row_inventory_proof(result: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    inv_blocks = _inventory_blocks(result)
    cov_blocks = _coverage_blocks(result)
    checked = 0
    physical_evaluated = 0
    complete = 0
    needs_review = 0
    not_physically_evaluated = 0
    physical_row_mismatch_count = 0
    open_rows = 0
    orphan_numeric_fragments = 0
    samples: List[Dict[str, Any]] = []

    for cov in cov_blocks:
        key = str(cov.get("key") or "")
        if not key:
            continue
        checked += 1
        locked = _int(cov.get("locked_rows"))
        open_count = _int(cov.get("open_rows"))
        expected = _int(cov.get("expected_rows"))
        orphan = _int(cov.get("orphan_numeric_fragments"))
        open_rows += open_count
        orphan_numeric_fragments += orphan
        inv = inv_blocks.get(key)
        physically_checked = bool(inv)
        if physically_checked:
            physical_evaluated += 1
        physical_rows = _int(inv.get("physical_row_count")) if inv else None
        rows_with_tail = _int(inv.get("rows_with_numeric_tail")) if inv else None
        physical_match = True
        if inv:
            # Under-count is the dangerous case: the PDF-first inventory saw
            # fewer line anchors than the public JSON has.  Over-count is kept
            # as review sample, but is not fatal by itself because it can be
            # caused by repeated auxiliary/global blocks or acceptable noise.
            physical_match = physical_rows >= expected and rows_with_tail >= min(locked, expected)
        else:
            not_physically_evaluated += 1
        status = "complete"
        reasons: List[str] = []
        if open_count:
            status = "needs_review"; reasons.append("open_rows")
        if orphan:
            status = "needs_review"; reasons.append("orphan_numeric_fragments")
        if inv and not physical_match:
            status = "needs_review"; reasons.append("physical_inventory_under_count")
            physical_row_mismatch_count += 1
        if not inv:
            # Honest scope marker, not a failure.  The JSON-level block coverage
            # can still be complete when no targeted/full PDF inventory was run.
            reasons.append("not_physically_reinventoried")
        if status == "complete":
            complete += 1
        else:
            needs_review += 1
        if (status != "complete" or not inv) and len(samples) < 80:
            samples.append({
                "key": key,
                "item": cov.get("item"),
                "coverage_status": cov.get("coverage_status"),
                "row_destination_status": status,
                "reasons": reasons,
                "json_expected_rows": expected,
                "json_locked_rows": locked,
                "json_open_rows": open_count,
                "physical_inventory_rows": physical_rows,
                "physical_rows_with_numeric_tail": rows_with_tail,
                "physically_evaluated": physically_checked,
            })
    scope = "none"
    if physical_evaluated and physical_evaluated == checked:
        scope = "full"
    elif physical_evaluated:
        scope = "targeted"
    overall = "complete" if needs_review == 0 and open_rows == 0 and orphan_numeric_fragments == 0 and physical_row_mismatch_count == 0 else "needs_review"
    manifest = {
        "version": CURRENT_RELEASE,
        "policy": "known_rows_must_be_locked_open_or_explicitly_outside_physical_inventory_scope",
        "summary": {
            "version": CURRENT_RELEASE,
            "composition_blocks_checked": checked,
            "composition_blocks_complete": complete,
            "composition_blocks_needs_review": needs_review,
            "physical_inventory_scope": scope,
            "physical_inventory_blocks_evaluated": physical_evaluated,
            "physical_inventory_blocks_not_evaluated": not_physically_evaluated,
            "json_open_rows": open_rows,
            "orphan_numeric_fragments": orphan_numeric_fragments,
            "physical_row_mismatch_count": physical_row_mismatch_count,
            "overall_status": overall,
            "not_overly_strict_note": "blocks outside the targeted/full PDF-first inventory are reported as scope gaps, not automatic extraction failures",
        },
        "needs_review_or_scope_samples": samples,
    }
    result.setdefault("documento_evidencias", {})["row_inventory_proof"] = manifest
    result.setdefault("meta", {}).setdefault("performance", {})["row_inventory_proof"] = dict(manifest["summary"])
    return manifest


def apply_row_inventory_proof(result: Dict[str, Any]) -> Dict[str, Any]:
    return build_row_inventory_proof(result)
