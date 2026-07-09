from __future__ import annotations

"""Relation contracts over already extracted rows (v61.0.40).

The cross resolver uses these contracts so same code+bank is not treated as a
single global truth.  Each relationship has explicit fields that may be copied
and fields that must never be copied.
"""

from typing import Any, Dict, Iterable, List, Tuple

VERSION = "v61.0.75-correction-output-contract-and-review-index"

RELATION_CONTRACTS: Dict[str, Dict[str, List[str]]] = {
    "budget_to_main_composition": {
        "allowed": ["descricao", "especificacao", "und", "valor_unit", "custo_unitario_com_bdi", "banco", "fonte", "codigo"],
        "forbidden": ["quant", "custo_parcial", "total"],
    },
    "main_composition_to_budget": {
        "allowed": ["descricao", "especificacao", "und", "valor_unit", "custo_unitario_com_bdi", "banco", "fonte", "codigo"],
        "forbidden": ["quant", "custo_parcial", "total"],
    },
    "global_auxiliary_to_contextual_auxiliary": {
        "allowed": ["descricao", "und", "valor_unit", "banco", "codigo"],
        "forbidden": ["quant", "total"],
    },
    "contextual_auxiliary_to_global_auxiliary": {
        "allowed": ["descricao", "und", "valor_unit", "banco", "codigo"],
        "forbidden": ["quant", "total"],
    },
    "same_collection_counterpart": {
        "allowed": ["descricao", "especificacao", "und", "valor_unit", "custo_unitario_sem_bdi", "custo_unitario_com_bdi", "custo_parcial", "custo_total", "total", "banco", "fonte", "codigo"],
        "forbidden": ["quant"],
    },
}


def relation_name(target_family: str, target_group: str, source_family: str, source_group: str, source_collection: str = "") -> str:
    tf, tg, sf, sg, sc = [str(x or "") for x in (target_family, target_group, source_family, source_group, source_collection)]
    if tf == "sinapi_like" and tg == "principal" and sf == "budget":
        return "budget_to_main_composition"
    if tf == "budget" and sf == "sinapi_like" and sg == "principal":
        return "main_composition_to_budget"
    if tg in {"composicoes_auxiliares", "insumos"} and sc == "auxiliares_globais":
        return "global_auxiliary_to_contextual_auxiliary"
    if tg == "principal" and sc == "principais":
        return "same_collection_counterpart"
    return "same_collection_counterpart"


def relation_allows_field(relation: str, field: str) -> bool:
    contract = RELATION_CONTRACTS.get(relation) or RELATION_CONTRACTS["same_collection_counterpart"]
    f = str(field or "")
    if f in contract.get("forbidden", []):
        return False
    return f in contract.get("allowed", [])


def relation_contract_report() -> Dict[str, Any]:
    return {"version": VERSION, "contracts": RELATION_CONTRACTS}
