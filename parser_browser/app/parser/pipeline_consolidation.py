from __future__ import annotations

"""Pipeline consolidation and correction-document hardening (v61.0.45).

This module does not add a new extraction strategy.  It makes the existing
strategies work as one auditable pipeline: execution order, effect counters,
non-redundant warnings, actionable unresolved lines and compact evidence trails.
The goal is to ensure each tool either affects the JSON final or is clearly
reported as diagnostic-only.
"""

from typing import Any, Dict, List, Tuple

VERSION = "v61.0.75-correction-output-contract-and-review-index"


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _unique_dicts(items: List[Dict[str, Any]], *, keys: Tuple[str, ...] = ("tipo", "row_id", "field", "codigo", "banco", "reason"), limit: int | None = None) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        marker = tuple(str(item.get(k, "")) for k in keys)
        if marker in seen:
            continue
        seen.add(marker)
        out.append(item)
        if limit is not None and len(out) >= limit:
            break
    return out


def _effect_count_for_step(step_name: str, report: Dict[str, Any]) -> int:
    summary = _as_dict(report.get("summary"))
    puzzle = _as_dict(report.get("budget_puzzle_resolver"))
    puzzle_summary = _as_dict(puzzle.get("summary"))
    if step_name == "sicro_collection_enforcer":
        return int(_as_dict(report.get("sicro_collection_enforcer")).get("moves", 0) or 0) + int(summary.get("sicro_issues", 0) or 0)
    if step_name == "document_evidence_index":
        return int(_as_dict(report.get("document_evidence_index")).get("key_count", 0) or 0)
    if step_name == "physical_evidence_index":
        return int(_as_dict(report.get("physical_evidence_index")).get("occurrence_count", 0) or 0)
    if step_name == "extracted_evidence_cross_resolver":
        return len(_as_list(_as_dict(report.get("extracted_evidence_cross_resolver")).get("applied")))
    if step_name == "field_consensus_engine":
        return int(_as_dict(report.get("field_consensus_engine")).get("candidate_count", 0) or 0)
    if step_name == "local_line_cascade_repair":
        return int(_as_dict(report.get("local_line_cascade_repair")).get("candidate_count", 0) or 0) + sum(1 for r in _as_list(report.get("repairs")) if isinstance(r, dict) and r.get("reason") in {"local_line_neighborhood_cascade_repair", "math_expected_value_found_near_same_codigo_banco"})
    if step_name == "budget_puzzle_resolver":
        return int(puzzle_summary.get("relations", 0) or 0) + int(puzzle_summary.get("chains", 0) or 0)
    if step_name == "budget_reconstruction_graph":
        return int(puzzle_summary.get("chains", 0) or 0)
    if step_name == "composition_cost_reconciliation":
        return int(puzzle_summary.get("composition_cost_mismatches", 0) or 0) + int(_as_dict(_as_dict(puzzle.get("composition_cost_reconciliation")).get("summary")).get("ok", 0) or 0)
    if step_name == "budget_hierarchy_reconciliation":
        return int(puzzle_summary.get("budget_hierarchy_mismatches", 0) or 0) + int(_as_dict(_as_dict(puzzle.get("budget_hierarchy_reconciliation")).get("summary")).get("ok", 0) or 0)
    if step_name == "entity_chain_conflict_resolver":
        return int(puzzle_summary.get("chain_conflicts", 0) or 0) + len(_as_list(_as_dict(_as_dict(puzzle.get("entity_chain_conflict_resolver")).get("confirmations"))))
    if step_name == "line_certainty_closure":
        return int(summary.get("closed_100", 0) or 0) + int(summary.get("closed_by_strong_consensus", 0) or 0)
    if step_name == "final_reconciliation_pass":
        return int(_as_dict(report.get("final_reconciliation_pass")).get("issue_count", 0) or 0) + int(summary.get("unresolved", 0) or 0)
    return 0


def _step_status(effect_count: int, *, required: bool = True, diagnostic_ok: bool = False) -> str:
    if effect_count > 0:
        return "used_with_effect"
    if diagnostic_ok:
        return "used_as_diagnostic"
    return "used_no_change" if required else "not_required"


