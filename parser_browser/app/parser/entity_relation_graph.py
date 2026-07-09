from __future__ import annotations

"""Budget entity relation graph (v61.0.43).

Treats the budget as a puzzle of related entities instead of isolated rows.
The graph is intentionally conservative: it never opens PDFs and never replaces
SICRO native contracts.  It only maps already parsed budget items, SINAPI-like
principals, contextual auxiliary/insumo rows and global auxiliaries by the
codigo+banco identity so other stages can reason about how pieces fit together.
"""

from collections import defaultdict
from typing import Any, Dict, Iterable, List, Sequence

VERSION = "v61.0.75-correction-output-contract-and-review-index"


def _clean(value: Any) -> str:
    return " ".join(str(value or "").replace("\u00a0", " ").split())


def _bank(value: Any) -> str:
    text = _clean(value).upper()
    return "PROPRIO" if text == "PRÓPRIO" else text


def code_bank_key(codigo: Any, banco: Any) -> str:
    code = _clean(codigo)
    bank = _bank(banco)
    return f"{code}|{bank}" if code else ""


def _first(row: Dict[str, Any], names: Sequence[str]) -> Any:
    for n in names:
        if isinstance(row, dict) and row.get(n) not in (None, ""):
            return row.get(n)
    return ""


def _add_entity(entities: Dict[str, Dict[str, Any]], by_key: Dict[str, List[str]], *, entity_id: str, kind: str, key: str, path: List[Any], data: Dict[str, Any], parent: str = "", family: str = "") -> None:
    if not key:
        return
    entity = {
        "entity_id": entity_id,
        "kind": kind,
        "family": family,
        "key": key,
        "codigo": _clean(_first(data, ["codigo"])),
        "banco": _clean(_first(data, ["banco", "fonte"])),
        "item": _clean(data.get("item") or ""),
        "path": list(path),
        "parent": parent,
        "fields": {
            "descricao": _clean(_first(data, ["descricao", "especificacao"])),
            "especificacao": _clean(_first(data, ["especificacao", "descricao"])),
            "und": _clean(data.get("und")),
            "quant": _clean(data.get("quant")),
            "valor_unit": _clean(data.get("valor_unit")),
            "total": _clean(data.get("total")),
            "custo_unitario_com_bdi": _clean(data.get("custo_unitario_com_bdi")),
            "custo_parcial": _clean(data.get("custo_parcial")),
        },
    }
    entities[entity_id] = entity
    by_key[key].append(entity_id)


