from __future__ import annotations

"""Composition principal cascade repair (v61.0.50).

Audits incomplete SINAPI-like composition principal rows by using available
evidence, without turning calculations into public extracted values.

v61.0.59 document-fidelity contract:

1. the composition's own reported PDF fields are sovereign;
2. component sums and linked budget values are audit/evidence only;
3. public numeric fields are never filled from recalculation/consensus.

Important contract: quantities are contextual.  This pass never copies the
budget quantity into the composition and no longer restores financial public
fields from component sums.  Missing public fields must be recovered from
physical PDF evidence by earlier extraction/reparse stages or stay pending for
correction.
"""

from typing import Any, Dict, Iterable, List, Tuple

from app.parser.document_evidence_index import code_bank_key
from app.parser.numeric_constraint_solver import parse_ptbr_number, format_ptbr_number, math_triplet_status

VERSION = "v61.0.75-correction-output-contract-and-review-index"
COMPONENT_GROUPS = ("composicoes_auxiliares", "insumos", "materiais", "mao_obra", "equipamentos", "auxiliares")


def _clean(v: Any) -> str:
    return " ".join(str(v or "").replace("\u00a0", " ").split())


def _empty(v: Any) -> bool:
    return v in (None, "")


def _set_path(root: Dict[str, Any], path: List[Any], value: Any) -> bool:
    cur: Any = root
    try:
        for p in path[:-1]:
            cur = cur[int(p)] if isinstance(cur, list) else cur[p]
        last = path[-1]
        if isinstance(cur, list):
            cur[int(last)] = value
        elif isinstance(cur, dict):
            cur[last] = value
        else:
            return False
        return True
    except Exception:
        return False


def _iter_budget_items(final_result: Dict[str, Any]) -> Iterable[Tuple[List[Any], Dict[str, Any]]]:
    def walk(nodes: Any, path: List[Any]):
        if not isinstance(nodes, list):
            return
        for idx, node in enumerate(nodes):
            if not isinstance(node, dict):
                continue
            p = path + [idx]
            if node.get("codigo"):
                yield p, node
            yield from walk(node.get("filhos"), p + ["filhos"])
    yield from walk(((final_result.get("orcamento_sintetico") or {}).get("itens_raiz") or []), ["orcamento_sintetico", "itens_raiz"])


def _budget_index(final_result: Dict[str, Any]) -> Dict[str, List[Tuple[List[Any], Dict[str, Any]]]]:
    out: Dict[str, List[Tuple[List[Any], Dict[str, Any]]]] = {}
    for path, item in _iter_budget_items(final_result):
        key = code_bank_key(item.get("codigo"), item.get("fonte") or item.get("banco"))
        if key:
            out.setdefault(key, []).append((path, item))
    return out


def _iter_sinapi_like_blocks(final_result: Dict[str, Any]) -> Iterable[Tuple[str, str, List[Any], Dict[str, Any]]]:
    comp = final_result.get("composicoes") if isinstance(final_result.get("composicoes"), dict) else {}
    # Current split contract.
    sinapi = comp.get("sinapi_like") if isinstance(comp.get("sinapi_like"), dict) else {}
    for collection in ("principais", "auxiliares_globais"):
        blocks = sinapi.get(collection) if isinstance(sinapi.get(collection), dict) else {}
        for key, block in blocks.items():
            if isinstance(block, dict):
                yield collection, str(key), ["composicoes", "sinapi_like", collection, key], block
    # Legacy flat collections may still be present in stage artifacts.
    for collection in ("principais", "auxiliares_globais"):
        blocks = comp.get(collection) if isinstance(comp.get(collection), dict) else {}
        for key, block in blocks.items():
            if not isinstance(block, dict):
                continue
            principal = block.get("principal") if isinstance(block.get("principal"), dict) else {}
            bank = _clean(principal.get("banco") or principal.get("fonte") or principal.get("banco_coluna") or (str(key).split("|", 1)[1] if "|" in str(key) else ""))
            if "SICRO" not in bank.upper():
                yield collection, str(key), ["composicoes", collection, key], block


