from __future__ import annotations

"""Compact final quality metrics for Lovable and parser diagnostics.

The metrics are document-independent counters collected from the public JSON and
existing final reports.  They do not change values; they make the integrity of
an extraction visible and testable.
"""

from typing import Any, Dict, Iterator, Optional, Tuple
from app.config.version import CURRENT_RELEASE
from app.parser.math_status import compute_component_math


def _iter_budget_nodes(nodes, path="orcamento_sintetico.itens_raiz"):
    if not isinstance(nodes, list):
        return
    for idx, node in enumerate(nodes):
        if not isinstance(node, dict):
            continue
        cur = f"{path}.{idx}"
        yield cur, node
        filhos = node.get("filhos")
        if isinstance(filhos, list):
            yield from _iter_budget_nodes(filhos, f"{cur}.filhos")


def _is_leaf_budget(node: Dict[str, Any]) -> bool:
    return isinstance(node, dict) and node.get("tipo") == "item" and not node.get("filhos")


def _iter_sinapi_blocks(composicoes: Dict[str, Any]):
    if not isinstance(composicoes, dict):
        return
    seen = set()
    fam = composicoes.get("sinapi_like") if isinstance(composicoes.get("sinapi_like"), dict) else {}
    for collection in ("principais", "auxiliares_globais"):
        for key, block in (fam.get(collection) or {}).items():
            if isinstance(block, dict) and id(block) not in seen:
                seen.add(id(block)); yield collection, str(key), block
    for collection in ("principais", "auxiliares_globais"):
        for key, block in (composicoes.get(collection) or {}).items():
            if not isinstance(block, dict) or id(block) in seen:
                continue
            principal = block.get("principal") if isinstance(block.get("principal"), dict) else {}
            bank = str(principal.get("banco") or "").upper()
            if not bank.startswith("SICRO"):
                seen.add(id(block)); yield collection, str(key), block


def _iter_rows(block: Dict[str, Any]):
    principal = block.get("principal") if isinstance(block.get("principal"), dict) else None
    if principal is not None:
        yield "principal", None, principal
    for group in ("composicoes_auxiliares", "insumos"):
        rows = block.get(group)
        if isinstance(rows, list):
            for idx, row in enumerate(rows):
                if isinstance(row, dict):
                    yield group, idx, row


