from __future__ import annotations

"""Active re-extraction coordinator for mandatory real-flow recovery.

This is not a new independent extractor.  It coordinates existing tools using
coverage targets as the source of truth: if critical fields are missing after a
normal pass, run a focused layered recovery and record every attempt.  It keeps
public values PDF-declared only.
"""

from typing import Any, Dict, Tuple

from app.config.version import CURRENT_RELEASE
from app.core.pdf_session import PdfDocumentSession
from app.parser.coverage_engine import build_coverage_targets
from app.parser.physical_numeric_tail_recovery import apply_physical_numeric_tail_recovery
from app.parser.token_fidelity import apply_public_token_fidelity
from app.parser.composition_banded_closure import apply_banded_composition_closure


def _compact_targets(rep: Dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for t in (rep or {}).get("targets") or []:
        if not isinstance(t, dict):
            continue
        out.append({k: t.get(k) for k in ("target_type", "section", "block", "item", "row_group", "row_index", "codigo", "banco", "missing", "severity", "reason") if k in t})
    return out[:100]


def apply_active_reextraction_engine(
    result: Dict[str, Any],
    *,
    pdf_session: PdfDocumentSession,
    options: Dict[str, Any] | None = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    options = dict(options or {})
    report: Dict[str, Any] = {
        "version": CURRENT_RELEASE,
        "attempted": True,
        "policy": "coverage_targets_drive_layered_reextraction_existing_tools_only_pdf_declared_values",
        "layers": ["coverage", "same_row_or_block_numeric_tail", "token_fidelity", "banded_closure", "post_coverage"],
        "attempts": [],
    }
    pre = build_coverage_targets(result, phase="active_reextraction_pre")
    report["pre_target_count"] = int(pre.get("target_count") or 0)
    report["pre_blocking_target_count"] = int(pre.get("blocking_target_count") or 0)
    report["pre_targets_sample"] = _compact_targets(pre)

    if report["pre_blocking_target_count"] == 0:
        report["skipped"] = True
        report["reason"] = "no_blocking_coverage_targets"
        result.setdefault("meta", {}).setdefault("performance", {})["active_reextraction_engine"] = {k: v for k, v in report.items() if k != "pre_targets_sample"}
        result.setdefault("documento_evidencias", {})["active_reextraction_engine"] = report
        return result, report

    # Reuse existing robust tools; do not invent new field values here.
    try:
        result, tail = apply_physical_numeric_tail_recovery(result, pdf_session=pdf_session, options={**options, "mandatory_targeted": True, "skip_if_no_targets": False})
        report["attempts"].append({"tool": "physical_numeric_tail_recovery", "patches_applied": tail.get("patches_applied"), "blocking_unresolved": len(tail.get("blocking_unresolved") or [])})
    except Exception as exc:
        report["attempts"].append({"tool": "physical_numeric_tail_recovery", "error": str(exc), "exception_type": exc.__class__.__name__})
    try:
        result, tok = apply_public_token_fidelity(result, pdf_session=pdf_session, options={**options, "mandatory_targeted": True})
        report["attempts"].append({"tool": "public_token_fidelity", "patches_applied": tok.get("patches_applied"), "blocks_scanned": tok.get("blocks_scanned")})
    except Exception as exc:
        report["attempts"].append({"tool": "public_token_fidelity", "error": str(exc), "exception_type": exc.__class__.__name__})
    try:
        band = apply_banded_composition_closure(result, options)
        report["attempts"].append({"tool": "banded_composition_closure", "blocks_scanned": band.get("blocks_scanned"), "open_rows": band.get("open_rows")})
    except Exception as exc:
        report["attempts"].append({"tool": "banded_composition_closure", "error": str(exc), "exception_type": exc.__class__.__name__})

    post = build_coverage_targets(result, phase="active_reextraction_post")
    report["post_target_count"] = int(post.get("target_count") or 0)
    report["post_blocking_target_count"] = int(post.get("blocking_target_count") or 0)
    report["post_targets_sample"] = _compact_targets(post)
    report["resolved_blocking_targets"] = max(0, report["pre_blocking_target_count"] - report["post_blocking_target_count"])
    report["status"] = "ok" if report["post_blocking_target_count"] == 0 else "needs_review"
    result.setdefault("meta", {}).setdefault("performance", {})["active_reextraction_engine"] = {k: v for k, v in report.items() if k not in {"pre_targets_sample", "post_targets_sample", "attempts"}}
    result.setdefault("documento_evidencias", {})["active_reextraction_engine"] = report
    return result, report


def apply_active_reextraction_file(file_path: str, result: Dict[str, Any], options: Dict[str, Any] | None = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    from pathlib import Path
    with PdfDocumentSession(Path(file_path).read_bytes()) as sess:
        return apply_active_reextraction_engine(result, pdf_session=sess, options=options)


def apply_active_reextraction_bytes(pdf_bytes: bytes, result: Dict[str, Any], options: Dict[str, Any] | None = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    with PdfDocumentSession(pdf_bytes) as sess:
        return apply_active_reextraction_engine(result, pdf_session=sess, options=options)
