from __future__ import annotations

"""Actionable accuracy report for Lovable output (v61.0.57).

This report is intentionally not a version comparator.  It summarizes the
current extraction with enough numbers and examples for Lovable/users to know
what is reliable, what needs review, and what is only internal diagnostics.
"""

from typing import Any, Dict, Iterable, List, Tuple

from app.parser.numeric_constraint_solver import parse_ptbr_number, format_ptbr_number

VERSION = "v61.0.75-correction-output-contract-and-review-index"

BUDGET_REQUIRED = ("codigo", "fonte", "especificacao", "und", "quant", "custo_unitario_com_bdi", "custo_parcial")
COMPOSITION_REQUIRED = ("codigo", "banco", "descricao", "und", "quant", "valor_unit", "total")
COMPONENT_GROUPS = ("composicoes_auxiliares", "insumos", "materiais", "mao_obra", "equipamentos", "auxiliares")


def _clean(v: Any) -> str:
    return " ".join(str(v or "").replace("\u00a0", " ").split())


def _as_dict(v: Any) -> Dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _as_list(v: Any) -> List[Any]:
    return v if isinstance(v, list) else []


def _code_bank_key(code: Any, bank: Any) -> str:
    code_s = _clean(code).upper().replace(" ", "")
    bank_s = _clean(bank).upper().replace("PRÓPRIO", "PROPRIO").replace("PRÓPRIA", "PROPRIO")
    if bank_s == "SICRO3":
        bank_s = "SICRO"
    return f"{code_s}|{bank_s}" if code_s and bank_s else ""


def _iter_budget_items(final_result: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    def walk(nodes: Any):
        for node in _as_list(nodes):
            if not isinstance(node, dict):
                continue
            if node.get("codigo"):
                yield node
            yield from walk(node.get("filhos"))
    yield from walk(_as_dict(final_result.get("orcamento_sintetico")).get("itens_raiz"))


def _iter_comp_blocks(final_result: Dict[str, Any], family: str | None = None, collection: str | None = None):
    comp = _as_dict(final_result.get("composicoes"))
    # Split contract.
    for fam in ("sinapi_like", "sicro"):
        if family and fam != family:
            continue
        fam_obj = _as_dict(comp.get(fam))
        for coll in ("principais", "auxiliares_globais"):
            if collection and coll != collection:
                continue
            for key, block in _as_dict(fam_obj.get(coll)).items():
                if isinstance(block, dict):
                    yield fam, coll, str(key), block
    # Legacy contract.
    if family in (None, "sinapi_like"):
        for coll in ("principais", "auxiliares_globais"):
            if collection and coll != collection:
                continue
            for key, block in _as_dict(comp.get(coll)).items():
                if not isinstance(block, dict):
                    continue
                p = _as_dict(block.get("principal"))
                bank = _clean(p.get("banco") or p.get("fonte") or (str(key).split("|",1)[1] if "|" in str(key) else ""))
                fam = "sicro" if "SICRO" in bank.upper() else "sinapi_like"
                if family and fam != family:
                    continue
                yield fam, coll, str(key), block


def _required_missing(row: Dict[str, Any], required: Iterable[str]) -> List[str]:
    return [f for f in required if row.get(f) in (None, "", [], {})]


def _math_budget_ok(item: Dict[str, Any], tol: float = 0.05) -> Tuple[str, float | None]:
    q = parse_ptbr_number(item.get("quant"))
    unit = parse_ptbr_number(item.get("custo_unitario_com_bdi"))
    total = parse_ptbr_number(item.get("custo_parcial"))
    if q is None or unit is None or total is None:
        return "missing", None
    expected = round(q * unit, 2)
    delta = round(total - expected, 6)
    return ("ok" if abs(delta) <= tol else "mismatch"), delta


def _math_comp_triplet(row: Dict[str, Any], tol: float = 0.05) -> Tuple[str, float | None]:
    q = parse_ptbr_number(row.get("quant"))
    unit = parse_ptbr_number(row.get("valor_unit"))
    total = parse_ptbr_number(row.get("total"))
    if q is None or unit is None or total is None:
        return "missing", None
    expected = round(q * unit, 2)
    delta = round(total - expected, 6)
    return ("ok" if abs(delta) <= tol else "mismatch"), delta


def _component_sum(block: Dict[str, Any]) -> Tuple[float | None, int, int]:
    total = 0.0
    used = 0
    missing = 0
    for group in COMPONENT_GROUPS:
        for row in _as_list(block.get(group)):
            if not isinstance(row, dict):
                continue
            val = parse_ptbr_number(row.get("total"))
            if val is None:
                missing += 1
            else:
                used += 1
                total += val
    return (round(total, 6), used, missing) if used else (None, 0, missing)


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 6) if den else None


