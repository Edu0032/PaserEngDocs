from __future__ import annotations

"""Composition cost reconciliation (v61.0.44).

For SINAPI-like compositions, checks whether the sum of contextual component
line totals explains the main composition unit cost. SICRO remains governed by
sicro_only and is not recalculated here.
"""

from typing import Any, Dict, List, Tuple

from app.parser.numeric_constraint_solver import parse_ptbr_number

VERSION = "v61.0.75-correction-output-contract-and-review-index"
COMPONENT_GROUPS = ("composicoes_auxiliares", "insumos", "materiais", "mao_obra", "equipamentos", "auxiliares")


def _clean(value: Any) -> str:
    return " ".join(str(value or "").replace("\u00a0", " ").split())


def _sum_component_totals(block: Dict[str, Any]) -> Tuple[float, List[Dict[str, Any]], List[Dict[str, Any]]]:
    total = 0.0
    used: List[Dict[str, Any]] = []
    missing: List[Dict[str, Any]] = []
    seen_ids = set()
    for group in COMPONENT_GROUPS:
        rows = block.get(group) if isinstance(block.get(group), list) else []
        for idx, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            rid = id(row)
            if rid in seen_ids:
                continue
            seen_ids.add(rid)
            raw_total = row.get("total")
            n = parse_ptbr_number(raw_total)
            rec = {"group": group, "index": idx, "codigo": row.get("codigo"), "banco": row.get("banco") or row.get("fonte"), "total": raw_total}
            if n is None:
                missing.append({**rec, "reason": "missing_or_invalid_component_total"})
            else:
                total += n
                used.append({**rec, "numeric_total": round(n, 6)})
    return total, used, missing


def build_composition_cost_reconciliation(final_result: Dict[str, Any] | None, *, tolerance: float = 0.08) -> Dict[str, Any]:
    final_result = final_result if isinstance(final_result, dict) else {}
    comp = final_result.get("composicoes") if isinstance(final_result.get("composicoes"), dict) else {}
    sinapi = comp.get("sinapi_like") if isinstance(comp.get("sinapi_like"), dict) else {}
    rows: List[Dict[str, Any]] = []
    for collection in ("principais", "auxiliares_globais"):
        blocks = sinapi.get(collection) if isinstance(sinapi.get(collection), dict) else {}
        for block_key, block in blocks.items():
            if not isinstance(block, dict):
                continue
            principal = block.get("principal") if isinstance(block.get("principal"), dict) else {}
            expected_raw = principal.get("valor_unit") or principal.get("total")
            expected = parse_ptbr_number(expected_raw)
            component_sum, used, missing = _sum_component_totals(block)
            if not used and not missing:
                status = "not_applicable_no_components"
                ok = True
                delta = None
            elif expected is None:
                status = "insufficient_principal_value"
                ok = False
                delta = None
            else:
                delta = round(component_sum - expected, 6)
                ok = abs(delta) <= tolerance
                status = "ok" if ok else "mismatch"
            rows.append({
                "block_key": str(block_key),
                "collection": collection,
                "codigo": principal.get("codigo") or str(block_key).split("|", 1)[0],
                "banco": principal.get("banco") or (str(block_key).split("|", 1)[1] if "|" in str(block_key) else ""),
                "principal_value": expected_raw,
                "principal_numeric_value": expected,
                "component_total_sum": round(component_sum, 6),
                "delta": delta,
                "tolerance": tolerance,
                "ok": ok,
                "status": status,
                "used_component_count": len(used),
                "missing_component_total_count": len(missing),
                "used_components": used[:80],
                "missing_components": missing[:80],
            })
    summary = {
        "checked": len(rows),
        "ok": sum(1 for r in rows if r.get("ok") is True),
        "mismatch": sum(1 for r in rows if r.get("status") == "mismatch"),
        "insufficient": sum(1 for r in rows if str(r.get("status") or "").startswith("insufficient")),
        "not_applicable": sum(1 for r in rows if r.get("status") == "not_applicable_no_components"),
    }
    return {"version": VERSION, "mode": "sinapi_like_composition_cost_reconciliation", "summary": summary, "rows": rows[:1000]}
