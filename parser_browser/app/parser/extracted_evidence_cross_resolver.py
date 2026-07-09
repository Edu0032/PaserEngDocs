from __future__ import annotations

"""Mandatory cross-resolver over already extracted evidence (v61.0.39).

This module is deliberately lightweight: it never opens the PDF and never scans
pages.  It only cross-checks budget rows, composition principals, contextual
auxiliaries and auxiliary-global definitions already present in the parsed JSON / 
ledger.  The heavy fallback that scans physical PDF occurrences is a separate
module.
"""

from typing import Any, Dict, Iterable, List

from app.parser.field_patch_validators import validate_patch_candidate

VERSION = "v61.0.75-correction-output-contract-and-review-index"

DESCRIPTION_FIELDS = {"descricao", "especificacao"}


def _row_key(row: Any) -> str:
    key = getattr(row, "key", "")
    return str(key or "").strip()


def _row_value(row: Any, field: str) -> Any:
    data = getattr(row, "row", {}) or {}
    return data.get(field) if isinstance(data, dict) else None


def _empty(v: Any) -> bool:
    return v in (None, "")


def _best_value(ledger: Any, key: str, field: str, min_confidence: float = 0.72) -> Dict[str, Any] | None:
    try:
        ev = ledger.best(key, field, min_confidence=min_confidence)
    except Exception:
        ev = None
    if not ev or not getattr(ev, "value", None):
        return None
    return {
        "value": ev.value,
        "source": getattr(ev, "source", "field_evidence_ledger"),
        "source_path": list(getattr(ev, "path", []) or []),
        "confidence": float(getattr(ev, "confidence", 0.0) or 0.0),
    }


def build_extracted_cross_candidates(rows: Iterable[Any], ledger: Any, *, context: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
    """Return safe patch candidates from already extracted rows/evidence.

    Quantity is intentionally never copied across budget/composition/global-aux
    boundaries because the same code/bank has contextual quantities in each
    relation.
    """
    candidates: List[Dict[str, Any]] = []
    context = context if isinstance(context, dict) else {}
    for row in list(rows or []):
        family = str(getattr(row, "family", "") or "")
        group = str(getattr(row, "group", "") or "")
        if family == "sicro" and group == "section_row":
            continue
        key = _row_key(row)
        if not key:
            continue
        row_data = getattr(row, "row", {}) or {}
        if not isinstance(row_data, dict):
            continue
        desc_field = str(getattr(row, "field_name", "descricao") or "descricao")
        field_plan: List[tuple[str, List[str], float, str]] = []
        field_plan.append((desc_field, ["descricao", "especificacao"], 0.50, "same_codigo_banco_description"))
        field_plan.append(("und", ["und"], 0.72, "same_codigo_banco_unit"))
        if family == "budget":
            field_plan.append(("custo_unitario_com_bdi", ["valor_unit", "total", "custo_unitario_com_bdi"], 0.72, "budget_main_composition_unit_cost"))
        elif family == "sinapi_like":
            if group in {"principal", "composicoes_auxiliares", "insumos"}:
                field_plan.append(("valor_unit", ["valor_unit", "custo_unitario_com_bdi", "total"], 0.72, "composition_budget_or_global_unit_value"))
            # v61.0.40: never derive/copy public total from unit value through the
            # light cross resolver. Math may record an expectation, but the public
            # total must be found in physical/extracted evidence for that field.
        for target_field, source_fields, min_conf, reason in field_plan:
            current = row_data.get(target_field)
            if target_field in DESCRIPTION_FIELDS:
                # Let the closure engine decide whether a non-empty description is weak;
                # candidates are still useful for replacement by the caller.
                pass
            elif not _empty(current):
                continue
            for source_field in source_fields:
                ev = _best_value(ledger, key, source_field, min_confidence=min_conf)
                if not ev:
                    continue
                validation = validate_patch_candidate(target_field, ev["value"], row_data, context)
                if not validation.get("ok"):
                    continue
                candidates.append({
                    "row_id": getattr(row, "row_id", ""),
                    "path": list(getattr(row, "path", []) or []) + [target_field],
                    "row_path": list(getattr(row, "path", []) or []),
                    "family": family,
                    "group": group,
                    "collection": getattr(row, "collection", ""),
                    "codigo": getattr(row, "codigo", ""),
                    "banco": getattr(row, "banco", ""),
                    "item": getattr(row, "item", ""),
                    "field": target_field,
                    "value": validation.get("normalized", ev["value"]),
                    "source": "extracted_evidence_cross_resolver",
                    "source_field": source_field,
                    "source_row_path": ev.get("source_path") or [],
                    "confidence": round(min(0.99, max(0.0, float(ev.get("confidence") or 0.0) + 0.04)), 3),
                    "reason": reason,
                    "quantity_policy": "never_copy_contextual_quantity",
                })
                break
    return candidates


def build_report(candidates: List[Dict[str, Any]], repairs: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "version": VERSION,
        "mode": "already_extracted_evidence_only",
        "candidate_count": len(candidates or []),
        "applied_count": len(repairs or []),
        "applied": list(repairs or [])[:300],
        "notes": [
            "Does not open or scan the PDF.",
            "Runs before local/global PDF sweeps.",
            "Never copies contextual quantities between budget, composition and auxiliary-global rows.",
        ],
    }
