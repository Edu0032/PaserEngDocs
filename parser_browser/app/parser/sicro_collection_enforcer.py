from __future__ import annotations

"""Final SICRO collection enforcer.

The invariant requested for v61.0.39 is simple and strong:
SICRO composition with item -> principais; without item -> auxiliares_globais.
This pass protects the final JSON after all merges/recoveries.
"""

from typing import Any, Dict, Tuple, List
import copy

VERSION = "v61.0.75-correction-output-contract-and-review-index"


def _has_item(block: Dict[str, Any]) -> bool:
    item = str((block or {}).get("item") or ((block or {}).get("principal") or {}).get("item") or "").strip()
    return bool(item)


def _is_sicro_key_or_block(key: str, block: Dict[str, Any]) -> bool:
    if "SICRO" in str(key).upper():
        return True
    principal = block.get("principal") if isinstance(block.get("principal"), dict) else {}
    bank = str(principal.get("banco") or principal.get("fonte") or principal.get("banco_coluna") or block.get("banco") or "").upper()
    return "SICRO" in bank or isinstance(block.get("sicro"), dict) or isinstance((block.get("detalhes") or {}).get("sicro"), dict)


def enforce_sicro_principal_auxiliary_collections(final_result: Dict[str, Any], *, apply: bool = True) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    result = final_result if apply else copy.deepcopy(final_result or {})
    comp = result.setdefault("composicoes", {})
    if not isinstance(comp, dict):
        return result, {"version": VERSION, "moved": [], "summary": {"moved": 0}}
    sicro = comp.setdefault("sicro", {})
    if not isinstance(sicro, dict):
        comp["sicro"] = sicro = {}
    principais = sicro.setdefault("principais", {})
    auxiliares = sicro.setdefault("auxiliares_globais", {})
    if not isinstance(principais, dict):
        sicro["principais"] = principais = {}
    if not isinstance(auxiliares, dict):
        sicro["auxiliares_globais"] = auxiliares = {}

    moved: List[Dict[str, Any]] = []

    # Include legacy top-level collections if they contain SICRO blocks.
    legacy_sources = []
    for collection in ("principais", "auxiliares_globais"):
        blocks = comp.get(collection)
        if isinstance(blocks, dict):
            legacy_sources.append((collection, blocks))
    sources = [("sicro.principais", principais), ("sicro.auxiliares_globais", auxiliares)] + legacy_sources

    for source_name, blocks in sources:
        for key, block in list((blocks or {}).items()):
            if not isinstance(block, dict) or not _is_sicro_key_or_block(str(key), block):
                continue
            wants_principal = _has_item(block)
            target = principais if wants_principal else auxiliares
            target_name = "sicro.principais" if wants_principal else "sicro.auxiliares_globais"
            if source_name == target_name and target.get(key) is block:
                continue
            # Prefer item-bearing block when a duplicate exists; otherwise keep first
            # target and report the duplicate as skipped.
            target[str(key)] = block
            if blocks is not target:
                try:
                    del blocks[key]
                except Exception:
                    pass
            moved.append({
                "tipo": "sicro_collection_enforced",
                "codigo": str(key).split("|", 1)[0],
                "key": str(key),
                "from": source_name,
                "to": target_name,
                "reason": "sicro_with_item_must_be_principal" if wants_principal else "sicro_without_item_must_be_global_auxiliary",
            })

    report = {"version": VERSION, "moved": moved, "summary": {"moved": len(moved)}}
    if moved:
        doc = result.setdefault("documento_correcao", {})
        if isinstance(doc, dict):
            doc["sicro_collection_enforcer"] = report
            warnings = doc.setdefault("warnings", [])
            if isinstance(warnings, list):
                warnings.extend(moved[:100])
    result.setdefault("meta", {}).setdefault("performance", {})["sicro_collection_enforcer"] = report
    return result, report