def build_pipeline_consolidation_report(final_result: Dict[str, Any], closure_report: Dict[str, Any]) -> Dict[str, Any]:
    """Build a compact, ordered audit of the tools already executed."""
    closure_report = _as_dict(closure_report)
    summary = _as_dict(closure_report.get("summary"))
    steps_def = [
        ("sicro_collection_enforcer", "organiza coleções SICRO antes das validações", True, True),
        ("document_evidence_index", "indexa evidências extraídas por código+banco", True, False),
        ("physical_evidence_index", "injeta evidências físicas/brutas do PDF", True, True),
        ("extracted_evidence_cross_resolver", "cruza orçamento, principais e auxiliares já extraídos", True, True),
        ("field_consensus_engine", "seleciona candidatos por consenso de evidências", True, True),
        ("local_line_cascade_repair", "procura mais perto da linha conhecida e usa matemática para encaixar campos vazios", True, True),
        ("budget_puzzle_resolver", "monta entidades e relações do orçamento como quebra-cabeças", True, False),
        ("budget_reconstruction_graph", "reconstrói cadeia orçamento→composição→linhas internas", True, False),
        ("composition_cost_reconciliation", "valida soma de componentes contra valor da composição", True, True),
        ("budget_hierarchy_reconciliation", "valida metas/submetas pela soma dos filhos", True, True),
        ("entity_chain_conflict_resolver", "resolve conflitos por cadeia de evidências", True, True),
        ("line_certainty_closure", "fecha linhas após correções e evidências", True, False),
        ("final_reconciliation_pass", "audita JSON final antes da exportação", True, True),
    ]
    execution_order: List[Dict[str, Any]] = []
    for order, (name, purpose, required, diagnostic_ok) in enumerate(steps_def, start=1):
        effect = _effect_count_for_step(name, closure_report)
        execution_order.append({
            "order": order,
            "step": name,
            "required": required,
            "status": _step_status(effect, required=required, diagnostic_ok=diagnostic_ok),
            "effect_count": effect,
            "purpose": purpose,
        })

    rows = _as_list(closure_report.get("rows"))
    closed_rows = [r for r in rows if isinstance(r, dict) and r.get("row_status") in {"closed_100", "closed_by_strong_consensus"}]
    unresolved_rows = [r for r in rows if isinstance(r, dict) and r.get("row_status") == "unresolved"]
    warning_rows = [r for r in rows if isinstance(r, dict) and r.get("row_status") == "closed_with_warning"]
    repairs = _as_list(closure_report.get("repairs"))
    useful_repairs = [r for r in repairs if isinstance(r, dict) and (r.get("status") in {"committed", "applied"} or r.get("after") not in (None, ""))]
    rejected_candidates = _as_list(_as_dict(closure_report.get("field_consensus_engine")).get("rejected"))
    puzzle = _as_dict(closure_report.get("budget_puzzle_resolver"))
    pipeline_ok = int(summary.get("unresolved", 0) or 0) == 0 and int(summary.get("sicro_issues", 0) or 0) == 0 and not _as_dict(closure_report.get("final_reconciliation_pass")).get("issues")

    unresolved_action_items = []
    for row in unresolved_rows[:250]:
        unresolved_action_items.append({
            "row_id": row.get("row_id"),
            "family": row.get("family"),
            "codigo": row.get("codigo"),
            "banco": row.get("banco"),
            "item": row.get("item"),
            "missing_fields": row.get("missing_fields") or [],
            "reasons": row.get("reasons") or [],
            "suggested_next_action": _suggest_next_action(row),
        })

    return {
        "version": VERSION,
        "mode": "pipeline_consolidation_and_closure_hardening",
        "pipeline_ok": bool(pipeline_ok),
        "execution_order": execution_order,
        "summary": {
            "total_rows": summary.get("total_rows"),
            "closed_100": summary.get("closed_100"),
            "closed_by_strong_consensus": summary.get("closed_by_strong_consensus"),
            "closed_with_warning": summary.get("closed_with_warning"),
            "unresolved": summary.get("unresolved"),
            "repairs_applied": summary.get("repairs_applied"),
            "useful_repairs": len(useful_repairs),
            "warning_rows": len(warning_rows),
            "sicro_issues": summary.get("sicro_issues"),
            "budget_chains": _as_dict(puzzle.get("summary")).get("chains"),
            "missing_global_auxiliaries": _as_dict(puzzle.get("summary")).get("missing_global_auxiliaries"),
            "composition_cost_mismatches": _as_dict(puzzle.get("summary")).get("composition_cost_mismatches"),
            "budget_hierarchy_mismatches": _as_dict(puzzle.get("summary")).get("budget_hierarchy_mismatches"),
            "chain_conflicts": _as_dict(puzzle.get("summary")).get("chain_conflicts"),
        },
        "closed_lines_sample": _line_sample(closed_rows, limit=80),
        "warning_lines_sample": _line_sample(warning_rows, limit=80),
        "unresolved_lines": unresolved_action_items,
        "applied_repairs": _unique_dicts(useful_repairs, keys=("row_id", "field", "reason", "after"), limit=180),
        "rejected_candidates": _unique_dicts([r for r in rejected_candidates if isinstance(r, dict)], keys=("row_id", "field", "value", "reason"), limit=180),
        "chain_reconciliation": {
            "budget_reconstruction_graph": _as_dict(puzzle.get("budget_reconstruction_graph")).get("summary") or {},
            "composition_cost_reconciliation": _as_dict(_as_dict(puzzle.get("composition_cost_reconciliation")).get("summary")) or {},
            "budget_hierarchy_reconciliation": _as_dict(_as_dict(puzzle.get("budget_hierarchy_reconciliation")).get("summary")) or {},
            "entity_chain_conflict_resolver": _as_dict(_as_dict(puzzle.get("entity_chain_conflict_resolver")).get("summary")) or {},
        },
        "evidence_indexes": {
            "document_evidence_index": {k: _as_dict(closure_report.get("document_evidence_index")).get(k) for k in ("status", "key_count", "evidence_value_count", "occurrence_count")},
            "physical_evidence_index": {k: _as_dict(closure_report.get("physical_evidence_index")).get(k) for k in ("status", "key_count", "occurrence_count", "source_zone_counts", "document_section_counts", "evidence_policy_counts")},
            "local_line_cascade_repair": {k: _as_dict(closure_report.get("local_line_cascade_repair")).get(k) for k in ("mode", "candidate_count", "rejected_count", "math_expected_searches")},
            "real_document_regression": _as_dict(_as_dict(final_result.get("meta")).get("performance")).get("real_document_regression") or {},
        },
    }