def _component_sum(block: Dict[str, Any]) -> Tuple[float | None, int, int]:
    total = 0.0
    used = 0
    missing = 0
    seen = set()
    for group in COMPONENT_GROUPS:
        rows = block.get(group)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            marker = id(row)
            if marker in seen:
                continue
            seen.add(marker)
            n = parse_ptbr_number(row.get("total"))
            if n is None:
                missing += 1
            else:
                total += n
                used += 1
    if used == 0:
        return None, used, missing
    return round(total, 6), used, missing


def _pick_budget_item(matches: List[Tuple[List[Any], Dict[str, Any]]], block_item: str) -> Tuple[List[Any], Dict[str, Any]] | None:
    if not matches:
        return None
    block_item = _clean(block_item)
    if block_item:
        exact = [(p, r) for p, r in matches if _clean(r.get("item")) == block_item]
        if len(exact) == 1:
            return exact[0]
    if len(matches) == 1:
        return matches[0]
    return None


def _budget_sem_bdi_value(item: Dict[str, Any]) -> float | None:
    return parse_ptbr_number(item.get("custo_unitario_sem_bdi"))


def _same_money(a: float | None, b: float | None, tolerance: float = 0.05) -> bool:
    return a is not None and b is not None and abs(a - b) <= tolerance


def _record(block: Dict[str, Any], entry: Dict[str, Any]) -> None:
    detalhes = block.setdefault("detalhes", {})
    if isinstance(detalhes, dict):
        detalhes.setdefault("composition_principal_cascade_repair", []).append(entry)


def _update_detail_math(block: Dict[str, Any], principal: Dict[str, Any], component_sum: float | None, used_count: int, missing_count: int) -> None:
    detalhes = block.setdefault("detalhes", {})
    if not isinstance(detalhes, dict):
        return
    status = math_triplet_status(principal, quantity_field="quant", unit_field="valor_unit", total_field="total")
    detalhes["math_status"] = {
        **status,
        "strict_sum_validation": True,
        "principal_total": parse_ptbr_number(principal.get("total")),
        "component_sum": component_sum,
        "component_rows_count": used_count,
        "missing_component_totals": missing_count,
        "source": "composition_principal_cascade_repair",
    }
    missing_public = [f"principal:{f}" for f in ("und", "quant", "valor_unit", "total") if _empty(principal.get(f))]
    if missing_public:
        detalhes["status_completude"] = "pendente_revisao"
        detalhes["campos_faltantes_detectados"] = missing_public
    else:
        detalhes["status_completude"] = "completo"
        detalhes.pop("campos_faltantes_detectados", None)


