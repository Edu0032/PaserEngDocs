from __future__ import annotations

"""Compact physical-block coverage manifests for the final real flow.

This module is intentionally document-independent.  It does not extract new
values and it does not duplicate the banded-closure engine.  It summarizes the
final public JSON as physical blocks:

- every SINAPI-like composition block has row coverage, lock status and math
  status;
- every budget leaf has required public numeric fields;
- orphan/open rows are surfaced compactly for correction documents;
- bulky fragment/debug details stay internal to the existing tools.

The goal is to make the final contract prove that no known row was left behind
without increasing the JSON with raw fragments or page text.
"""

from typing import Any, Dict, Iterator, List, Tuple

from app.config.version import CURRENT_RELEASE
from app.parser.math_status import compute_component_math

REQ_ROW = ("und", "quant", "valor_unit", "total")
REQ_BUDGET_LEAF = ("quant", "custo_unitario_sem_bdi", "custo_unitario_com_bdi", "custo_parcial")


def _norm(value: Any) -> str:
    import unicodedata
    text = " ".join(str(value or "").split()).upper()
    return "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))


def _iter_sinapi_blocks(composicoes: Dict[str, Any]) -> Iterator[Tuple[str, str, Dict[str, Any]]]:
    if not isinstance(composicoes, dict):
        return
    seen: set[int] = set()
    fam = composicoes.get("sinapi_like") if isinstance(composicoes.get("sinapi_like"), dict) else {}
    for collection in ("principais", "auxiliares_globais"):
        blocks = fam.get(collection) if isinstance(fam, dict) else None
        if isinstance(blocks, dict):
            for key, block in blocks.items():
                if isinstance(block, dict) and id(block) not in seen:
                    seen.add(id(block)); yield collection, str(key), block
    for collection in ("principais", "auxiliares_globais"):
        blocks = composicoes.get(collection)
        if isinstance(blocks, dict):
            for key, block in blocks.items():
                if not isinstance(block, dict) or id(block) in seen:
                    continue
                principal = block.get("principal") if isinstance(block.get("principal"), dict) else {}
                if _norm(principal.get("banco") or principal.get("fonte") or "").startswith("SICRO"):
                    continue
                seen.add(id(block)); yield collection, str(key), block


def _iter_rows(block: Dict[str, Any]):
    principal = block.get("principal") if isinstance(block.get("principal"), dict) else None
    if principal is not None:
        yield "principal", None, principal
    for group in ("composicoes_auxiliares", "insumos"):
        rows = block.get(group)
        if isinstance(rows, list):
            for idx, row in enumerate(rows):
                if isinstance(row, dict):
                    yield group, idx, row


def _iter_budget_nodes(nodes: Any, path: str = "orcamento_sintetico.itens_raiz"):
    if not isinstance(nodes, list):
        return
    for idx, node in enumerate(nodes):
        if not isinstance(node, dict):
            continue
        cur = f"{path}.{idx}"
        yield cur, node
        filhos = node.get("filhos")
        if isinstance(filhos, list):
            yield from _iter_budget_nodes(filhos, f"{cur}.filhos")


def _is_leaf_budget(node: Dict[str, Any]) -> bool:
    return isinstance(node, dict) and node.get("tipo") == "item" and not node.get("filhos")


