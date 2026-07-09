from __future__ import annotations

"""Final integrity orchestrator for the real browser/Lovable flow.

This module is intentionally thin: it does not duplicate extraction logic.  It
coordinates the existing recovery/validation tools in the real final flow so a
mandatory tool cannot exist only in tests and be skipped by the exported bundle.

Global policy (not document-specific):
- public numeric fields are PDF-declared tokens;
- math ranks/validates recovery candidates, but never creates public values;
- mandatory recovery failures are surfaced in the quality gate, not swallowed as
  harmless warnings;
- budget totals may be reassigned to the semantic owner, never replaced by a
  recalculated chain sum.
"""

from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Tuple

from app.config.version import CURRENT_RELEASE
from app.core.output_compact import refresh_quality_gate_after_repairs, prune_runtime_only_fields
from app.parser.budget_total_ownership import apply_budget_total_ownership_repair
from app.parser.lovable_policy import apply_lovable_consumption_policy
from app.parser.public_numeric_evidence import (
    build_public_numeric_evidence_bytes,
    build_public_numeric_evidence_file,
)
from app.parser.final_quality_metrics import apply_final_quality_metrics
from app.parser.token_fidelity import apply_public_token_fidelity_bytes, apply_public_token_fidelity_file
from app.parser.composition_banded_closure import apply_banded_composition_closure
from app.parser.clean_final_contract import apply_clean_final_contract
from app.parser.evidence_registry import apply_evidence_registry
from app.parser.coverage_engine import build_coverage_targets
from app.parser.from_scratch_block_inventory import build_from_scratch_block_inventory_file, build_from_scratch_block_inventory_bytes
from app.parser.active_reextraction_engine import apply_active_reextraction_file, apply_active_reextraction_bytes
from app.parser.evidence_conflict_resolver import apply_evidence_conflict_resolver
from app.parser.extraction_consistency_status import apply_extraction_consistency_status
from app.parser.physical_block_coverage import apply_physical_block_coverage_manifest
from app.parser.row_inventory_proof import apply_row_inventory_proof
from app.parser.compact_correction_document import apply_compact_correction_document
from app.parser.budget_total_lines import apply_budget_total_lines
from app.parser.light_reextraction_diff_scan import build_light_reextraction_diff_scan_file, build_light_reextraction_diff_scan_bytes
from app.parser.physical_numeric_tail_recovery import (
    apply_physical_numeric_tail_recovery_bytes,
    apply_physical_numeric_tail_recovery_file,
)


def _is_gate_blocking(result: Dict[str, Any]) -> bool:
    gate = ((result.get("auditoria_final") or {}).get("quality_gate") or {}) if isinstance(result.get("auditoria_final"), dict) else {}
    if not isinstance(gate, dict) or not gate:
        return False
    return bool(not gate.get("ok", True) or int(gate.get("blocking_issue_count") or 0) > 0)


def _add_mandatory_failure(result: Dict[str, Any], *, stage: str, exc: Exception) -> None:
    """Record mandatory-stage failure as a final blocking issue.

    Previous versions sometimes converted mandatory recovery errors into normal
    warnings.  That allowed stale JSON to look deliverable.  This helper keeps
    the JSON generated for inspection, but the gate cannot become ok.
    """
    issue = {
        "code": "mandatory_integrity_orchestrator_failed",
        "severity": "blocking",
        "blocks_json_ok": True,
        "stage": stage,
        "message": str(exc),
        "exception_type": exc.__class__.__name__,
        "version": CURRENT_RELEASE,
    }
    result.setdefault("documento_correcao", {}).setdefault("warnings", []).append({"tipo": "mandatory_integrity_orchestrator_failed", **issue})
    gate = result.setdefault("auditoria_final", {}).setdefault("quality_gate", {})
    issues = gate.setdefault("issues", [])
    if isinstance(issues, list):
        issues.append(issue)
    gate["ok"] = False
    gate["version"] = CURRENT_RELEASE
    gate["blocking_issue_count"] = int(gate.get("blocking_issue_count") or 0) + 1
    sev = gate.setdefault("severity_summary", {})
    if isinstance(sev, dict):
        sev["blocking"] = int(sev.get("blocking") or 0) + 1
    result["status"] = "quality_gate_failed"


