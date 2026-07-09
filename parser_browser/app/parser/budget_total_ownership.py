from __future__ import annotations

"""Budget subtotal ownership repair.

v61.0.62 policy:
- public totals must remain PDF-declared values;
- if a visually extracted subtotal was attached to the wrong hierarchy level,
  move the exact text token to the level whose descendants explain it;
- never replace a PDF-declared public total with a recalculated total.
"""

from typing import Any, Dict, List, Tuple

from app.parser.numeric_constraint_solver import parse_ptbr_number

VERSION = "v61.0.75-correction-output-contract-and-review-index"


def _clean(value: Any) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split()).strip()


def _num(value: Any) -> float | None:
    try:
        return parse_ptbr_number(value)
    except Exception:
        return None


def _leaf_total(node: Dict[str, Any]) -> float:
    if not isinstance(node, dict):
        return 0.0
    filhos = node.get("filhos")
    if isinstance(filhos, list) and filhos:
        return round(sum(_leaf_total(ch) for ch in filhos if isinstance(ch, dict)), 6)
    for field in ("custo_parcial", "custo_total", "total"):
        n = _num(node.get(field))
        if n is not None:
            return float(n)
    return 0.0


def _own_total_text(node: Dict[str, Any]) -> str:
    if not isinstance(node, dict):
        return ""
    for field in ("custo_total", "custo_parcial", "total"):
        if node.get(field) not in (None, ""):
            return _clean(node.get(field))
    return ""


def _get_children(node: Dict[str, Any]) -> List[Dict[str, Any]]:
    filhos = node.get("filhos") if isinstance(node, dict) else None
    return [ch for ch in filhos if isinstance(ch, dict)] if isinstance(filhos, list) else []


def _ensure_audit(node: Dict[str, Any]) -> Dict[str, Any]:
    audit = node.setdefault("_audit", {})
    if not isinstance(audit, dict):
        node["_audit"] = audit = {}
    return audit


def _remove_public_total(node: Dict[str, Any]) -> str:
    for field in ("custo_total", "total"):
        if isinstance(node, dict) and node.get(field) not in (None, ""):
            return _clean(node.pop(field))
    return ""


def _walk_parent_child(parent: Dict[str, Any], path: List[Any], report: Dict[str, Any], *, tolerance: float) -> None:
    children = _get_children(parent)
    for idx, child in enumerate(children):
        _walk_parent_child(child, path + ["filhos", idx], report, tolerance=tolerance)

    if not children:
        return

    parent_num = _num(parent.get("custo_total"))
    parent_leaf_sum = _leaf_total(parent)

    # If a child carries a subtotal that cannot belong to itself, but exactly
    # explains the full parent subtree, the visual subtotal was assigned to the
    # wrong hierarchy owner. Move the *same text token*, do not calculate a new
    # value.
    for idx, child in enumerate(children):
        if not isinstance(child, dict) or not _get_children(child):
            continue
        child_total_text = _own_total_text(child)
        child_total_num = _num(child_total_text)
        if child_total_num is None:
            continue
        child_leaf_sum = _leaf_total(child)
        if abs(child_total_num - child_leaf_sum) <= tolerance:
            continue
        if parent_num is None and abs(child_total_num - parent_leaf_sum) <= tolerance:
            moved_text = _remove_public_total(child)
            if not moved_text:
                continue
            parent["custo_total"] = moved_text
            parent_audit = _ensure_audit(parent)
            child_audit = _ensure_audit(child)
            parent_audit.setdefault("budget_total_ownership", []).append({
                "version": VERSION,
                "action": "accepted_reassigned_from_child",
                "source_child_item": child.get("item"),
                "source_child_path": path + ["filhos", idx],
                "value": moved_text,
                "reason": "child_total_mismatch_parent_descendants_match",
                "child_leaf_sum": round(child_leaf_sum, 2),
                "parent_leaf_sum": round(parent_leaf_sum, 2),
            })
            child_audit.setdefault("budget_total_ownership", []).append({
                "version": VERSION,
                "action": "removed_wrong_owner_public_total",
                "moved_to_parent_item": parent.get("item"),
                "value": moved_text,
                "reason": "subtotal_belongs_to_parent_not_this_submeta",
                "child_leaf_sum": round(child_leaf_sum, 2),
            })
            report["patches"].append({
                "action": "reassign_budget_total_owner",
                "from_item": child.get("item"),
                "to_item": parent.get("item"),
                "value": moved_text,
                "from_path": path + ["filhos", idx],
                "to_path": path,
                "child_leaf_sum": round(child_leaf_sum, 2),
                "parent_leaf_sum": round(parent_leaf_sum, 2),
            })
            # Only one such visual subtotal should explain this parent.
            parent_num = _num(parent.get("custo_total"))


def apply_budget_total_ownership_repair(result: Dict[str, Any], *, tolerance: float = 0.08) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    report: Dict[str, Any] = {
        "version": VERSION,
        "attempted": True,
        "policy": "move_pdf_declared_subtotal_to_semantic_owner_never_replace_by_chain_sum",
        "patches": [],
        "patches_applied": 0,
    }
    if not isinstance(result, dict):
        return result, report
    roots = (((result.get("orcamento_sintetico") or {}).get("itens_raiz") or []) if isinstance(result.get("orcamento_sintetico"), dict) else [])
    if isinstance(roots, list):
        for idx, root in enumerate(roots):
            if isinstance(root, dict):
                _walk_parent_child(root, ["orcamento_sintetico", "itens_raiz", idx], report, tolerance=tolerance)
    report["patches_applied"] = len(report["patches"])
    result.setdefault("meta", {}).setdefault("performance", {})["budget_total_ownership_repair"] = report
    result.setdefault("documento_correcao", {})["budget_total_ownership_repair"] = report
    return result, report
