from __future__ import annotations

from typing import Any, Dict, Iterable, List

from app.core.money import parse_ptbr_number
from app.core.schemas import OrcamentoItem, OrcamentoSintetico

VERSION = "v61.0.75-correction-output-contract-and-review-index"


def _walk(nodes: Iterable[OrcamentoItem]):
    for node in nodes or []:
        yield node
        yield from _walk(getattr(node, "filhos", []) or [])


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)):
            return float(value)
        parsed = parse_ptbr_number(str(value))
        return float(parsed) if parsed is not None else None
    except Exception:
        return None


def validate_budget_math(orcamento: OrcamentoSintetico, *, tolerance_abs: float = 0.05, tolerance_rel: float = 0.002) -> Dict[str, Any]:
    """Validate synthetic budget item arithmetic without treating document rounding as parser error.

    This validator is used as a recheck trigger/audit signal: if quantity × unit
    price diverges from the partial cost, the row is marked for targeted review.
    It never mutates the public JSON and never blocks SICRO native processing.
    """
    checks: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    for item in _walk(getattr(orcamento, "itens_raiz", []) or []):
        if str(getattr(item, "tipo", "") or "").lower() != "item":
            continue
        q = _num(getattr(item, "quant", None))
        unit = _num(getattr(item, "custo_unitario_com_bdi", None))
        if unit is None:
            unit = _num(getattr(item, "custo_unitario_sem_bdi", None))
        partial = _num(getattr(item, "custo_parcial", None))
        if q is None or unit is None or partial is None:
            continue
        expected = q * unit
        diff = abs(expected - partial)
        rel = diff / max(abs(partial), abs(expected), 1.0)
        status = "ok" if (diff <= tolerance_abs or rel <= tolerance_rel) else "warning"
        row = {
            "item": getattr(item, "item", ""),
            "codigo": getattr(item, "codigo", ""),
            "fonte": getattr(item, "fonte", ""),
            "quant": getattr(item, "quant", None),
            "unit_price_used": getattr(item, "custo_unitario_com_bdi", None) or getattr(item, "custo_unitario_sem_bdi", None),
            "custo_parcial": getattr(item, "custo_parcial", None),
            "expected": round(expected, 4),
            "difference": round(diff, 4),
            "relative_difference": round(rel, 6),
            "status": status,
            "action": "keep" if status == "ok" else "targeted_recheck_candidate",
        }
        checks.append(row)
        if status != "ok":
            warnings.append(row)
    return {
        "version": VERSION,
        "status": "ok" if not warnings else "warning",
        "checks": checks[:500],
        "warnings": warnings[:200],
        "summary": {"checked": len(checks), "warnings": len(warnings)},
    }
