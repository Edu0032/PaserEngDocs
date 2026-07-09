from __future__ import annotations

from typing import Any, Dict, List

VERSION = "v61.0.39-deep-area-sweep-iterative-closure"


def _clean(v: Any) -> str:
    return " ".join(str(v or "").replace("\u00a0", " ").split()).strip()


def _weak_reason(value: Any) -> str:
    text = _clean(value)
    if not text:
        return "empty"
    tail = (text.upper().split() or [""])[-1]
    if tail in {"DE", "DA", "DO", "DAS", "DOS", "PARA", "COM", "E", "EM", "A", "O"}:
        return "ends_with_connector"
    if len(text) < 42 and "AF_" not in text.upper():
        return "short_without_service_anchor"
    if text.startswith("-"):
        return "leading_orphan_fragment"
    if "=>" in text:
        return "summary_marker_leaked"
    return ""


def build_weak_field_reparse_targets(final_result: Dict[str, Any] | None, document_learning_profile: Dict[str, Any] | None = None) -> Dict[str, Any]:
    final_result = final_result or {}
    targets: List[Dict[str, Any]] = []

    def add_budget(nodes: Any, path: List[Any]) -> None:
        if not isinstance(nodes, list):
            return
        for idx, node in enumerate(nodes):
            if not isinstance(node, dict):
                continue
            cur_path = path + [idx]
            if node.get("codigo"):
                reason = _weak_reason(node.get("especificacao") or node.get("descricao"))
                if reason:
                    targets.append({
                        "target_id": ".".join(map(str, cur_path)) + "::especificacao",
                        "path": ["orcamento_sintetico", "itens_raiz", *cur_path[2:], "especificacao"] if cur_path[:2] == ["orcamento_sintetico", "itens_raiz"] else cur_path + ["especificacao"],
                        "family": "budget",
                        "table_family": "budget",
                        "field": "especificacao",
                        "codigo": node.get("codigo"),
                        "banco": node.get("fonte"),
                        "current_value": node.get("especificacao") or node.get("descricao") or "",
                        "page": node.get("pagina") or node.get("pagina_inicio") or node.get("page_hint"),
                        "reason": reason,
                        "priority": 1 if reason in {"empty", "summary_marker_leaked"} else 2,
                    })
            add_budget(node.get("filhos"), cur_path + ["filhos"])
    add_budget(((final_result.get("orcamento_sintetico") or {}).get("itens_raiz") or []), ["orcamento_sintetico", "itens_raiz"])

    comp = final_result.get("composicoes") if isinstance(final_result.get("composicoes"), dict) else {}
    for family in ("sinapi_like",):
        fam = comp.get(family) if isinstance(comp.get(family), dict) else {}
        for collection in ("principais", "auxiliares_globais"):
            blocks = fam.get(collection) if isinstance(fam, dict) else None
            if not isinstance(blocks, dict):
                continue
            for key, block in blocks.items():
                if not isinstance(block, dict):
                    continue
                principal = block.get("principal") if isinstance(block.get("principal"), dict) else {}
                if principal:
                    reason = _weak_reason(principal.get("descricao"))
                    if reason:
                        targets.append({"target_id": f"composicoes.{family}.{collection}.{key}.principal::descricao", "path": ["composicoes", family, collection, key, "principal", "descricao"], "family": "sinapi_like", "table_family": "composition", "collection": collection, "comp_key": key, "row_group": "principal", "field": "descricao", "codigo": principal.get("codigo"), "banco": principal.get("banco"), "current_value": principal.get("descricao") or "", "page": block.get("pagina_inicio"), "reason": reason, "priority": 1 if reason == "empty" else 2})
                for group in ("composicoes_auxiliares", "insumos"):
                    rows = block.get(group)
                    if not isinstance(rows, list):
                        continue
                    for i, row in enumerate(rows):
                        if not isinstance(row, dict):
                            continue
                        reason = _weak_reason(row.get("descricao"))
                        if reason:
                            targets.append({"target_id": f"composicoes.{family}.{collection}.{key}.{group}.{i}::descricao", "path": ["composicoes", family, collection, key, group, i, "descricao"], "family": "sinapi_like", "table_family": "composition", "collection": collection, "comp_key": key, "row_group": group, "row_index": i, "field": "descricao", "codigo": row.get("codigo"), "banco": row.get("banco"), "current_value": row.get("descricao") or "", "page": row.get("page_hint") or block.get("pagina_inicio"), "reason": reason, "priority": 1 if reason == "empty" else 3})
    profile_targets = []
    plan = (document_learning_profile or {}).get("selective_reparse_plan") if isinstance(document_learning_profile, dict) else None
    if isinstance(plan, dict):
        profile_targets = list(plan.get("budget_targets") or []) + list(plan.get("composition_targets") or [])
    return {
        "version": VERSION,
        "mode": "weak_field_selective_reparse",
        "targets": targets[:200],
        "profile_plan_targets": profile_targets[:200],
        "summary": {"targets": len(targets), "profile_plan_targets": len(profile_targets), "budget_targets": sum(1 for t in targets if t.get("family") == "budget"), "composition_targets": sum(1 for t in targets if t.get("family") == "sinapi_like")},
    }
