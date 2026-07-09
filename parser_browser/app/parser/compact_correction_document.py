from __future__ import annotations

"""Clean, actionable correction document for Lovable review.

The correction document is not a debug dump.  It is a UI/review contract:
when a problem or PDF inconsistency exists, Lovable receives a short issue with
its category, severity, affected field, composition/budget location, page span,
crop hint and candidate destination data.  Heavy hypotheses/logs are moved to
``analise_orcamentaria.debug_recovery`` and the detailed evidence remains in
``documento_evidencias``.
"""

from typing import Any, Dict, Iterable, List, Tuple
from app.config.version import CURRENT_RELEASE

_DEBUG_KEYS = {
    "targeted_recovery",
    "debug_recovery",
    "pre_repair_snapshots",
    "correction_preliminary_resumo",
    "final_integrity_orchestrator",
    "clean_final_contract",
}


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def _get_gate(result: Dict[str, Any]) -> Dict[str, Any]:
    return ((result.get("auditoria_final") or {}).get("quality_gate") or {}) if isinstance(result.get("auditoria_final"), dict) else {}


def _path_to_string(path: Any) -> str:
    if isinstance(path, list):
        return ".".join(str(x) for x in path)
    return str(path or "")


def _clean_empty(obj: Any) -> Any:
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            cv = _clean_empty(v)
            if cv not in (None, "", [], {}):
                out[k] = cv
        return out
    if isinstance(obj, list):
        out = []
        for x in obj:
            cx = _clean_empty(x)
            if cx not in (None, "", [], {}):
                out.append(cx)
        return out
    return obj


def _as_int(v: Any) -> int | None:
    try:
        if v in (None, ""):
            return None
        return int(v)
    except Exception:
        return None


def _page_interval(start: Any = None, end: Any = None, page: Any = None) -> Dict[str, Any]:
    s = _as_int(start)
    e = _as_int(end)
    p = _as_int(page)
    if s is None and p is not None:
        s = p
    if e is None and s is not None:
        e = s
    return _clean_empty({"page_start": s, "page_end": e, "page": p or s})


def _crop_hint(page: Any = None, bbox: Any = None, line_preview: str | None = None, page_start: Any = None, page_end: Any = None, focus: str | None = None) -> Dict[str, Any]:
    hint = {
        "ui_action": "open_pdf_page_and_focus_region",
        "page": _as_int(page) or _as_int(page_start),
        "page_start": _as_int(page_start) or _as_int(page),
        "page_end": _as_int(page_end) or _as_int(page_start) or _as_int(page),
        "bbox": bbox,
        "focus": focus,
        "line_preview": (line_preview or "")[:260],
    }
    return _clean_empty(hint)


# ---------------------------------------------------------------------------
# Lookups: keep issues short but locatable.
# ---------------------------------------------------------------------------

def _iter_blocks(result: Dict[str, Any]) -> Iterable[Tuple[str, str, str, Dict[str, Any]]]:
    comps = result.get("composicoes") if isinstance(result.get("composicoes"), dict) else {}
    seen: set[int] = set()
    if isinstance(comps, dict):
        fam = comps.get("sinapi_like") if isinstance(comps.get("sinapi_like"), dict) else None
        if isinstance(fam, dict):
            for collection in ("principais", "auxiliares_globais"):
                blocks = fam.get(collection)
                if isinstance(blocks, dict):
                    for key, block in blocks.items():
                        if isinstance(block, dict) and id(block) not in seen:
                            seen.add(id(block))
                            yield "sinapi_like", collection, str(key), block
        for collection in ("principais", "auxiliares_globais"):
            blocks = comps.get(collection)
            if isinstance(blocks, dict):
                for key, block in blocks.items():
                    if isinstance(block, dict) and id(block) not in seen:
                        seen.add(id(block))
                        yield "flat", collection, str(key), block