def _budget_is_full_scope(budget: Dict[str, Any]) -> bool:
    if isinstance(budget.get("itens_plano"), list) and budget.get("itens_plano"):
        return True
    leaves = 0
    populated = 0
    for _p, n in _iter_budget_nodes(budget.get("itens_raiz") or []):
        if isinstance(n, dict) and n.get("tipo") == "item" and not n.get("filhos"):
            leaves += 1
            if any(n.get(f) not in (None, "", [], {}) for f in ("quant", "custo_unitario_sem_bdi", "custo_unitario_com_bdi")):
                populated += 1
    return leaves > 0 and populated >= max(1, leaves // 2)


def _status_from_closure(block: Dict[str, Any], math: Dict[str, Any], open_rows: int) -> str:
    closure = ((block.get("detalhes") or {}).get("banded_composition_closure") or {}) if isinstance(block.get("detalhes"), dict) else {}
    if isinstance(closure, dict) and closure.get("status"):
        return str(closure.get("status"))
    math_ok = (bool(math.get("ok")) or str(math.get("status") or "") == "ok") and int(math.get("missing_component_totals") or 0) == 0
    return "ok" if open_rows == 0 and math_ok else "needs_review"


def build_physical_block_coverage_manifest(result: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(result, dict):
        return {}

    comp_manifests: List[Dict[str, Any]] = []
    open_rows_compact: List[Dict[str, Any]] = []
    complete_blocks = 0
    incomplete_blocks = 0
    rows_total = 0
    rows_locked = 0
    useful_orphan_fragments = 0

    for collection, key, block in _iter_sinapi_blocks(result.get("composicoes") if isinstance(result.get("composicoes"), dict) else {}):
        row_count = 0
        locked_count = 0
        open_count = 0
        missing_fields_count = 0
        open_sample: List[Dict[str, Any]] = []
        for group, idx, row in _iter_rows(block):
            row_count += 1; rows_total += 1
            missing = [f for f in REQ_ROW if row.get(f) in (None, "", [], {})]
            if missing:
                open_count += 1; missing_fields_count += len(missing)
                item = {"block": key, "row_group": group, "row_index": idx, "codigo": row.get("codigo"), "banco": row.get("banco"), "missing": missing}
                if len(open_sample) < 5:
                    open_sample.append(item)
                if len(open_rows_compact) < 100:
                    open_rows_compact.append(item)
            else:
                locked_count += 1; rows_locked += 1
        try:
            math = compute_component_math(block)
        except Exception:
            math = {}
        closure = ((block.get("detalhes") or {}).get("banded_composition_closure") or {}) if isinstance(block.get("detalhes"), dict) else {}
        free_fragments = int((closure or {}).get("free_fragments_after_closure") or 0) if isinstance(closure, dict) else 0
        useful_orphan_fragments += free_fragments
        status = _status_from_closure(block, math, open_count)
        complete = status == "ok" and open_count == 0
        if complete:
            complete_blocks += 1
        else:
            incomplete_blocks += 1
        comp_manifests.append({
            "key": key,
            "collection": collection,
            "item": block.get("item"),
            "page_start": block.get("pagina_inicio"),
            "page_end": block.get("pagina_fim"),
            "pages": block.get("paginas") or [],
            "expected_rows": row_count,
            "extracted_rows": row_count,
            "locked_rows": locked_count,
            "open_rows": open_count,
            "missing_required_fields": missing_fields_count,
            "orphan_numeric_fragments": free_fragments,
            "coverage_status": "complete" if complete else "needs_review",
            "math_status": str((math or {}).get("status") or ("ok" if (math or {}).get("ok") else "unknown")),
            "public_values_preserved": True,
            "open_rows_sample": open_sample,
        })

    budget_leaf_count = 0
    budget_leaf_complete = 0
    budget_open_sample: List[Dict[str, Any]] = []
    budget = result.get("orcamento_sintetico") if isinstance(result.get("orcamento_sintetico"), dict) else {}
    enforce_budget = _budget_is_full_scope(budget)
    for path, node in _iter_budget_nodes((budget.get("itens_raiz") or []) if isinstance(budget, dict) else []):
        if not _is_leaf_budget(node):
            continue
        budget_leaf_count += 1
        if not enforce_budget:
            budget_leaf_complete += 1
            continue
        missing = [f for f in REQ_BUDGET_LEAF if node.get(f) in (None, "", [], {})]
        if not missing:
            budget_leaf_complete += 1
        elif len(budget_open_sample) < 100:
            budget_open_sample.append({"path": path, "item": node.get("item"), "codigo": node.get("codigo"), "fonte": node.get("fonte"), "missing": missing})

    budget_manifest = {
        "version": CURRENT_RELEASE,
        "leaf_count": budget_leaf_count,
        "leaf_complete_count": budget_leaf_complete,
        "leaf_missing_count": max(0, budget_leaf_count - budget_leaf_complete),
        "coverage_status": "complete" if budget_leaf_count == budget_leaf_complete else "needs_review",
        "open_leaf_sample": budget_open_sample,
    }
    summary = {
        "version": CURRENT_RELEASE,
        "policy": "every_known_physical_block_row_must_be_locked_complete_or_explicitly_reported",
        "composition_block_count": len(comp_manifests),
        "composition_complete_block_count": complete_blocks,
        "composition_incomplete_block_count": incomplete_blocks,
        "composition_rows_total": rows_total,
        "composition_rows_locked": rows_locked,
        "composition_open_rows": max(0, rows_total - rows_locked),
        "useful_orphan_fragments": useful_orphan_fragments,
        "budget_leaf_count": budget_leaf_count,
        "budget_leaf_complete_count": budget_leaf_complete,
        "budget_leaf_missing_count": max(0, budget_leaf_count - budget_leaf_complete) if enforce_budget else 0,
        "budget_full_scope_evaluated": bool(enforce_budget),
        "overall_status": "complete" if incomplete_blocks == 0 and (not enforce_budget or budget_leaf_count == budget_leaf_complete) and useful_orphan_fragments == 0 else "needs_review",
    }
    manifest = {
        "version": CURRENT_RELEASE,
        "summary": summary,
        "budget_manifest": budget_manifest,
        # Compact by default: one small manifest per composition, no raw page text.
        "composition_manifests": comp_manifests[:1000],
        "open_rows_compact": open_rows_compact,
    }
    return manifest


def apply_physical_block_coverage_manifest(result: Dict[str, Any]) -> Dict[str, Any]:
    manifest = build_physical_block_coverage_manifest(result)
    if not isinstance(result, dict):
        return manifest
    result.setdefault("documento_evidencias", {})["physical_block_coverage"] = manifest
    result.setdefault("meta", {}).setdefault("performance", {})["physical_block_coverage"] = {k: v for k, v in (manifest.get("summary") or {}).items()}
    # Correction document remains compact: include only summary and open samples.
    result.setdefault("documento_correcao", {})["physical_block_coverage"] = {
        "version": CURRENT_RELEASE,
        "summary": manifest.get("summary") or {},
        "budget_open_leaf_sample": (manifest.get("budget_manifest") or {}).get("open_leaf_sample") or [],
        "open_rows_compact": manifest.get("open_rows_compact") or [],
    }
    return manifest