def _stamp_version(result: Dict[str, Any]) -> None:
    meta = result.setdefault("meta", {})
    if isinstance(meta, dict):
        meta["parser_version"] = CURRENT_RELEASE
        meta["config_schema_version"] = CURRENT_RELEASE
    doc = result.setdefault("documento_correcao", {})
    if isinstance(doc, dict):
        doc["versao"] = CURRENT_RELEASE
    gate = ((result.get("auditoria_final") or {}).get("quality_gate") or {}) if isinstance(result.get("auditoria_final"), dict) else {}
    if isinstance(gate, dict):
        gate["version"] = CURRENT_RELEASE
    pol = result.get("lovable_consumption_policy")
    if isinstance(pol, dict):
        pol["version"] = CURRENT_RELEASE


def _finalize_status(result: Dict[str, Any]) -> None:
    gate = ((result.get("auditoria_final") or {}).get("quality_gate") or {}) if isinstance(result.get("auditoria_final"), dict) else {}
    if isinstance(gate, dict) and gate and (not gate.get("ok", True) or int(gate.get("blocking_issue_count") or 0) > 0):
        result["status"] = "quality_gate_failed"
    else:
        result["status"] = "ok"


def run_final_integrity_orchestrator(
    result: Dict[str, Any],
    *,
    file_path: str | None = None,
    pdf_bytes: bytes | None = None,
    options: Dict[str, Any] | None = None,
    perf_key: str = "final_integrity_orchestrator",
    prune_runtime: bool = True,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Run mandatory final integrity tools in one real-flow stage.

    The function is generic and document-independent.  It only asks existing
    recovery tools to operate on the supplied PDF and final result.  It is safe
    to call multiple times; each call recomputes the quality gate after patches.
    """
    out: Dict[str, Any] = result if isinstance(result, dict) else {}
    options = dict(options or {})
    report: Dict[str, Any] = {
        "version": CURRENT_RELEASE,
        "attempted": True,
        "perf_key": perf_key,
        "input_gate_blocking": _is_gate_blocking(out),
        "stages": [],
        "errors": [],
    }
    coverage_target_blocks: list[str] = []

    # 0) Coverage targets.  Before any repair, enumerate missing/uncertain
    # public fields as explicit targets.  This proves that the flow is not
    # waiting for a later report to notice an extraction gap.
    try:
        pre_targets = build_coverage_targets(out, phase="pre_recovery")
        for target in pre_targets.get("targets") or []:
            if isinstance(target, dict) and target.get("block"):
                block_key = str(target.get("block"))
                if block_key not in coverage_target_blocks:
                    coverage_target_blocks.append(block_key)
        report["stages"].append({"name": "coverage_engine_pre_recovery", "report": {k: v for k, v in pre_targets.items() if k != "targets"}})
    except Exception as exc:
        report["errors"].append({"stage": "coverage_engine_pre_recovery", "message": str(exc), "exception_type": exc.__class__.__name__})
        _add_mandatory_failure(out, stage="coverage_engine_pre_recovery", exc=exc)

    # 0b) PDF-first compact inventory.  This is an extraction-safety step, not
    # a public-value writer: it scans known composition blocks from the PDF
    # itself and records whether physical row anchors/numeric tails are visible.
    try:
        inventory_options = {**options, "from_scratch_inventory_full_scan": bool((options.get("accuracy_profile") or {}).get("from_scratch_inventory_full_scan") if isinstance(options.get("accuracy_profile"), dict) else False)}
        if coverage_target_blocks and not inventory_options.get("target_blocks") and not inventory_options.get("target_compositions"):
            inventory_options["target_blocks"] = coverage_target_blocks
        if file_path:
            inventory_report = build_from_scratch_block_inventory_file(file_path, out, inventory_options)
        elif pdf_bytes:
            inventory_report = build_from_scratch_block_inventory_bytes(pdf_bytes, out, inventory_options)
        else:
            inventory_report = {"attempted": False, "skipped": True, "reason": "no_pdf_available"}
        inv_summary = inventory_report.get("summary") if isinstance(inventory_report, dict) else inventory_report
        report["stages"].append({"name": "from_scratch_block_inventory", "report": inv_summary})
    except Exception as exc:
        report["errors"].append({"stage": "from_scratch_block_inventory", "message": str(exc), "exception_type": exc.__class__.__name__})
        _add_mandatory_failure(out, stage="from_scratch_block_inventory", exc=exc)

    # 1) Physical numeric recovery.  The recovery tool itself decides which
    # targets are required from quality-gate/correction/math evidence.  It never
    # invents public values: it writes only physical PDF tokens.
    try:
        recovery_options = {**options, "mandatory_targeted": True, "skip_if_no_targets": True}
        if file_path:
            out, numeric_tail_report = apply_physical_numeric_tail_recovery_file(file_path, out, recovery_options)
        elif pdf_bytes:
            out, numeric_tail_report = apply_physical_numeric_tail_recovery_bytes(pdf_bytes, out, recovery_options)
        else:
            numeric_tail_report = {"attempted": False, "skipped": True, "reason": "no_pdf_available"}
        report["stages"].append({"name": "physical_numeric_tail_recovery", "report": numeric_tail_report})
    except Exception as exc:
        report["errors"].append({"stage": "physical_numeric_tail_recovery", "message": str(exc), "exception_type": exc.__class__.__name__})
        _add_mandatory_failure(out, stage="physical_numeric_tail_recovery", exc=exc)

    # 2) Token fidelity.  After any missing-tail recovery, walk SINAPI-like
    # rows and restore exact physical tokens (for example 1 -> 1,0000000 or
    # 1134 -> 1.134,00) when the same numeric value exists in the PDF row.
    try:
        token_options = {**options, "mandatory_targeted": True}
        if file_path:
            out, token_report = apply_public_token_fidelity_file(file_path, out, token_options)
        elif pdf_bytes:
            out, token_report = apply_public_token_fidelity_bytes(pdf_bytes, out, token_options)
        else:
            token_report = {"attempted": False, "skipped": True, "reason": "no_pdf_available"}
        report["stages"].append({"name": "public_token_fidelity", "report": token_report})
    except Exception as exc:
        report["errors"].append({"stage": "public_token_fidelity", "message": str(exc), "exception_type": exc.__class__.__name__})
        _add_mandatory_failure(out, stage="public_token_fidelity", exc=exc)

    # 3) Banded closure audit.  The parser already used Docling/Normalizer
    # bands during extraction; this stage makes final row/fragment ownership
    # explicit after recovery and token-fidelity passes.
    try:
        band_report = apply_banded_composition_closure(out, options)
        report["stages"].append({"name": "banded_composition_closure", "report": band_report})
    except Exception as exc:
        report["errors"].append({"stage": "banded_composition_closure", "message": str(exc), "exception_type": exc.__class__.__name__})
        _add_mandatory_failure(out, stage="banded_composition_closure", exc=exc)

    # 2) Budget subtotal ownership.  This preserves the exact PDF token while
    # assigning it to the hierarchy level whose descendants explain it.
    try:
        out, budget_owner_report = apply_budget_total_ownership_repair(out)
        report["stages"].append({"name": "budget_total_ownership_repair", "report": budget_owner_report})
    except Exception as exc:
        report["errors"].append({"stage": "budget_total_ownership_repair", "message": str(exc), "exception_type": exc.__class__.__name__})
        _add_mandatory_failure(out, stage="budget_total_ownership_repair", exc=exc)

    # Refresh gate before evidence so stale pre-recovery target blocks do not
    # make the evidence pass report a targeted snapshot as if it were global.
    try:
        pre_evidence_gate = refresh_quality_gate_after_repairs(out)
        report["quality_gate_before_evidence"] = deepcopy(pre_evidence_gate)
    except Exception as exc:
        report["errors"].append({"stage": "refresh_quality_gate_before_evidence", "message": str(exc), "exception_type": exc.__class__.__name__})
        _add_mandatory_failure(out, stage="refresh_quality_gate_before_evidence", exc=exc)

    # 2b) Coverage after recovery/ownership.  Remaining blocking targets are
    # extraction coverage failures; math-only targets with all fields present
    # become document-consistency warnings later.
    try:
        post_targets = build_coverage_targets(out, phase="post_recovery")
        report["stages"].append({"name": "coverage_engine_post_recovery", "report": {k: v for k, v in post_targets.items() if k != "targets"}})
    except Exception as exc:
        report["errors"].append({"stage": "coverage_engine_post_recovery", "message": str(exc), "exception_type": exc.__class__.__name__})
        _add_mandatory_failure(out, stage="coverage_engine_post_recovery", exc=exc)

    # 2c) Active re-extraction engine.  If coverage still has blocking targets,
    # coordinate the existing tools in layers.  This stage is a no-op when
    # post-recovery coverage is already complete, and records why.
    try:
        if file_path:
            out, active_report = apply_active_reextraction_file(file_path, out, options)
        elif pdf_bytes:
            out, active_report = apply_active_reextraction_bytes(pdf_bytes, out, options)
        else:
            active_report = {"attempted": False, "skipped": True, "reason": "no_pdf_available"}
        report["stages"].append({"name": "active_reextraction_engine", "report": {k: v for k, v in active_report.items() if k not in {"pre_targets_sample", "post_targets_sample", "attempts"}}})
    except Exception as exc:
        report["errors"].append({"stage": "active_reextraction_engine", "message": str(exc), "exception_type": exc.__class__.__name__})
        _add_mandatory_failure(out, stage="active_reextraction_engine", exc=exc)

    # 3) Evidence-first public numeric ledger.  This does not change SICRO and
    # does not invent values: it proves public budget/SINAPI-like numeric fields
    # against physical PDF text whenever a PDF is available.
    try:
        evidence_options = {**options, "mandatory_targeted": True}
        if file_path:
            out, public_evidence_report = build_public_numeric_evidence_file(file_path, out, evidence_options)
        elif pdf_bytes:
            out, public_evidence_report = build_public_numeric_evidence_bytes(pdf_bytes, out, evidence_options)
        else:
            public_evidence_report = {"attempted": False, "skipped": True, "reason": "no_pdf_available"}
        report["stages"].append({"name": "public_numeric_evidence", "report": public_evidence_report})
    except Exception as exc:
        report["errors"].append({"stage": "public_numeric_evidence", "message": str(exc), "exception_type": exc.__class__.__name__})
        _add_mandatory_failure(out, stage="public_numeric_evidence", exc=exc)

    # 4) Lovable policy.  Contract metadata must always be present in the real
    # output so downstream UI never treats chain math as a public overwrite.
    try:
        apply_lovable_consumption_policy(out)
        report["stages"].append({"name": "lovable_consumption_policy", "applied": True})
    except Exception as exc:
        report["errors"].append({"stage": "lovable_consumption_policy", "message": str(exc), "exception_type": exc.__class__.__name__})
        _add_mandatory_failure(out, stage="lovable_consumption_policy", exc=exc)

    # Central evidence registry.  Build one normalized evidence source after
    # public evidence, token fidelity, physical recovery and banded closure have
    # produced their own reports.  Later validators and Lovable can inspect this
    # registry instead of reconciling several tool-specific formats.
    try:
        registry_report = apply_evidence_registry(out, options)
        report["stages"].append({"name": "evidence_registry", "report": {k: v for k, v in registry_report.items() if k not in {"field_registry", "row_lock_registry"}}})
    except Exception as exc:
        report["errors"].append({"stage": "evidence_registry", "message": str(exc), "exception_type": exc.__class__.__name__})
        _add_mandatory_failure(out, stage="evidence_registry", exc=exc)

    # Clean stale/pre-repair diagnostics from the public final contract.
    try:
        clean_report = apply_clean_final_contract(out)
        report["stages"].append({"name": "clean_final_contract", "report": clean_report})
    except Exception as exc:
        report["errors"].append({"stage": "clean_final_contract", "message": str(exc), "exception_type": exc.__class__.__name__})
        _add_mandatory_failure(out, stage="clean_final_contract", exc=exc)

    # Rebuild registry after cleaning so it reflects the public final contract,
    # not stale pre-repair snapshots.
    try:
        registry_report_after_clean = apply_evidence_registry(out, options)
        report["stages"].append({"name": "evidence_registry_after_clean", "report": {k: v for k, v in registry_report_after_clean.items() if k not in {"field_registry", "row_lock_registry"}}})
    except Exception as exc:
        report["errors"].append({"stage": "evidence_registry_after_clean", "message": str(exc), "exception_type": exc.__class__.__name__})
        _add_mandatory_failure(out, stage="evidence_registry_after_clean", exc=exc)

    # 4b) Compact physical-block coverage.  Every known SINAPI-like composition
    # block and budget leaf is summarized so no row/field can be left behind
    # silently, without carrying raw page text into the final JSON.
    try:
        block_coverage = apply_physical_block_coverage_manifest(out)
        report["stages"].append({"name": "physical_block_coverage", "report": block_coverage.get("summary") if isinstance(block_coverage, dict) else block_coverage})
    except Exception as exc:
        report["errors"].append({"stage": "physical_block_coverage", "message": str(exc), "exception_type": exc.__class__.__name__})
        _add_mandatory_failure(out, stage="physical_block_coverage", exc=exc)


    # 4bb) Budget declared total lines.  Expose total geral/meta/submeta totals
    # as display-friendly declared lines without changing hierarchy semantics or
    # recalculating values.
    try:
        total_lines_report = apply_budget_total_lines(out)
        report["stages"].append({"name": "budget_total_lines", "report": total_lines_report})
    except Exception as exc:
        report["errors"].append({"stage": "budget_total_lines", "message": str(exc), "exception_type": exc.__class__.__name__})
        _add_mandatory_failure(out, stage="budget_total_lines", exc=exc)

    # 4bc) Lightweight PDF-vs-JSON anchor sweep.  This looks for code/bank
    # anchors present in PDF text but missing from public JSON.  It is diagnostic
    # only, compact, and never writes public values.
    try:
        if file_path:
            diff_scan_report = build_light_reextraction_diff_scan_file(file_path, out, options)
        elif pdf_bytes:
            diff_scan_report = build_light_reextraction_diff_scan_bytes(pdf_bytes, out, options)
        else:
            diff_scan_report = {"attempted": False, "skipped": True, "reason": "no_pdf_available"}
        report["stages"].append({"name": "light_reextraction_diff_scan", "report": {k: v for k, v in diff_scan_report.items() if k != "potential_missing_samples"}})
    except Exception as exc:
        report["errors"].append({"stage": "light_reextraction_diff_scan", "message": str(exc), "exception_type": exc.__class__.__name__})
        _add_mandatory_failure(out, stage="light_reextraction_diff_scan", exc=exc)

    # 4d) Row inventory proof.  This compact manifest reconciles known JSON rows
    # with PDF-first inventory scope and physical-block coverage.  It reports
    # scope gaps without being so rigid that correct targeted results are lost.
    try:
        row_inventory = apply_row_inventory_proof(out)
        report["stages"].append({"name": "row_inventory_proof", "report": row_inventory.get("summary") if isinstance(row_inventory, dict) else row_inventory})
    except Exception as exc:
        report["errors"].append({"stage": "row_inventory_proof", "message": str(exc), "exception_type": exc.__class__.__name__})
        _add_mandatory_failure(out, stage="row_inventory_proof", exc=exc)

    # 4c) Resolve evidence authority/truth type.  This does not alter public
    # values; it marks PDF-declared tokens as public truth and calculations as
    # audit-only evidence.
    try:
        conflict_report = apply_evidence_conflict_resolver(out)
        report["stages"].append({"name": "evidence_conflict_resolver", "report": conflict_report})
    except Exception as exc:
        report["errors"].append({"stage": "evidence_conflict_resolver", "message": str(exc), "exception_type": exc.__class__.__name__})
        _add_mandatory_failure(out, stage="evidence_conflict_resolver", exc=exc)

    # 5) Final quality metrics make the real-flow effect visible in the JSON.
    try:
        metrics = apply_final_quality_metrics(out)
        report["quality_metrics_before_gate"] = metrics
    except Exception as exc:
        report["errors"].append({"stage": "final_quality_metrics", "message": str(exc), "exception_type": exc.__class__.__name__})
        _add_mandatory_failure(out, stage="final_quality_metrics", exc=exc)

    # 6) Refresh gate after every patch and stamp version after compact stages.
    try:
        gate = refresh_quality_gate_after_repairs(out)
        report["quality_gate_after"] = deepcopy(gate)
    except Exception as exc:
        report["errors"].append({"stage": "refresh_quality_gate_after_repairs", "message": str(exc), "exception_type": exc.__class__.__name__})
        _add_mandatory_failure(out, stage="refresh_quality_gate_after_repairs", exc=exc)

    # 6b) Separate parser extraction fidelity from document consistency.
    # A mathematically wrong PDF can still be faithfully extracted; these
    # statuses make that distinction explicit for Lovable and audits.
    try:
        status_report = apply_extraction_consistency_status(out)
        report["stages"].append({"name": "extraction_vs_document_consistency", "report": {
            "extraction_ok": status_report.get("extraction_status", {}).get("ok"),
            "extraction_issue_count": status_report.get("extraction_status", {}).get("critical_issue_count"),
            "document_consistency_ok": status_report.get("document_consistency_status", {}).get("ok"),
            "document_consistency_issue_count": status_report.get("document_consistency_status", {}).get("issue_count"),
        }})
    except Exception as exc:
        report["errors"].append({"stage": "extraction_vs_document_consistency", "message": str(exc), "exception_type": exc.__class__.__name__})
        _add_mandatory_failure(out, stage="extraction_vs_document_consistency", exc=exc)

    # The quality gate recomputation intentionally rebuilds current issues from
    # the public JSON.  Mandatory orchestration failures are execution failures,
    # not public-field issues, so re-apply them after the gate refresh so they
    # cannot be erased and the final JSON cannot be marked ok.
    for err in report.get("errors") or []:
        try:
            _add_mandatory_failure(out, stage=str(err.get("stage") or "unknown"), exc=RuntimeError(str(err.get("message") or err)))
        except Exception:
            pass

    # Preserve applied cascade repairs produced by the existing line-certainty
    # and closure tools.  The integrity orchestrator must not erase evidence
    # documents created by earlier real-flow stages.
    try:
        evid = out.setdefault("documento_evidencias", {})
        cascade = evid.setdefault("cascade_repairs", {})
        if not cascade.get("applied_repairs"):
            perf = (out.get("meta") or {}).get("performance") or {}
            for rep_key in (
                "line_certainty_closure_after_recovery",
                "line_certainty_closure_after_physical_index",
                "line_certainty_closure_after_output_contract_flow",
                "line_certainty_closure_engine",
            ):
                rep = perf.get(rep_key) if isinstance(perf, dict) else None
                repairs = (rep or {}).get("repairs") if isinstance(rep, dict) else None
                applied = [r for r in (repairs or []) if isinstance(r, dict) and r.get("applied", True)]
                if applied:
                    cascade["applied_repairs"] = applied
                    cascade.setdefault("source", rep_key)
                    break
    except Exception:
        pass

    _stamp_version(out)
    out.setdefault("meta", {}).setdefault("performance", {})[perf_key] = report
    out.setdefault("analise_orcamentaria", {}).setdefault("debug_recovery", {})["final_integrity_orchestrator"] = report
    if prune_runtime:
        out = prune_runtime_only_fields(out)
        _stamp_version(out)
        # prune_runtime_only_fields recomputes the public gate from fields and
        # can therefore erase execution-level mandatory failures.  Re-apply
        # those failures after pruning as well.
        for err in report.get("errors") or []:
            try:
                _add_mandatory_failure(out, stage=str(err.get("stage") or "unknown"), exc=RuntimeError(str(err.get("message") or err)))
            except Exception:
                pass
    try:
        # Ensure the public status blocks reflect the pruned final JSON.
        status_report_final = apply_extraction_consistency_status(out)
        report["stages"].append({"name": "extraction_vs_document_consistency_after_prune", "report": {
            "extraction_ok": status_report_final.get("extraction_status", {}).get("ok"),
            "document_consistency_ok": status_report_final.get("document_consistency_status", {}).get("ok"),
        }})
    except Exception as exc:
        report["errors"].append({"stage": "extraction_vs_document_consistency_after_prune", "message": str(exc), "exception_type": exc.__class__.__name__})
        _add_mandatory_failure(out, stage="extraction_vs_document_consistency_after_prune", exc=exc)


    try:
        total_lines_report_after = apply_budget_total_lines(out)
        report["stages"].append({"name": "budget_total_lines_after_prune", "report": total_lines_report_after})
    except Exception as exc:
        report["errors"].append({"stage": "budget_total_lines_after_prune", "message": str(exc), "exception_type": exc.__class__.__name__})
        _add_mandatory_failure(out, stage="budget_total_lines_after_prune", exc=exc)

    # Build a short current-state correction document after the final status
    # blocks are known.  Full evidence stays in documento_evidencias;
    # documento_correcao.resumo_final_curto remains concise for Lovable/users.
    try:
        compact_corr = apply_compact_correction_document(out)
        report["stages"].append({"name": "compact_correction_document", "report": {"pending_errors": len(compact_corr.get("pending_errors") or []), "warnings": len(compact_corr.get("warnings") or []), "applied_patches": len(compact_corr.get("applied_patches") or [])}})
    except Exception as exc:
        report["errors"].append({"stage": "compact_correction_document", "message": str(exc), "exception_type": exc.__class__.__name__})
        _add_mandatory_failure(out, stage="compact_correction_document", exc=exc)

    # Final metrics must reflect the actual public JSON after pruning and the
    # final gate, not an earlier pre-gate state.
    try:
        metrics_after = apply_final_quality_metrics(out)
        report["quality_metrics_after_gate"] = metrics_after
    except Exception as exc:
        report["errors"].append({"stage": "final_quality_metrics_after_gate", "message": str(exc), "exception_type": exc.__class__.__name__})
        _add_mandatory_failure(out, stage="final_quality_metrics_after_gate", exc=exc)
    _finalize_status(out)
    # Rebuild the compact correction summary after final status normalization so
    # documento_correcao.resumo_final_curto reflects the current public status,
    # not an earlier pre-finalize snapshot.
    try:
        compact_corr_final = apply_compact_correction_document(out)
        report["stages"].append({"name": "compact_correction_document_after_finalize", "report": {"status": (compact_corr_final.get("summary") or {}).get("status"), "pending_errors": len(compact_corr_final.get("pending_errors") or []), "warnings": len(compact_corr_final.get("warnings") or [])}})
    except Exception as exc:
        report["errors"].append({"stage": "compact_correction_document_after_finalize", "message": str(exc), "exception_type": exc.__class__.__name__})
        _add_mandatory_failure(out, stage="compact_correction_document_after_finalize", exc=exc)
    report["status_after"] = out.get("status")
    report["blocking_after"] = _is_gate_blocking(out)
    return out, report


def run_final_integrity_orchestrator_file(
    file_path: str,
    result: Dict[str, Any],
    options: Dict[str, Any] | None = None,
    *,
    perf_key: str = "final_integrity_orchestrator_file",
    prune_runtime: bool = True,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    return run_final_integrity_orchestrator(result, file_path=file_path, options=options, perf_key=perf_key, prune_runtime=prune_runtime)


def run_final_integrity_orchestrator_bytes(
    pdf_bytes: bytes,
    result: Dict[str, Any],
    options: Dict[str, Any] | None = None,
    *,
    perf_key: str = "final_integrity_orchestrator_bytes",
    prune_runtime: bool = True,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    return run_final_integrity_orchestrator(result, pdf_bytes=pdf_bytes, options=options, perf_key=perf_key, prune_runtime=prune_runtime)