def _block_lookup(result: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    lookup: Dict[str, Dict[str, Any]] = {}
    for family, collection, key, block in _iter_blocks(result):
        principal = block.get("principal") if isinstance(block.get("principal"), dict) else {}
        pages = block.get("paginas") if isinstance(block.get("paginas"), list) else []
        start = block.get("pagina_inicio") or (min([p for p in pages if isinstance(p, int)]) if pages else None)
        end = block.get("pagina_fim") or (max([p for p in pages if isinstance(p, int)]) if pages else start)
        lookup[key] = _clean_empty({
            "family": family,
            "collection": collection,
            "composition": key,
            "item": block.get("item"),
            "codigo": principal.get("codigo"),
            "banco": principal.get("banco") or principal.get("fonte"),
            "descricao": principal.get("descricao"),
            "page_start": start,
            "page_end": end,
            "source_section": "composicoes_analiticas",
        })
    return lookup


def _budget_item_lookup(result: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    budget = result.get("orcamento_sintetico") if isinstance(result.get("orcamento_sintetico"), dict) else {}

    def walk(nodes: Any, path: List[Any]) -> None:
        if not isinstance(nodes, list):
            return
        for idx, node in enumerate(nodes):
            if not isinstance(node, dict):
                continue
            p = path + [idx]
            item = str(node.get("item") or "")
            if item:
                out[item] = _clean_empty({
                    "item": item,
                    "tipo": node.get("tipo"),
                    "codigo": node.get("codigo"),
                    "fonte": node.get("fonte"),
                    "descricao": node.get("descricao") or node.get("especificacao"),
                    "path": ".".join(str(x) for x in (["orcamento_sintetico", "itens_raiz"] + p)),
                    "source_section": "orcamento_sintetico",
                })
            walk(node.get("filhos"), p + ["filhos"])

    walk(budget.get("itens_raiz"), [])
    return out


def _resolve_location(result: Dict[str, Any], issue: Dict[str, Any], block_info: Dict[str, Dict[str, Any]] | None = None, budget_info: Dict[str, Dict[str, Any]] | None = None) -> Dict[str, Any]:
    block_info = block_info or _block_lookup(result)
    budget_info = budget_info or _budget_item_lookup(result)
    evidence = issue.get("evidence") if isinstance(issue.get("evidence"), dict) else {}
    comp = issue.get("comp_key") or issue.get("composition") or issue.get("block") or issue.get("composicao")
    comp_meta = block_info.get(str(comp)) if comp else None
    item = issue.get("item") or (comp_meta or {}).get("item")
    budget_meta = budget_info.get(str(item)) if item else None
    page = issue.get("page") or issue.get("pagina") or evidence.get("page") or evidence.get("pagina") or (comp_meta or {}).get("page_start")
    return _clean_empty({
        "path": _path_to_string(issue.get("path")),
        "source_section": issue.get("source_section") or (comp_meta or {}).get("source_section") or (budget_meta or {}).get("source_section"),
        "item": item,
        "codigo": issue.get("codigo") or (comp_meta or {}).get("codigo") or (budget_meta or {}).get("codigo"),
        "banco": issue.get("banco") or (comp_meta or {}).get("banco") or (budget_meta or {}).get("fonte"),
        "composicao": comp,
        "row_group": issue.get("row_group"),
        "row_index": issue.get("row_index"),
        "page": _as_int(page),
        "page_interval": _page_interval((comp_meta or {}).get("page_start"), (comp_meta or {}).get("page_end"), page),
    })


# ---------------------------------------------------------------------------
# Issue compaction.
# ---------------------------------------------------------------------------

def _compact_issue(result: Dict[str, Any], issue: Dict[str, Any], *, fallback_type: str = "quality_gate_issue", category: str = "quality_gate") -> Dict[str, Any]:
    block_info = _block_lookup(result)
    budget_info = _budget_item_lookup(result)
    evidence = issue.get("evidence") if isinstance(issue.get("evidence"), dict) else {}
    loc = _resolve_location(result, issue, block_info, budget_info)
    page = loc.get("page") or evidence.get("page")
    bbox = issue.get("bbox") or evidence.get("bbox") or evidence.get("codigo_bbox")
    line_preview = issue.get("line_preview") or evidence.get("line_text") or issue.get("message")
    severity = issue.get("severity") or issue.get("gravidade") or ("blocking" if issue.get("blocks_json_ok") else "warning")
    return _clean_empty({
        "id": issue.get("id") or issue.get("code") or issue.get("target_id") or f"{category}:{fallback_type}",
        "categoria": category,
        "tipo": issue.get("tipo") or issue.get("code") or fallback_type,
        "gravidade": severity,
        "status": issue.get("status") or ("pendente" if severity == "blocking" or issue.get("blocks_json_ok") else "aviso"),
        "local": loc,
        "campo": issue.get("field") or issue.get("campo"),
        "valor_atual": issue.get("current_value") or issue.get("value"),
        "valor_pdf": issue.get("pdf_value") or evidence.get("value") or evidence.get("recovered_text"),
        "valor_calculado": issue.get("calculated_value") or issue.get("recomputed_value"),
        "mensagem": issue.get("message") or issue.get("reason"),
        "acao_recomendada": issue.get("action") or issue.get("recommended_action") or issue.get("message"),
        "material_apoio": {
            "crop_hint": _crop_hint(page, bbox, line_preview, page_start=(loc.get("page_interval") or {}).get("page_start"), page_end=(loc.get("page_interval") or {}).get("page_end"), focus=loc.get("composicao") or loc.get("item")),
            "line_preview": (line_preview or "")[:260],
            "evidence_ref": issue.get("evidence_ref") or "documento_evidencias.evidence_registry",
        },
    })


def _compact_status_issue(result: Dict[str, Any], issue: Dict[str, Any], *, category: str, default_type: str, default_severity: str) -> Dict[str, Any]:
    # extraction/document status issues use slightly different field names.
    normalized = dict(issue)
    normalized.setdefault("severity", default_severity)
    normalized.setdefault("tipo", issue.get("code") or default_type)
    normalized.setdefault("block", issue.get("block"))
    normalized.setdefault("comp_key", issue.get("block"))
    normalized.setdefault("message", issue.get("reason") or issue.get("status"))
    if isinstance(issue.get("math_status"), dict):
        math = issue["math_status"]
        normalized.setdefault("calculated_value", math.get("component_sum"))
        normalized.setdefault("pdf_value", math.get("principal_total") or math.get("expected"))
        normalized.setdefault("recommended_action", "review_pdf_declared_values_keep_public_values_unchanged" if category == "document_consistency" else "review_missing_extraction_fields")
    return _compact_issue(result, normalized, fallback_type=default_type, category=category)


def _compact_left_behind(result: Dict[str, Any], sample: Dict[str, Any]) -> Dict[str, Any]:
    parsed = sample.get("parsed_columns") if isinstance(sample.get("parsed_columns"), dict) else {}
    candidates = sample.get("possible_destination_candidates") if isinstance(sample.get("possible_destination_candidates"), list) else []
    best = candidates[0] if candidates and isinstance(candidates[0], dict) else {}
    location = _clean_empty({
        "source_section": "composicoes_analiticas",
        "page": sample.get("page"),
        "page_interval": _page_interval(page=sample.get("page")),
        "codigo": parsed.get("codigo") or sample.get("codigo_norm"),
        "banco": parsed.get("banco") or sample.get("banco"),
        "composicao_candidata": best.get("composition"),
        "item_candidato": best.get("item"),
    })
    return _clean_empty({
        "id": sample.get("id"),
        "categoria": "left_behind_scan",
        "tipo": "possible_line_left_behind",
        "gravidade": sample.get("gravidade") or "warning",
        "status": "needs_user_review",
        "local": location,
        "colunas_detectadas": parsed,
        "candidatos_destino": candidates,
        "motivo_match": sample.get("match_reason"),
        "politica_verificacao": sample.get("verification_policy"),
        "acao_recomendada": sample.get("recommended_action") or "review_and_attach_if_block_context_confirms",
        "material_apoio": {
            "crop_hint": sample.get("crop_hint") or _crop_hint(sample.get("page"), line_preview=sample.get("line_preview"), focus=best.get("composition")),
            "line_preview": (sample.get("line_preview") or "")[:280],
            "evidence_ref": "documento_evidencias.light_reextraction_diff_scan",
        },
    })


def _collect_patches(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    patches: List[Dict[str, Any]] = []
    corr = result.get("documento_correcao") if isinstance(result.get("documento_correcao"), dict) else {}
    for key in ("budget_total_ownership", "physical_numeric_tail_recovery", "public_token_fidelity"):
        val = corr.get(key) if isinstance(corr, dict) else None
        if isinstance(val, dict):
            for p in val.get("patches") or val.get("patches_applied_details") or []:
                if isinstance(p, dict) and len(patches) < 120:
                    patches.append(_clean_empty({
                        "source": key,
                        "field": p.get("field"),
                        "path": _path_to_string(p.get("path")),
                        "value": p.get("value"),
                        "previous_value": p.get("previous_value"),
                        "reason": p.get("reason") or p.get("source"),
                        "local": {"page": p.get("page"), "codigo": p.get("codigo"), "banco": p.get("banco"), "composicao": p.get("comp_key") or p.get("block")},
                        "material_apoio": {"crop_hint": _crop_hint(p.get("page"), p.get("bbox")), "evidence_ref": "documento_evidencias.evidence_registry"},
                    }))
    budget = (result.get("orcamento_sintetico") or {}).get("itens_raiz") if isinstance(result.get("orcamento_sintetico"), dict) else []
    stack = list(budget or []) if isinstance(budget, list) else []
    while stack and len(patches) < 120:
        node = stack.pop(0)
        if not isinstance(node, dict):
            continue
        for audit in ((node.get("_audit") or {}).get("budget_total_ownership") or []) if isinstance(node.get("_audit"), dict) else []:
            if isinstance(audit, dict):
                patches.append(_clean_empty({
                    "source": "budget_total_ownership",
                    "item": node.get("item"),
                    "descricao": node.get("descricao"),
                    "value": audit.get("value"),
                    "action": audit.get("action"),
                    "reason": audit.get("reason"),
                    "moved_to_parent_item": audit.get("moved_to_parent_item"),
                    "source_child_item": audit.get("source_child_item"),
                }))
        filhos = node.get("filhos")
        if isinstance(filhos, list):
            stack.extend(filhos)
    return patches


# ---------------------------------------------------------------------------
# Debug separation and final document.
# ---------------------------------------------------------------------------

def _move_debug_payloads(result: Dict[str, Any]) -> None:
    corr = result.get("documento_correcao") if isinstance(result.get("documento_correcao"), dict) else {}
    if not isinstance(corr, dict):
        return
    debug = result.setdefault("analise_orcamentaria", {}).setdefault("debug_recovery", {})
    for key in list(corr.keys()):
        if key in _DEBUG_KEYS:
            debug[key] = corr.pop(key)
    tr = debug.get("targeted_recovery") if isinstance(debug.get("targeted_recovery"), dict) else None
    if tr:
        corr.setdefault("debug_summary", {})["targeted_recovery"] = {
            "attempted": tr.get("attempted"),
            "status": tr.get("status"),
            "target_count": tr.get("target_count"),
            "patch_count": len(tr.get("patches") or []) if isinstance(tr.get("patches"), list) else 0,
            "unresolved_count": len(tr.get("unresolved") or []) if isinstance(tr.get("unresolved"), list) else 0,
            "debug_path": "analise_orcamentaria.debug_recovery.targeted_recovery",
        }


def _group_problem_counts(problems: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_category: Dict[str, int] = {}
    by_severity: Dict[str, int] = {}
    by_type: Dict[str, int] = {}
    for p in problems:
        cat = str(p.get("categoria") or "uncategorized")
        sev = str(p.get("gravidade") or "warning")
        typ = str(p.get("tipo") or "unknown")
        by_category[cat] = by_category.get(cat, 0) + 1
        by_severity[sev] = by_severity.get(sev, 0) + 1
        by_type[typ] = by_type.get(typ, 0) + 1
    return {"by_category": by_category, "by_severity": by_severity, "by_type": by_type}


def apply_compact_correction_document(result: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    _move_debug_payloads(result)
    gate = _get_gate(result)
    issues = gate.get("issues") if isinstance(gate.get("issues"), list) else []
    blocking = [i for i in issues if isinstance(i, dict) and (i.get("severity") == "blocking" or i.get("blocks_json_ok"))]
    warnings = [i for i in issues if isinstance(i, dict) and i not in blocking]
    corr = result.get("documento_correcao") if isinstance(result.get("documento_correcao"), dict) else {}
    left_behind = corr.get("possible_left_behind_lines") if isinstance(corr.get("possible_left_behind_lines"), list) else []
    coverage = ((result.get("documento_evidencias") or {}).get("physical_block_coverage") or {}) if isinstance(result.get("documento_evidencias"), dict) else {}
    diff = ((result.get("documento_evidencias") or {}).get("light_reextraction_diff_scan") or {}) if isinstance(result.get("documento_evidencias"), dict) else {}
    extraction = result.get("extraction_status") if isinstance(result.get("extraction_status"), dict) else {}
    doc_consistency = result.get("document_consistency_status") if isinstance(result.get("document_consistency_status"), dict) else {}

    pending_errors = [_clean_empty(_compact_issue(result, i, fallback_type="blocking_issue", category="quality_gate")) for i in blocking[:120]]
    warning_items = [_clean_empty(_compact_issue(result, i, fallback_type="warning_issue", category="quality_gate")) for i in warnings[:120]]
    extraction_issues = [
        _compact_status_issue(result, i, category="extraction", default_type="extraction_issue", default_severity="blocking")
        for i in (extraction.get("issues") or [])[:120]
        if isinstance(i, dict)
    ]
    document_issues = [
        _compact_status_issue(result, i, category="document_consistency", default_type="document_consistency_issue", default_severity="warning")
        for i in (doc_consistency.get("issues") or [])[:120]
        if isinstance(i, dict)
    ]
    left_behind_items = [_compact_left_behind(result, x) for x in left_behind[:120] if isinstance(x, dict)]
    # Unified problem catalog for Lovable.  Keep it concise but complete enough
    # for page/crop review windows.
    problems = pending_errors + extraction_issues + document_issues + warning_items + left_behind_items
    problem_counts = _group_problem_counts(problems)

    summary = {
        "version": CURRENT_RELEASE,
        "status": result.get("status"),
        "quality_gate_ok": bool(gate.get("ok")) if gate else False,
        "blocking_issue_count": int(gate.get("blocking_issue_count") or len(blocking) or len(extraction_issues) or 0) if isinstance(gate, dict) else len(blocking),
        "warning_issue_count": len([p for p in problems if p.get("gravidade") != "blocking"]),
        "problem_count": len(problems),
        "possible_left_behind_line_count": len(left_behind_items),
        "extraction_status": {k: v for k, v in extraction.items() if k != "issues"},
        "document_consistency_status": {k: v for k, v in doc_consistency.items() if k != "issues"},
        "block_coverage_summary": coverage.get("summary") if isinstance(coverage, dict) else {},
        "light_diff_scan_summary": {k: v for k, v in diff.items() if k not in {"potential_missing_lines", "potential_missing_samples"}} if isinstance(diff, dict) else {},
        "problem_counts": problem_counts,
    }
    compact = {
        "version": CURRENT_RELEASE,
        "schema_version": "correction_document.v2.actionable_review",
        "purpose": "clean_actionable_correction_document_for_lovable_review",
        "ui_review_mode": "page_crop_dynamic_review",
        "principles": [
            "public_values_mirror_pdf_declared_tokens",
            "math_is_audit_only_never_public_overwrite",
            "each_problem_has_location_or_evidence_reference_when_available",
            "heavy_debug_lives_in_analise_orcamentaria_debug_recovery",
        ],
        "summary": summary,
        "problemas": problems[:250],
        "problemas_por_categoria": {
            "quality_gate": pending_errors + warning_items,
            "extraction": extraction_issues,
            "document_consistency": document_issues,
            "possible_left_behind_lines": left_behind_items,
        },
        # Backward-compatible aliases consumed by earlier Lovable integrations.
        "pending_errors": pending_errors + extraction_issues,
        "warnings": warning_items + document_issues,
        "possible_left_behind_lines": left_behind_items,
        "applied_patches": _collect_patches(result),
        "supporting_material": {
            "evidence_registry_path": "documento_evidencias.evidence_registry",
            "physical_block_coverage_path": "documento_evidencias.physical_block_coverage",
            "row_inventory_proof_path": "documento_evidencias.row_inventory_proof",
            "light_diff_scan_path": "documento_evidencias.light_reextraction_diff_scan",
            "debug_recovery_path": "analise_orcamentaria.debug_recovery",
            "contract_documentation": "docs/lovable_contracts/13_CORRECTION_DOCUMENT_UI_REVIEW_CONTRACT.md",
        },
    }
    corr = result.setdefault("documento_correcao", {})
    corr["schema_version"] = "correction_document.v2.actionable_review"
    compact_clean = _clean_empty(compact)
    # Keep stable list keys even when empty; this is easier for Lovable and
    # preserves backward compatibility with older consumers/tests.
    for list_key in ("problemas", "pending_errors", "warnings", "possible_left_behind_lines", "applied_patches"):
        compact_clean.setdefault(list_key, [])
    compact_clean.setdefault("problemas_por_categoria", {
        "quality_gate": [],
        "extraction": [],
        "document_consistency": [],
        "possible_left_behind_lines": [],
    })
    corr["resumo_final_curto"] = compact_clean
    # Store only the problem list/index at top level for easy UI lookup; heavy
    # debug remains outside documento_correcao.
    corr["problemas"] = compact_clean.get("problemas", [])
    corr["problemas_por_categoria"] = compact_clean.get("problemas_por_categoria", {})
    result.setdefault("meta", {}).setdefault("performance", {})["compact_correction_document"] = {
        "version": CURRENT_RELEASE,
        "schema_version": "correction_document.v2.actionable_review",
        "problem_count": len(problems),
        "pending_errors": len(pending_errors) + len(extraction_issues),
        "warnings": len(warning_items) + len(document_issues),
        "possible_left_behind_lines": len(left_behind_items),
        "applied_patches": len(compact["applied_patches"]),
    }
    return _clean_empty(compact)
