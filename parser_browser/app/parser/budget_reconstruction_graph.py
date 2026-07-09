from __future__ import annotations

"""Budget Reconstruction Graph (v61.0.44).

Builds chain-level links that explain how the synthetic budget is assembled from
main compositions, contextual auxiliary rows, global auxiliaries and physical
occurrences.  This is intentionally not a SICRO engine; SICRO native output stays
authoritative and is only represented as entities/links when already present in
final_result.
"""

from typing import Any, Dict, List, Tuple

VERSION = "v61.0.75-correction-output-contract-and-review-index"


def _clean(value: Any) -> str:
    return " ".join(str(value or "").replace("\u00a0", " ").split())


def _norm_bank(value: Any) -> str:
    text = _clean(value).upper()
    return "PROPRIO" if text == "PRÓPRIO" else text


def _entity(graph: Dict[str, Any], entity_id: str) -> Dict[str, Any]:
    entities = graph.get("entities") if isinstance(graph.get("entities"), dict) else {}
    ent = entities.get(entity_id) if isinstance(entities.get(entity_id), dict) else {}
    return ent


def _fields(ent: Dict[str, Any]) -> Dict[str, Any]:
    return ent.get("fields") if isinstance(ent.get("fields"), dict) else {}


def _key(ent: Dict[str, Any]) -> str:
    return _clean(ent.get("key"))


def _physical_occurrences_for_key(physical_index: Dict[str, Any] | None, key: str) -> List[Dict[str, Any]]:
    if not key or not isinstance(physical_index, dict):
        return []
    bucket = ((physical_index.get("keys") or {}).get(key) or {}) if isinstance(physical_index.get("keys"), dict) else {}
    occ = bucket.get("occurrences") if isinstance(bucket.get("occurrences"), list) else []
    return [o for o in occ if isinstance(o, dict)][:30]


def build_budget_reconstruction_graph(final_result: Dict[str, Any] | None, entity_graph: Dict[str, Any] | None = None, physical_index: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Build chain graph from already-parsed entities.

    The graph is tolerant: missing global auxiliaries are recorded as auditable
    issues because real engineering budgets often omit expanded auxiliary blocks.
    They are not fatal and do not remove the contextual auxiliary row from its
    principal chain.
    """
    graph = entity_graph if isinstance(entity_graph, dict) else {}
    relations = [r for r in (graph.get("relations") or []) if isinstance(r, dict)]
    entities = graph.get("entities") if isinstance(graph.get("entities"), dict) else {}
    by_key = graph.get("by_key") if isinstance(graph.get("by_key"), dict) else {}

    inside_by_principal: Dict[str, List[Dict[str, Any]]] = {}
    contextual_to_global: Dict[str, List[str]] = {}
    budget_to_principal: List[Tuple[str, str, Dict[str, Any]]] = []

    for rel in relations:
        rtype = rel.get("type")
        if rtype == "inside_principal":
            inside_by_principal.setdefault(str(rel.get("to") or ""), []).append(rel)
        elif rtype == "contextual_auxiliary_global":
            contextual_to_global.setdefault(str(rel.get("from") or ""), []).append(str(rel.get("to") or ""))
        elif rtype == "budget_main_composition":
            budget_to_principal.append((str(rel.get("from") or ""), str(rel.get("to") or ""), rel))

    chains: List[Dict[str, Any]] = []
    missing_global_aux: List[Dict[str, Any]] = []

    for budget_id, principal_id, rel in budget_to_principal:
        budget_ent = _entity(graph, budget_id)
        principal_ent = _entity(graph, principal_id)
        key = rel.get("key") or _key(principal_ent) or _key(budget_ent)
        internal_rows: List[Dict[str, Any]] = []
        for inside in inside_by_principal.get(principal_id, []):
            child_id = str(inside.get("from") or "")
            child = _entity(graph, child_id)
            child_key = _key(child)
            matched_globals = contextual_to_global.get(child_id, [])
            internal_record = {
                "entity_id": child_id,
                "kind": child.get("kind"),
                "key": child_key,
                "codigo": child.get("codigo"),
                "banco": child.get("banco"),
                "fields": _fields(child),
                "matched_global_auxiliary_ids": matched_globals,
                "has_global_auxiliary": bool(matched_globals),
            }
            internal_rows.append(internal_record)
            if child.get("kind", "").startswith("contextual_composicoes_auxiliares") and not matched_globals:
                missing_global_aux.append({
                    "code": "contextual_auxiliary_without_global_expansion",
                    "severity": "warning",
                    "principal_entity_id": principal_id,
                    "contextual_entity_id": child_id,
                    "key": child_key,
                    "message": "Auxiliar referenciada dentro de composição principal não possui auxiliar global expandida; isso pode ocorrer por omissão do orçamento e não deve quebrar o parser.",
                })
        occurrences = _physical_occurrences_for_key(physical_index, str(key))
        chains.append({
            "chain_id": f"chain:{key}:{len(chains)}",
            "key": key,
            "budget_item_id": budget_id,
            "main_composition_id": principal_id,
            "budget_item": {"entity_id": budget_id, "item": budget_ent.get("item"), "fields": _fields(budget_ent)},
            "main_composition": {"entity_id": principal_id, "item": principal_ent.get("item"), "fields": _fields(principal_ent)},
            "internal_rows": internal_rows,
            "internal_row_count": len(internal_rows),
            "global_auxiliary_match_count": sum(1 for r in internal_rows if r.get("has_global_auxiliary")),
            "missing_global_auxiliary_count": sum(1 for r in internal_rows if not r.get("has_global_auxiliary") and str(r.get("kind") or "").startswith("contextual_composicoes_auxiliares")),
            "physical_occurrence_count": len(occurrences),
            "physical_occurrences": occurrences[:10],
            "status": "linked_budget_to_main_composition",
        })

    linked_principals = {c.get("main_composition_id") for c in chains}
    unlinked_principals: List[Dict[str, Any]] = []
    for eid, ent in entities.items():
        kind = str(ent.get("kind") or "")
        if "principais_principal" in kind and eid not in linked_principals:
            unlinked_principals.append({"entity_id": eid, "key": ent.get("key"), "kind": kind, "reason": "main_composition_without_budget_item_relation"})

    return {
        "version": VERSION,
        "mode": "budget_reconstruction_graph",
        "chain_count": len(chains),
        "chains": chains[:1000],
        "missing_global_auxiliaries": missing_global_aux[:500],
        "unlinked_principals": unlinked_principals[:500],
        "summary": {
            "chains": len(chains),
            "internal_rows": sum(int(c.get("internal_row_count") or 0) for c in chains),
            "global_auxiliary_matches": sum(int(c.get("global_auxiliary_match_count") or 0) for c in chains),
            "missing_global_auxiliaries": len(missing_global_aux),
            "unlinked_principals": len(unlinked_principals),
            "physical_occurrences": sum(int(c.get("physical_occurrence_count") or 0) for c in chains),
        },
    }


def compact_budget_reconstruction_graph(report: Dict[str, Any] | None, *, max_chains: int = 80) -> Dict[str, Any]:
    report = report if isinstance(report, dict) else {}
    return {
        "version": VERSION,
        "mode": report.get("mode") or "budget_reconstruction_graph",
        "summary": report.get("summary") or {},
        "chain_count": report.get("chain_count", 0),
        "sample_chains": (report.get("chains") or [])[:max_chains],
        "missing_global_auxiliaries": (report.get("missing_global_auxiliaries") or [])[:120],
        "unlinked_principals": (report.get("unlinked_principals") or [])[:120],
    }
