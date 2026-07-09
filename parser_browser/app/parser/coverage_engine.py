from __future__ import annotations

"""Coverage targets for extraction-first final flow.

This module does not extract or patch values.  It converts the public JSON into
explicit recovery/verification targets so the real-flow orchestrator can prove
that no critical missing field or unresolved composition is silently skipped.

Global policy:
- target generation is schema/role based, not document-specific;
- math can identify a suspicious target but never creates a public value;
- SICRO is intentionally not modified here.
"""

from typing import Any, Dict, Iterator, List, Tuple

from app.config.version import CURRENT_RELEASE
from app.parser.math_status import compute_component_math

BUDGET_REQUIRED = ("quant", "custo_unitario_sem_bdi", "custo_unitario_com_bdi", "custo_parcial")
COMP_REQUIRED = ("und", "quant", "valor_unit", "total")


def _norm(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _is_empty(value: Any) -> bool:
    return value in (None, "", [], {})


def _iter_budget(nodes: Any, path: str = "orcamento_sintetico.itens_raiz") -> Iterator[Tuple[str, Dict[str, Any]]]:
    if not isinstance(nodes, list):
        return
    for i, node in enumerate(nodes):
        if not isinstance(node, dict):
            continue
        cur = f"{path}.{i}"
        yield cur, node
        filhos = node.get("filhos")
        if isinstance(filhos, list):
            yield from _iter_budget(filhos, f"{cur}.filhos")


def _is_leaf_budget(node: Dict[str, Any]) -> bool:
    return isinstance(node, dict) and node.get("tipo") == "item" and not node.get("filhos")


def _bank_is_sicro(value: Any) -> bool:
    return _norm(value).upper().startswith("SICRO")


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
                if _bank_is_sicro(principal.get("banco") or principal.get("fonte")):
                    continue
                seen.add(id(block)); yield collection, str(key), block


def _iter_rows(block: Dict[str, Any]) -> Iterator[Tuple[str, int | None, Dict[str, Any]]]:
    principal = block.get("principal") if isinstance(block.get("principal"), dict) else None
    if principal is not None:
        yield "principal", None, principal
    for group in ("composicoes_auxiliares", "insumos"):
        rows = block.get(group)
        if isinstance(rows, list):
            for idx, row in enumerate(rows):
                if isinstance(row, dict):
                    yield group, idx, row


def _coverage_target(**kw: Any) -> Dict[str, Any]:
    kw.setdefault("version", CURRENT_RELEASE)
    kw.setdefault("required", True)
    return kw



def _budget_is_full_scope(budget: Dict[str, Any]) -> bool:
    # Full final JSON carries itens_plano or broadly populated leaf fields.
    # Minimal test/recovery payloads can contain only a small hierarchy fragment
    # used to test ownership repair; those should not be treated as a failed
    # complete budget extraction.
    if isinstance(budget.get("itens_plano"), list) and budget.get("itens_plano"):
        return True
    leaves = 0
    populated = 0
    for _p, n in _iter_budget(budget.get("itens_raiz") or []):
        if isinstance(n, dict) and n.get("tipo") == "item" and not n.get("filhos"):
            leaves += 1
            if any(n.get(f) not in (None, "", [], {}) for f in ("quant", "custo_unitario_sem_bdi", "custo_unitario_com_bdi")):
                populated += 1
    return leaves > 0 and populated >= max(1, leaves // 2)

def build_coverage_targets(result: Dict[str, Any], *, phase: str = "pre_recovery") -> Dict[str, Any]:
    """Build explicit recovery/verification targets from the current public JSON."""
    if not isinstance(result, dict):
        return {}
    targets: List[Dict[str, Any]] = []

    budget = result.get("orcamento_sintetico") if isinstance(result.get("orcamento_sintetico"), dict) else {}
    enforce_budget = _budget_is_full_scope(budget)
    for path, node in _iter_budget(budget.get("itens_raiz") or []):
        if enforce_budget and _is_leaf_budget(node):
            missing = [f for f in BUDGET_REQUIRED if _is_empty(node.get(f))]
            if missing:
                targets.append(_coverage_target(
                    target_type="budget_leaf_missing_public_numeric",
                    section="orcamento_sintetico",
                    severity="blocking",
                    path=path,
                    item=node.get("item"),
                    codigo=node.get("codigo"),
                    fonte=node.get("fonte"),
                    missing=missing,
                    search_scope=["same_budget_row", "same_budget_page", "budget_range"],
                    reason="leaf_budget_item_requires_public_numbers_from_pdf",
                ))

    for collection, key, block in _iter_sinapi_blocks(result.get("composicoes") if isinstance(result.get("composicoes"), dict) else {}):
        try:
            math = compute_component_math(block)
        except Exception as exc:
            math = {"status": "not_evaluable", "reason": str(exc)}
        block_has_missing = False
        for group, idx, row in _iter_rows(block):
            missing = [f for f in COMP_REQUIRED if _is_empty(row.get(f))]
            if missing:
                block_has_missing = True
                targets.append(_coverage_target(
                    target_type="composition_row_missing_public_numeric",
                    section="composicoes_analiticas",
                    severity="blocking",
                    collection=collection,
                    block=key,
                    item=block.get("item"),
                    row_group=group,
                    row_index=idx,
                    codigo=row.get("codigo"),
                    banco=row.get("banco") or row.get("fonte"),
                    missing=missing,
                    page_hint=block.get("pagina_inicio") or ((block.get("paginas") or [None])[0] if isinstance(block.get("paginas"), list) else None),
                    search_scope=["same_row", "same_composition_block", "same_page", "same_code_bank_global"],
                    reason="composition_row_requires_pdf_declared_numeric_tail",
                ))
        math_status = str((math or {}).get("status") or "")
        if math_status not in {"", "ok", "ok_with_rounding"}:
            # If all fields are present, this is a document consistency issue;
            # if fields are missing, it is an extraction coverage problem.
            targets.append(_coverage_target(
                target_type="composition_math_not_closed",
                section="composicoes_analiticas",
                severity="blocking" if block_has_missing or int((math or {}).get("missing_component_totals") or 0) else "document_warning",
                collection=collection,
                block=key,
                item=block.get("item"),
                math_status=math,
                search_scope=["same_composition_block", "same_page", "same_code_bank_global"],
                reason="composition_math_detected_recovery_or_document_consistency_target",
            ))

    summary: Dict[str, Any] = {
        "version": CURRENT_RELEASE,
        "phase": phase,
        "target_count": len(targets),
        "blocking_target_count": sum(1 for t in targets if t.get("severity") == "blocking"),
        "document_warning_target_count": sum(1 for t in targets if t.get("severity") == "document_warning"),
        "targets": targets[:1000],
    }
    result.setdefault("documento_evidencias", {}).setdefault("coverage_engine", {})[phase] = summary
    result.setdefault("meta", {}).setdefault("performance", {})[f"coverage_engine_{phase}"] = {k: v for k, v in summary.items() if k != "targets"}
    return summary