def build_entity_relation_graph(final_result: Dict[str, Any] | None) -> Dict[str, Any]:
    final_result = final_result if isinstance(final_result, dict) else {}
    entities: Dict[str, Dict[str, Any]] = {}
    by_key: Dict[str, List[str]] = defaultdict(list)
    relations: List[Dict[str, Any]] = []

    def walk_budget(nodes: Any, base: List[Any]) -> None:
        if not isinstance(nodes, list):
            return
        for idx, node in enumerate(nodes):
            if not isinstance(node, dict):
                continue
            path = base + [idx]
            key = code_bank_key(node.get("codigo"), node.get("fonte") or node.get("banco"))
            if key:
                eid = f"budget:{node.get('item') or idx}:{key}"
                _add_entity(entities, by_key, entity_id=eid, kind="budget_item", family="budget", key=key, path=path, data=node)
            walk_budget(node.get("filhos"), path + ["filhos"])

    walk_budget(((final_result.get("orcamento_sintetico") or {}).get("itens_raiz") or []), ["orcamento_sintetico", "itens_raiz"])

    comp = final_result.get("composicoes") if isinstance(final_result.get("composicoes"), dict) else {}
    for family in ("sinapi_like", "sicro"):
        fam = comp.get(family) if isinstance(comp.get(family), dict) else {}
        for collection in ("principais", "auxiliares_globais"):
            blocks = fam.get(collection) if isinstance(fam.get(collection), dict) else {}
            for block_key, block in blocks.items():
                if not isinstance(block, dict):
                    continue
                principal = block.get("principal") if isinstance(block.get("principal"), dict) else {}
                code = principal.get("codigo") or (str(block_key).split("|", 1)[0] if "|" in str(block_key) else "")
                bank = principal.get("banco") or principal.get("fonte") or (str(block_key).split("|", 1)[1] if "|" in str(block_key) else "")
                key = code_bank_key(code, bank)
                principal_eid = ""
                if principal and key:
                    principal_eid = f"{family}:{collection}:{block_key}:principal"
                    pcopy = dict(principal)
                    pcopy.setdefault("item", block.get("item"))
                    _add_entity(entities, by_key, entity_id=principal_eid, kind=f"{family}_{collection}_principal", family=family, key=key, path=["composicoes", family, collection, block_key, "principal"], data=pcopy)
                if family == "sinapi_like":
                    for group in ("composicoes_auxiliares", "insumos", "materiais", "mao_obra", "equipamentos", "auxiliares"):
                        rows = block.get(group) if isinstance(block.get(group), list) else []
                        for ridx, row in enumerate(rows):
                            if not isinstance(row, dict):
                                continue
                            rkey = code_bank_key(row.get("codigo"), row.get("banco") or row.get("fonte"))
                            if not rkey:
                                continue
                            eid = f"{family}:{collection}:{block_key}:{group}:{ridx}"
                            _add_entity(entities, by_key, entity_id=eid, kind=f"contextual_{group}", family=family, key=rkey, path=["composicoes", family, collection, block_key, group, ridx], data=row, parent=principal_eid)
                            if principal_eid:
                                relations.append({"type": "inside_principal", "from": eid, "to": principal_eid, "field_policy": {"copy_allowed": ["descricao", "und", "valor_unit"], "copy_forbidden": ["quant", "total"]}})

    # Same codigo+banco relations across known entity types.
    for key, ids in by_key.items():
        kinds = {entities[i]["kind"] for i in ids if i in entities}
        budgets = [i for i in ids if entities.get(i, {}).get("kind") == "budget_item"]
        principals = [i for i in ids if "principais_principal" in entities.get(i, {}).get("kind", "")]
        globals_ = [i for i in ids if "auxiliares_globais_principal" in entities.get(i, {}).get("kind", "")]
        contextual = [i for i in ids if entities.get(i, {}).get("kind", "").startswith("contextual_")]
        for b in budgets:
            for p in principals:
                relations.append({"type": "budget_main_composition", "from": b, "to": p, "key": key, "field_policy": {"copy_allowed": ["descricao", "especificacao", "und", "valor_unit", "custo_unitario_com_bdi"], "copy_forbidden": ["quant", "total", "custo_parcial"]}})
        for c in contextual:
            for g in globals_:
                relations.append({"type": "contextual_auxiliary_global", "from": c, "to": g, "key": key, "field_policy": {"copy_allowed": ["descricao", "und", "valor_unit"], "copy_forbidden": ["quant", "total"]}})
        if len(ids) > 1:
            relations.append({"type": "same_code_bank_cluster", "key": key, "entities": ids[:30], "kinds": sorted(kinds)})

    return {
        "version": VERSION,
        "mode": "budget_puzzle_entity_relation_graph",
        "entity_count": len(entities),
        "relation_count": len(relations),
        "key_count": len(by_key),
        "entities": entities,
        "by_key": {k: v[:40] for k, v in by_key.items()},
        "relations": relations[:1000],
    }


def compact_entity_relation_graph(graph: Dict[str, Any], *, max_entities: int = 40, max_relations: int = 80) -> Dict[str, Any]:
    if not isinstance(graph, dict):
        return {"version": VERSION, "entity_count": 0, "relation_count": 0}
    entities = graph.get("entities") if isinstance(graph.get("entities"), dict) else {}
    return {
        "version": VERSION,
        "mode": graph.get("mode"),
        "entity_count": graph.get("entity_count", 0),
        "relation_count": graph.get("relation_count", 0),
        "key_count": graph.get("key_count", 0),
        "sample_entities": dict(list(entities.items())[:max_entities]),
        "sample_relations": list(graph.get("relations") or [])[:max_relations],
    }
