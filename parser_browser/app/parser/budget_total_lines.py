from __future__ import annotations

"""Inline budget total presentation and compact total evidence index.

Global, document-independent policy:
- meta/submeta totals are public fields on the hierarchy node itself (`custo_total`),
  not detached display rows;
- item leaves keep `custo_parcial` as their public total field;
- the root total stays at `orcamento_sintetico.total`;
- an optional compact evidence/display index is stored under `documento_evidencias`,
  not as an alternate public budget structure.
"""

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List

from app.config.version import CURRENT_RELEASE


def _parse_ptbr_money(value: Any) -> Decimal | None:
    if value in (None, "", [], {}):
        return None
    text = str(value).strip().replace("R$", "").replace(" ", "")
    if not text:
        return None
    text = text.replace(".", "").replace(",", ".")
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _format_ptbr_money(value: Any) -> str:
    dec = _parse_ptbr_money(value)
    if dec is None:
        return str(value or "")
    q = dec.quantize(Decimal("0.01"))
    sign = "-" if q < 0 else ""
    q = abs(q)
    inteiro, frac = f"{q:.2f}".split(".")
    parts: List[str] = []
    while inteiro:
        parts.append(inteiro[-3:])
        inteiro = inteiro[:-3]
    return sign + ".".join(reversed(parts or ["0"])) + "," + frac


def _iter_nodes(nodes: Any, path: str = "orcamento_sintetico.itens_raiz"):
    if not isinstance(nodes, list):
        return
    for idx, node in enumerate(nodes):
        if not isinstance(node, dict):
            continue
        cur = f"{path}.{idx}"
        yield cur, node
        filhos = node.get("filhos")
        if isinstance(filhos, list):
            yield from _iter_nodes(filhos, f"{cur}.filhos")


def _level_from_item(item: Any) -> int:
    text = str(item or "")
    return 1 + text.count(".") if text else 0


def _public_source_for_node(node: Dict[str, Any]) -> str:
    audits = ((node.get("_audit") or {}).get("budget_total_ownership") or []) if isinstance(node.get("_audit"), dict) else []
    for audit in audits:
        if isinstance(audit, dict) and audit.get("action") in {"accepted_reassigned_from_child", "removed_wrong_owner_public_total"}:
            return "pdf_declared_reassigned_owner"
    return "pdf_declared"


def _find_same_token(value: Any, declared_tokens: Iterable[str]) -> str:
    dec = _parse_ptbr_money(value)
    if dec is None:
        return str(value or "")
    for tok in declared_tokens:
        tok_s = str(tok or "")
        if _parse_ptbr_money(tok_s) == dec and "." in tok_s:
            return tok_s
    return _format_ptbr_money(value)


def _display_total_field_for_node(node: Dict[str, Any]) -> str:
    if node.get("tipo") in {"meta", "submeta"} or (node.get("filhos") and node.get("custo_total") not in (None, "", [], {})):
        return "custo_total"
    return "custo_parcial"


def build_budget_total_lines(result: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize inline public totals and build an evidence-only display index.

    The public budget tree remains the source of truth.  This function does not
    create detached public total rows; it only ensures tokens are textual PDF-like
    and records an index for UI/audit support in documento_evidencias.
    """
    if not isinstance(result, dict):
        return {}
    budget = result.get("orcamento_sintetico") if isinstance(result.get("orcamento_sintetico"), dict) else None
    if budget is None:
        return {}

    nodes = list(_iter_nodes(budget.get("itens_raiz") or []))
    declared_tokens = [str(n.get("custo_total")) for _p, n in nodes if isinstance(n, dict) and n.get("custo_total") not in (None, "", [], {})]
    if budget.get("total") not in (None, "", [], {}):
        declared_tokens.append(str(budget.get("total")))

    total_token = _find_same_token(budget.get("total"), declared_tokens)
    if total_token:
        budget["total"] = total_token

    total_index: List[Dict[str, Any]] = []
    if total_token:
        total_index.append({
            "tipo": "total_geral",
            "descricao": "TOTAL GERAL",
            "valor": total_token,
            "source": "pdf_declared",
            "path": "orcamento_sintetico.total",
            "display_location": "orcamento_sintetico.total",
        })

    inline_total_nodes = 0
    for path, node in nodes:
        if not isinstance(node, dict):
            continue
        field = _display_total_field_for_node(node)
        val = node.get(field)
        if val in (None, "", [], {}):
            continue
        token = _find_same_token(val, declared_tokens)
        if field == "custo_total" and token != val:
            node[field] = token
        # Record display semantics on the node, but keep the public value inline.
        node.setdefault("_display", {})["total_field"] = field
        if field == "custo_total":
            inline_total_nodes += 1
            node["_display"]["total_display_policy"] = "show_inline_with_meta_or_submeta_fields"
            total_index.append({
                "tipo": "meta_total" if node.get("tipo") == "meta" or _level_from_item(node.get("item")) == 1 else "submeta_total",
                "item": node.get("item"),
                "descricao": node.get("descricao") or node.get("especificacao"),
                "valor": token,
                "source": _public_source_for_node(node),
                "path": f"{path}.{field}",
                "display_location": "inline_budget_hierarchy_node",
                "nivel": _level_from_item(node.get("item")),
            })

    # Backward cleanup: v72 stored detached total lines in the public budget.
    # Keep only a compact support index under evidence so the UI does not render
    # a duplicate/separate budget line list.
    budget.pop("linhas_totais", None)
    budget.setdefault("display_policy", {})["totals"] = {
        "meta_submeta_totals": "show_custo_total_inline_on_the_same_hierarchy_node",
        "leaf_totals": "show_custo_parcial_inline_on_leaf_items",
        "root_total": "show_orcamento_sintetico_total",
        "do_not_render_documento_evidencias_total_index_as_public_rows": True,
        "version": CURRENT_RELEASE,
    }

    report = {
        "version": CURRENT_RELEASE,
        "status": "ok",
        "public_budget_has_detached_total_lines": False,
        "inline_total_node_count": inline_total_nodes,
        "total_index_count": len(total_index),
        "has_total_geral": bool(total_token),
        "total_token": budget.get("total"),
        "total_index": total_index[:200],
        "policy": "display_meta_submeta_totals_inline_with_hierarchy_nodes_not_as_detached_public_rows",
    }
    result.setdefault("documento_evidencias", {})["budget_total_display_index"] = report
    result.setdefault("meta", {}).setdefault("performance", {})["budget_total_lines"] = {k: v for k, v in report.items() if k != "total_index"}
    return report


def apply_budget_total_lines(result: Dict[str, Any]) -> Dict[str, Any]:
    return build_budget_total_lines(result)