def apply_composition_principal_cascade_repair(final_result: Dict[str, Any] | None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    result = final_result if isinstance(final_result, dict) else {}
    budget = _budget_index(result)
    repairs: List[Dict[str, Any]] = []
    blocked: List[Dict[str, Any]] = []

    for collection, block_key, block_path, block in list(_iter_sinapi_like_blocks(result)):
        principal = block.get("principal") if isinstance(block.get("principal"), dict) else None
        if not principal:
            continue
        codigo = _clean(principal.get("codigo") or (block_key.split("|", 1)[0] if "|" in block_key else ""))
        banco = _clean(principal.get("banco") or principal.get("fonte") or (block_key.split("|", 1)[1] if "|" in block_key else ""))
        key = code_bank_key(codigo, banco)
        if not key:
            continue
        component_sum, used_count, missing_count = _component_sum(block)
        budget_match = _pick_budget_item(budget.get(key, []), _clean(block.get("item")))
        budget_item = budget_match[1] if budget_match else None
        budget_sem = _budget_sem_bdi_value(budget_item) if budget_item else None
        component_supported = component_sum is not None and used_count > 0 and missing_count == 0
        budget_agrees = _same_money(component_sum, budget_sem) if component_supported and budget_sem is not None else False
        # Use component sum as authoritative when all internal component totals are present.
        # If a linked budget item exists, require agreement to write financial fields.
        write_financial = component_supported and (budget_item is None or budget_agrees)
        if component_supported and budget_item is not None and not budget_agrees:
            blocked.append({
                "block_key": block_key,
                "codigo": codigo,
                "banco": banco,
                "item": block.get("item"),
                "reason": "component_sum_disagrees_with_budget_sem_bdi",
                "component_sum": format_ptbr_number(component_sum),
                "budget_custo_unitario_sem_bdi": budget_item.get("custo_unitario_sem_bdi") if budget_item else None,
            })
        field_repairs: List[Dict[str, Any]] = []
        audit_notes: List[Dict[str, Any]] = []
        # Unit can safely come from linked budget only as same identity/context evidence.
        # Numeric public fields remain untouched unless they already came from PDF evidence.
        if _empty(principal.get("und")) and budget_item and budget_item.get("und"):
            value = _clean(budget_item.get("und"))
            principal["und"] = value
            field_repairs.append({"field": "und", "value": value, "source": "linked_budget_same_codigo_banco_item", "quantity_policy": "unit_only_no_quantity_copy"})

        missing_numeric = [f for f in ("quant", "valor_unit", "total") if _empty(principal.get(f))]
        if missing_numeric and component_supported:
            audit_notes.append({
                "tipo": "numeric_public_repair_blocked",
                "reason": "calculation_or_component_sum_is_audit_only_without_physical_pdf_token",
                "fields": missing_numeric,
                "component_sum_reported": format_ptbr_number(component_sum or 0.0),
                "linked_budget_custo_unitario_sem_bdi": budget_item.get("custo_unitario_sem_bdi") if budget_item else None,
            })
            blocked.append({
                "block_key": block_key,
                "codigo": codigo,
                "banco": banco,
                "item": block.get("item"),
                "reason": "public_numeric_repair_requires_physical_pdf_evidence",
                "fields": missing_numeric,
                "component_sum_reported": format_ptbr_number(component_sum or 0.0),
                "linked_budget_custo_unitario_sem_bdi": budget_item.get("custo_unitario_sem_bdi") if budget_item else None,
            })
        if component_supported:
            detalhes = block.setdefault("detalhes", {})
            if isinstance(detalhes, dict):
                calc = detalhes.setdefault("_calc", {})
                if isinstance(calc, dict):
                    calc["component_sum_reported"] = format_ptbr_number(component_sum or 0.0)
                    calc["component_rows_count"] = used_count
                    calc["missing_component_totals"] = missing_count
                    calc["public_numeric_policy"] = "audit_only_never_overwrite_pdf_public_fields"

        if field_repairs or audit_notes:
            entry = {
                "tipo": "composition_principal_cascade_repair",
                "block_key": block_key,
                "collection": collection,
                "codigo": codigo,
                "banco": banco,
                "item": block.get("item"),
                "path": block_path + ["principal"],
                "component_sum": format_ptbr_number(component_sum or 0.0) if component_sum is not None else None,
                "component_rows_count": used_count,
                "missing_component_totals": missing_count,
                "linked_budget_item": budget_item.get("item") if budget_item else None,
                "linked_budget_custo_unitario_sem_bdi": budget_item.get("custo_unitario_sem_bdi") if budget_item else None,
                "quantity_policy": "quantidades são contextuais; orçamento não sobrescreve composição; auxiliar/global também não sobrescreve consumo contextual",
                "repairs": field_repairs,
                "audit_notes": audit_notes,
                "numeric_policy": "calculation_is_audit_only_not_public_source",
            }
            if field_repairs:
                repairs.append(entry)
            _record(block, entry)
        _update_detail_math(block, principal, component_sum, used_count, missing_count)

    report = {
        "version": VERSION,
        "mode": "composition_principal_cascade_and_contextual_quantity_guard",
        "repairs": repairs,
        "blocked": blocked,
        "summary": {
            "repairs": len(repairs),
            "fields_repaired": sum(len(r.get("repairs") or []) for r in repairs),
            "blocked": len(blocked),
        },
    }
    if repairs or blocked:
        doc = result.setdefault("documento_correcao", {})
        if isinstance(doc, dict):
            doc["composition_principal_cascade_repair"] = report
            warnings = doc.setdefault("warnings", [])
            if isinstance(warnings, list):
                for r in repairs[:120]:
                    warnings.append({"tipo": "composition_principal_cascade_repair_applied", **r})
                for b in blocked[:120]:
                    warnings.append({"tipo": "composition_principal_cascade_repair_blocked", **b})
    result.setdefault("meta", {}).setdefault("performance", {})["composition_principal_cascade_repair"] = report
    return result, report