def apply_final_quality_metrics(result: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    budget_leaf_count = 0
    budget_leaf_with_required_numbers = 0
    budget_nodes_with_declared_total = 0
    budget_nodes = ((result.get("orcamento_sintetico") or {}).get("itens_raiz") or []) if isinstance(result.get("orcamento_sintetico"), dict) else []
    for _path, node in _iter_budget_nodes(budget_nodes):
        if node.get("custo_total") not in (None, "", [], {}):
            budget_nodes_with_declared_total += 1
        if _is_leaf_budget(node):
            budget_leaf_count += 1
            required = ("quant", "custo_unitario_sem_bdi", "custo_unitario_com_bdi", "custo_parcial")
            if all(node.get(f) not in (None, "", [], {}) for f in required):
                budget_leaf_with_required_numbers += 1

    composition_count = 0
    composition_closed_count = 0
    composition_with_missing_numeric_count = 0
    composition_math_incoherent_count = 0
    rows_total = 0
    rows_locked_like = 0
    for _collection, _key, block in _iter_sinapi_blocks(result.get("composicoes") if isinstance(result.get("composicoes"), dict) else {}):
        composition_count += 1
        try:
            math = compute_component_math(block)
        except Exception:
            math = {}
        missing_totals = int((math or {}).get("missing_component_totals") or 0)
        math_ok = bool(math.get("ok")) or str(math.get("status") or "") == "ok"
        if math_ok and missing_totals == 0:
            composition_closed_count += 1
        if math.get("ok") and (str(math.get("status") or "") != "ok" or missing_totals > 0):
            composition_math_incoherent_count += 1
        block_missing = False
        for _group, _idx, row in _iter_rows(block):
            rows_total += 1
            missing = [f for f in ("und", "quant", "valor_unit", "total") if row.get(f) in (None, "", [], {})]
            if missing:
                block_missing = True
            else:
                rows_locked_like += 1
        if block_missing:
            composition_with_missing_numeric_count += 1

    evid = result.get("documento_evidencias") if isinstance(result.get("documento_evidencias"), dict) else {}
    ev_report = evid.get("public_numeric_evidence_report") if isinstance(evid.get("public_numeric_evidence_report"), dict) else {}
    registry = evid.get("evidence_registry") if isinstance(evid.get("evidence_registry"), dict) else {}
    block_cov = evid.get("physical_block_coverage") if isinstance(evid.get("physical_block_coverage"), dict) else {}
    scratch_inv = evid.get("from_scratch_block_inventory") if isinstance(evid.get("from_scratch_block_inventory"), dict) else {}
    active_rex = evid.get("active_reextraction_engine") if isinstance(evid.get("active_reextraction_engine"), dict) else {}
    total_lines = evid.get("budget_total_display_index") if isinstance(evid.get("budget_total_display_index"), dict) else {}
    diff_scan = evid.get("light_reextraction_diff_scan") if isinstance(evid.get("light_reextraction_diff_scan"), dict) else {}
    row_proof = evid.get("row_inventory_proof") if isinstance(evid.get("row_inventory_proof"), dict) else {}
    row_proof_summary = row_proof.get("summary") if isinstance(row_proof, dict) and isinstance(row_proof.get("summary"), dict) else {}
    block_cov_summary = block_cov.get("summary") if isinstance(block_cov, dict) and isinstance(block_cov.get("summary"), dict) else {}
    scratch_summary = scratch_inv.get("summary") if isinstance(scratch_inv, dict) and isinstance(scratch_inv.get("summary"), dict) else {}
    gate = ((result.get("auditoria_final") or {}).get("quality_gate") or {}) if isinstance(result.get("auditoria_final"), dict) else {}
    perf = ((result.get("meta") or {}).get("performance") or {}) if isinstance(result.get("meta"), dict) else {}
    recovery_targets_created = 0
    recovery_targets_resolved = 0
    for name, rep in perf.items() if isinstance(perf, dict) else []:
        if isinstance(rep, dict) and "target_blocks" in rep:
            targets = rep.get("target_blocks") or []
            recovery_targets_created += len(targets) if isinstance(targets, list) else 0
            recovery_targets_resolved += max(0, len(targets) - len(rep.get("blocking_unresolved") or [])) if isinstance(targets, list) else 0
    extraction_status = result.get("extraction_status") if isinstance(result.get("extraction_status"), dict) else {}
    document_consistency_status = result.get("document_consistency_status") if isinstance(result.get("document_consistency_status"), dict) else {}
    coverage = (result.get("documento_evidencias") or {}).get("coverage_engine") if isinstance(result.get("documento_evidencias"), dict) else {}
    pre_cov = coverage.get("pre_recovery") if isinstance(coverage, dict) and isinstance(coverage.get("pre_recovery"), dict) else {}
    post_cov = coverage.get("post_recovery") if isinstance(coverage, dict) and isinstance(coverage.get("post_recovery"), dict) else {}
    metrics = {
        "version": CURRENT_RELEASE,
        "budget_leaf_count": budget_leaf_count,
        "budget_leaf_with_required_numbers": budget_leaf_with_required_numbers,
        "budget_nodes_with_declared_total": budget_nodes_with_declared_total,
        "composition_count": composition_count,
        "composition_closed_count": composition_closed_count,
        "composition_with_missing_numeric_count": composition_with_missing_numeric_count,
        "composition_math_incoherent_count": composition_math_incoherent_count,
        "composition_rows_count": rows_total,
        "composition_rows_complete_count": rows_locked_like,
        "public_numeric_fields_checked": int(ev_report.get("public_numeric_fields_checked") or 0),
        "public_numeric_without_evidence_count": int(ev_report.get("public_numeric_without_evidence_count") or 0),
        "public_numeric_without_primary_evidence_count": int(ev_report.get("public_numeric_without_primary_evidence_count", ev_report.get("public_numeric_without_evidence_count") or 0) or 0),
        "public_numeric_without_any_evidence_count": int(ev_report.get("public_numeric_without_any_evidence_count", ev_report.get("public_numeric_without_evidence_count") or 0) or 0),
        "public_numeric_auxiliary_only_count": int(ev_report.get("public_numeric_auxiliary_only_count") or 0),
        "public_numeric_evidence_not_checked_count": int(ev_report.get("public_numeric_evidence_not_checked_count") or 0),
        "public_numeric_evidence_gate_mode": str(ev_report.get("evidence_gate_mode") or "not_run"),
        "evidence_registry_entry_count": int(registry.get("entry_count") or 0),
        "evidence_registry_field_entry_count": int(registry.get("field_entry_count") or 0),
        "evidence_registry_primary_physical_entry_count": int(registry.get("primary_physical_entry_count") or 0),
        "evidence_registry_missing_or_unknown_entry_count": int(registry.get("missing_or_unknown_entry_count") or 0),
        "evidence_registry_locked_row_count": int(registry.get("locked_row_count") or 0),
        "evidence_registry_open_row_count": int(registry.get("open_row_count") or 0),
        "required_rows_missing_count": int(ev_report.get("required_rows_missing_count") or 0),
        "recovery_targets_created": recovery_targets_created,
        "recovery_targets_resolved": recovery_targets_resolved,
        "blocking_issues": int(gate.get("blocking_issue_count") or 0) if isinstance(gate, dict) else 0,
        "quality_gate_ok": bool(gate.get("ok")) if isinstance(gate, dict) and gate else False,
        "extraction_status_ok": bool(extraction_status.get("ok")) if extraction_status else False,
        "extraction_status_issue_count": int(extraction_status.get("critical_issue_count") or 0) if extraction_status else 0,
        "document_consistency_status_ok": bool(document_consistency_status.get("ok")) if document_consistency_status else False,
        "document_consistency_issue_count": int(document_consistency_status.get("issue_count") or 0) if document_consistency_status else 0,
        "coverage_pre_recovery_targets": int(pre_cov.get("target_count") or 0) if pre_cov else 0,
        "coverage_post_recovery_targets": int(post_cov.get("target_count") or 0) if post_cov else 0,
        "coverage_post_recovery_blocking_targets": int(post_cov.get("blocking_target_count") or 0) if post_cov else 0,
        "physical_block_coverage_status": str(block_cov_summary.get("overall_status") or "not_run"),
        "physical_block_composition_block_count": int(block_cov_summary.get("composition_block_count") or 0),
        "physical_block_composition_complete_count": int(block_cov_summary.get("composition_complete_block_count") or 0),
        "physical_block_composition_incomplete_count": int(block_cov_summary.get("composition_incomplete_block_count") or 0),
        "physical_block_composition_open_rows": int(block_cov_summary.get("composition_open_rows") or 0),
        "physical_block_useful_orphan_fragments": int(block_cov_summary.get("useful_orphan_fragments") or 0),
        "physical_block_budget_leaf_missing_count": int(block_cov_summary.get("budget_leaf_missing_count") or 0),
        "from_scratch_inventory_status": str(scratch_summary.get("overall_status") or "not_run"),
        "from_scratch_inventory_block_count": int(scratch_summary.get("block_count") or 0),
        "from_scratch_inventory_complete_block_count": int(scratch_summary.get("complete_block_count") or 0),
        "from_scratch_inventory_physical_rows_total": int(scratch_summary.get("physical_rows_total") or 0),
        "active_reextraction_status": str(active_rex.get("status") or ("skipped" if active_rex.get("skipped") else "not_run")),
        "active_reextraction_pre_blocking_targets": int(active_rex.get("pre_blocking_target_count") or 0),
        "active_reextraction_post_blocking_targets": int(active_rex.get("post_blocking_target_count") or 0),
        "active_reextraction_resolved_blocking_targets": int(active_rex.get("resolved_blocking_targets") or 0),
        "row_inventory_proof_status": str(row_proof_summary.get("overall_status") or "not_run"),
        "row_inventory_composition_blocks_checked": int(row_proof_summary.get("composition_blocks_checked") or 0),
        "row_inventory_composition_blocks_complete": int(row_proof_summary.get("composition_blocks_complete") or 0),
        "row_inventory_composition_blocks_needs_review": int(row_proof_summary.get("composition_blocks_needs_review") or 0),
        "row_inventory_physical_scope": str(row_proof_summary.get("physical_inventory_scope") or "not_run"),
        "row_inventory_physical_blocks_evaluated": int(row_proof_summary.get("physical_inventory_blocks_evaluated") or 0),
        "row_inventory_json_open_rows": int(row_proof_summary.get("json_open_rows") or 0),
        "row_inventory_orphan_numeric_fragments": int(row_proof_summary.get("orphan_numeric_fragments") or 0),
        "row_inventory_physical_row_mismatch_count": int(row_proof_summary.get("physical_row_mismatch_count") or 0),
        "budget_inline_total_node_count": int(total_lines.get("inline_total_node_count") or 0),
        "budget_total_index_count": int(total_lines.get("total_index_count") or 0),
        "budget_has_total_geral": bool(total_lines.get("has_total_geral")),
        "budget_public_detached_total_lines": bool(total_lines.get("public_budget_has_detached_total_lines")),
        "light_diff_scan_status": str(diff_scan.get("status") or ("skipped" if diff_scan.get("skipped") else "not_run")),
        "light_diff_scan_scanned_pages": int(diff_scan.get("scanned_pages") or 0),
        "light_diff_scan_potential_missing_code_count": int(diff_scan.get("potential_missing_code_count") or 0),
    }
    result["quality_metrics"] = metrics
    result.setdefault("documento_correcao", {})["quality_metrics"] = metrics
    return metrics