def _line_sample(rows: List[Dict[str, Any]], *, limit: int = 80) -> List[Dict[str, Any]]:
    sample: List[Dict[str, Any]] = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        sample.append({
            "row_id": row.get("row_id"),
            "family": row.get("family"),
            "codigo": row.get("codigo"),
            "banco": row.get("banco"),
            "item": row.get("item"),
            "row_status": row.get("row_status"),
            "missing_fields": row.get("missing_fields") or [],
            "reasons": row.get("reasons") or [],
        })
    return sample


def _suggest_next_action(row: Dict[str, Any]) -> str:
    missing = set(row.get("missing_fields") or [])
    reasons = set(row.get("reasons") or [])
    if missing & {"descricao", "especificacao"}:
        return "conferir descrição no PDF físico, composição relacionada ou auxiliar global"
    if missing & {"und", "quant", "valor_unit", "total", "custo_unitario_com_bdi", "custo_parcial"}:
        return "procurar campo numérico/unidade em evidência física e validar com matemática"
    if "math_mismatch" in reasons:
        return "rever quantidade, valor unitário e total/custo parcial que não fecham matematicamente"
    if "weak_description" in reasons:
        return "rever descrição por possível truncamento ou poluição de linha vizinha"
    return "conferir evidências da linha e relações no orçamento/composição"


def consolidate_correction_document(final_result: Dict[str, Any], closure_report: Dict[str, Any]) -> Dict[str, Any]:
    """Attach a non-redundant correction-document view for Lovable/UI review."""
    report = build_pipeline_consolidation_report(final_result, closure_report)
    doc = final_result.setdefault("documento_correcao", {})
    if not isinstance(doc, dict):
        final_result["documento_correcao"] = doc = {}

    # Dedupe legacy warning list without removing useful details.
    warnings = _as_list(doc.get("warnings"))
    doc["warnings"] = _unique_dicts([w for w in warnings if isinstance(w, dict)], limit=600)

    doc["auditoria_consolidada"] = report
    doc["resumo_executivo"] = {
        "version": VERSION,
        "pipeline_ok": report.get("pipeline_ok"),
        "linhas_avaliadas": (report.get("summary") or {}).get("total_rows"),
        "linhas_fechadas_100": (report.get("summary") or {}).get("closed_100"),
        "linhas_fechadas_por_consenso": (report.get("summary") or {}).get("closed_by_strong_consensus"),
        "linhas_com_alerta": (report.get("summary") or {}).get("closed_with_warning"),
        "linhas_pendentes": (report.get("summary") or {}).get("unresolved"),
        "reparos_uteis": (report.get("summary") or {}).get("useful_repairs"),
        "cadeias_reconstruidas": (report.get("summary") or {}).get("budget_chains"),
        "pendencias_sicro": (report.get("summary") or {}).get("sicro_issues"),
        "real_document_regression": (((report.get("evidence_indexes") or {}).get("real_document_regression") or {}).get("summary") or {}),
    }
    doc["pendencias_para_resolucao"] = report.get("unresolved_lines") or []
    doc["reparos_aplicados_consolidados"] = report.get("applied_repairs") or []
    doc["candidatos_rejeitados_consolidados"] = report.get("rejected_candidates") or []
    doc["ordem_execucao_pipeline"] = report.get("execution_order") or []

    analysis = final_result.setdefault("analise_orcamentaria", {})
    if isinstance(analysis, dict):
        analysis["pipeline_consolidation"] = {
            "version": VERSION,
            "summary": report.get("summary") or {},
            "execution_order": report.get("execution_order") or [],
            "principle": "ferramentas_existentes_consolidadas_em_ordem_de_execucao_com_efeito_rastreavel_no_json_final",
        }
    return report
