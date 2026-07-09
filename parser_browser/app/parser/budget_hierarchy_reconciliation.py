from __future__ import annotations

"""Budget hierarchy reconciliation (v61.0.44).

Checks whether meta/submeta totals are explained by child item totals. This is a
non-fatal audit that helps detect missing leaf rows, wrong levels and polluted
subtotals.
"""

from typing import Any, Dict, List, Tuple

from app.parser.numeric_constraint_solver import parse_ptbr_number

VERSION = "v61.0.75-correction-output-contract-and-review-index"


def _clean(value: Any) -> str:
    return " ".join(str(value or "").replace("\u00a0", " ").split())


def _node_total(node: Dict[str, Any]) -> Any:
    for field in ("custo_total", "custo_parcial", "total"):
        if isinstance(node, dict) and node.get(field) not in (None, ""):
            return node.get(field)
    return ""


def _walk(node: Dict[str, Any], path: List[Any], rows: List[Dict[str, Any]], tolerance: float) -> float:
    filhos = node.get("filhos") if isinstance(node.get("filhos"), list) else []
    own_total = parse_ptbr_number(_node_total(node))
    if not filhos:
        return own_total or 0.0
    child_sum = 0.0
    for idx, child in enumerate(filhos):
        if isinstance(child, dict):
            child_sum += _walk(child, path + ["filhos", idx], rows, tolerance)
    if own_total is None:
        status = "parent_total_missing"
        ok = False
        delta = None
    else:
        delta_val = child_sum - own_total
        delta = round(delta_val, 6)
        ok = abs(delta_val) <= tolerance
        status = "ok" if ok else "mismatch"
    rows.append({
        "item": node.get("item"),
        "path": path,
        "descricao": node.get("descricao") or node.get("especificacao"),
        "parent_total": _node_total(node),
        "parent_numeric_total": own_total,
        "child_sum": round(child_sum, 6),
        "delta": delta,
        "tolerance": tolerance,
        "child_count": len(filhos),
        "ok": ok,
        "status": status,
    })
    return own_total if own_total is not None else child_sum


def build_budget_hierarchy_reconciliation(final_result: Dict[str, Any] | None, *, tolerance: float = 0.08) -> Dict[str, Any]:
    final_result = final_result if isinstance(final_result, dict) else {}
    roots = ((final_result.get("orcamento_sintetico") or {}).get("itens_raiz") or []) if isinstance(final_result.get("orcamento_sintetico"), dict) else []
    rows: List[Dict[str, Any]] = []
    for idx, root in enumerate(roots):
        if isinstance(root, dict):
            _walk(root, ["orcamento_sintetico", "itens_raiz", idx], rows, tolerance)
    summary = {
        "checked_parent_nodes": len(rows),
        "ok": sum(1 for r in rows if r.get("ok") is True),
        "mismatch": sum(1 for r in rows if r.get("status") == "mismatch"),
        "missing_parent_total": sum(1 for r in rows if r.get("status") == "parent_total_missing"),
    }
    return {"version": VERSION, "mode": "budget_hierarchy_reconciliation", "summary": summary, "rows": rows[:1000]}