def build_output_accuracy_report(final_result: Dict[str, Any] | None, closure_report: Dict[str, Any] | None = None) -> Dict[str, Any]:
    final = final_result if isinstance(final_result, dict) else {}
    closure = closure_report if isinstance(closure_report, dict) else {}

    budget_items = list(_iter_budget_items(final))
    budget_missing_examples: List[Dict[str, Any]] = []
    budget_math_examples: List[Dict[str, Any]] = []
    budget_required_ok = 0
    budget_math_ok = 0
    budget_math_missing = 0
    budget_math_mismatch = 0
    for item in budget_items:
        missing = _required_missing(item, BUDGET_REQUIRED)
        if not missing:
            budget_required_ok += 1
        elif len(budget_missing_examples) < 30:
            budget_missing_examples.append({"item": item.get("item"), "codigo": item.get("codigo"), "fonte": item.get("fonte"), "missing": missing})
        status, delta = _math_budget_ok(item)
        if status == "ok":
            budget_math_ok += 1
        elif status == "missing":
            budget_math_missing += 1
        else:
            budget_math_mismatch += 1
            if len(budget_math_examples) < 30:
                budget_math_examples.append({"item": item.get("item"), "codigo": item.get("codigo"), "delta": delta, "quant": item.get("quant"), "custo_unitario_com_bdi": item.get("custo_unitario_com_bdi"), "custo_parcial": item.get("custo_parcial")})

    budget_index = {_code_bank_key(i.get("codigo"), i.get("fonte") or i.get("banco")): i for i in budget_items if _code_bank_key(i.get("codigo"), i.get("fonte") or i.get("banco"))}

    main_blocks = list(_iter_comp_blocks(final, "sinapi_like", "principais"))
    aux_globals = list(_iter_comp_blocks(final, "sinapi_like", "auxiliares_globais"))
    aux_global_keys = {str(k) for _f, _c, k, _b in aux_globals}
    comp_required_ok = 0
    comp_triplet_ok = 0
    comp_triplet_missing = 0
    comp_triplet_mismatch = 0
    comp_component_ok = 0
    comp_component_missing = 0
    comp_component_mismatch = 0
    comp_examples: List[Dict[str, Any]] = []
    missing_aux_global: List[Dict[str, Any]] = []
    for _fam, coll, key, block in main_blocks:
        p = _as_dict(block.get("principal"))
        missing = _required_missing(p, COMPOSITION_REQUIRED)
        if not missing:
            comp_required_ok += 1
        status, delta = _math_comp_triplet(p)
        if status == "ok":
            comp_triplet_ok += 1
        elif status == "missing":
            comp_triplet_missing += 1
        else:
            comp_triplet_mismatch += 1
        csum, used, missing_totals = _component_sum(block)
        ptotal = parse_ptbr_number(p.get("total"))
        if csum is not None and ptotal is not None and missing_totals == 0:
            if abs(round(ptotal - csum, 6)) <= max(0.05, abs(ptotal) * 0.001):
                comp_component_ok += 1
            else:
                comp_component_mismatch += 1
        else:
            comp_component_missing += 1
        if (missing or status != "ok" or (csum is not None and ptotal is not None and abs(round(ptotal-csum,6)) > max(0.05, abs(ptotal)*0.001))) and len(comp_examples) < 40:
            comp_examples.append({
                "key": key, "item": block.get("item"), "codigo": p.get("codigo"), "banco": p.get("banco"),
                "missing_principal_fields": missing, "triplet_status": status, "triplet_delta": delta,
                "component_sum": format_ptbr_number(csum) if csum is not None else None, "component_rows": used,
                "missing_component_totals": missing_totals,
            })
        for row in _as_list(block.get("composicoes_auxiliares")):
            if not isinstance(row, dict):
                continue
            rkey = _code_bank_key(row.get("codigo"), row.get("banco") or row.get("fonte"))
            if rkey and rkey not in aux_global_keys and len(missing_aux_global) < 80:
                row_complete = not _required_missing(row, ("codigo", "banco", "descricao", "und", "quant", "valor_unit", "total"))
                missing_aux_global.append({
                    "codigo_banco": rkey,
                    "parent_composition": key,
                    "item": block.get("item"),
                    "severity": "warning" if row_complete else "review",
                    "impact": "linha interna completa; ausência da global não bloqueia" if row_complete else "global ausente e linha interna incompleta; revisar",
                })

    sicro_principals = list(_iter_comp_blocks(final, "sicro", "principais"))
    sicro_aux = list(_iter_comp_blocks(final, "sicro", "auxiliares_globais"))
    sicro_with_item_without_budget: List[Dict[str, Any]] = []
    for _fam, coll, key, block in sicro_principals:
        p = _as_dict(block.get("principal"))
        bkey = _code_bank_key(p.get("codigo") or key.split("|")[0], p.get("banco") or "SICRO")
        if block.get("item") and bkey not in budget_index and len(sicro_with_item_without_budget) < 80:
            sicro_with_item_without_budget.append({"codigo_banco": bkey, "item": block.get("item"), "severity": "review", "message": "tem item e continua principal; não foi encontrada referência no sintético"})

    corr = _as_dict(final.get("documento_correcao"))
    human = _as_dict(corr.get("auditoria_humana"))
    hsummary = _as_dict(human.get("summary"))
    qgate = _as_dict(_as_dict(final.get("auditoria_final")).get("quality_gate"))

    blocking_errors = 0
    if budget_math_mismatch or budget_math_missing:
        blocking_errors += 1
    if comp_triplet_mismatch or comp_triplet_missing:
        blocking_errors += 1
    if qgate and qgate.get("ok") is False:
        blocking_errors += 1

    try:
        from app.parser.semantic_consistency import build_entity_confidence_report, build_component_mismatch_diagnostics
        entity_confidence = build_entity_confidence_report(final, limit_examples=360)
        component_diagnostics = build_component_mismatch_diagnostics(final, limit=160)
    except Exception as _sem_exc:
        entity_confidence = {"version": VERSION, "status": "error", "error": str(_sem_exc)}
        component_diagnostics = {"version": VERSION, "status": "error", "error": str(_sem_exc)}

    status = "ok" if blocking_errors == 0 else "needs_review"
    return {
        "version": VERSION,
        "document_type": "accuracy_report",
        "status": status,
        "principle": "métricas acionáveis; diagnósticos internos não viram erro público sem afetar campo/conta/estrutura final",
        "summary": {
            "blocking_error_groups": blocking_errors,
            "quality_gate_ok": qgate.get("ok") if qgate else None,
            "lovable_review_queue_count": hsummary.get("review_queue_count"),
            "budget_math_ok_rate": _rate(budget_math_ok, len(budget_items)),
            "budget_required_field_rate": _rate(budget_required_ok, len(budget_items)),
            "composition_principal_required_field_rate": _rate(comp_required_ok, len(main_blocks)),
            "composition_principal_triplet_ok_rate": _rate(comp_triplet_ok, len(main_blocks)),
            "composition_component_sum_ok_rate": _rate(comp_component_ok, len(main_blocks)),
        },
        "budget": {
            "leaf_items": len(budget_items),
            "required_fields_ok": budget_required_ok,
            "required_fields_missing": len(budget_items) - budget_required_ok,
            "math_checked": len(budget_items),
            "math_ok": budget_math_ok,
            "math_missing": budget_math_missing,
            "math_mismatch": budget_math_mismatch,
            "missing_examples": budget_missing_examples,
            "math_problem_examples": budget_math_examples,
        },
        "compositions": {
            "sinapi_like_principals": len(main_blocks),
            "sinapi_like_auxiliares_globais": len(aux_globals),
            "principal_required_fields_ok": comp_required_ok,
            "principal_required_fields_missing": len(main_blocks) - comp_required_ok,
            "principal_triplet_ok": comp_triplet_ok,
            "principal_triplet_missing": comp_triplet_missing,
            "principal_triplet_mismatch": comp_triplet_mismatch,
            "component_sum_ok": comp_component_ok,
            "component_sum_missing_or_not_validatable": comp_component_missing,
            "component_sum_mismatch": comp_component_mismatch,
            "problem_examples": comp_examples,
            "auxiliares_internas_sem_global": {
                "count": len(missing_aux_global),
                "examples": missing_aux_global,
                "policy": "não é erro fatal; se a linha interna está completa, Lovable trata como aviso de referência ausente",
            },
        },
        "sicro": {
            "principais": len(sicro_principals),
            "auxiliares_globais": len(sicro_aux),
            "principais_com_item_sem_referencia_sintetico": sicro_with_item_without_budget,
            "policy": "tem item = principal; sem item = auxiliar global; ausência de referência no sintético é revisão Lovable, não reclassificação automática",
        },
        "component_mismatch_diagnostics": component_diagnostics,
        "entity_confidence_report": entity_confidence,
        "correction_document": {
            "review_queue_count": hsummary.get("review_queue_count"),
            "strict_unresolved_rows": hsummary.get("strict_unresolved_rows"),
            "reference_review_items": hsummary.get("reference_review_items"),
            "targeted_recovery_diagnostic_ignored": hsummary.get("targeted_recovery_diagnostic_ignored"),
            "targeted_recovery_actionable_unresolved": hsummary.get("targeted_recovery_actionable_unresolved"),
        },
    }
