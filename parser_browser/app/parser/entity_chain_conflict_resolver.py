from __future__ import annotations

"""Entity-chain conflict resolver (v61.0.44).

Looks across reconstructed chains to surface disagreements between budget items,
main compositions and physical/contextual evidence. It does not blindly patch;
it provides chain-level diagnostics for closure and the correction document.
"""

from typing import Any, Dict, List

from app.parser.numeric_constraint_solver import parse_ptbr_number

VERSION = "v61.0.75-correction-output-contract-and-review-index"


def _clean(value: Any) -> str:
    return " ".join(str(value or "").replace("\u00a0", " ").split())


def _norm_text(value: Any) -> str:
    return _clean(value).upper().replace("PRÓPRIO", "PROPRIO")


def _fields(obj: Dict[str, Any]) -> Dict[str, Any]:
    return obj.get("fields") if isinstance(obj.get("fields"), dict) else {}


def _similar_price(a: Any, b: Any, tolerance: float = 0.12) -> bool | None:
    na = parse_ptbr_number(a)
    nb = parse_ptbr_number(b)
    if na is None or nb is None:
        return None
    return abs(na - nb) <= tolerance


def build_entity_chain_conflict_report(reconstruction_graph: Dict[str, Any] | None) -> Dict[str, Any]:
    reconstruction_graph = reconstruction_graph if isinstance(reconstruction_graph, dict) else {}
    conflicts: List[Dict[str, Any]] = []
    confirmations: List[Dict[str, Any]] = []
    for chain in reconstruction_graph.get("chains") or []:
        if not isinstance(chain, dict):
            continue
        key = chain.get("key")
        budget_fields = _fields(chain.get("budget_item") or {})
        comp_fields = _fields(chain.get("main_composition") or {})
        # Description conflicts are softer because budget and composition may use abbreviated text.
        b_desc = _norm_text(budget_fields.get("descricao") or budget_fields.get("especificacao"))
        c_desc = _norm_text(comp_fields.get("descricao") or comp_fields.get("especificacao"))
        if b_desc and c_desc:
            if b_desc == c_desc or b_desc in c_desc or c_desc in b_desc:
                confirmations.append({"key": key, "field": "descricao", "status": "compatible_budget_composition_description"})
            else:
                conflicts.append({"key": key, "field": "descricao", "severity": "warning", "budget_value": budget_fields.get("descricao") or budget_fields.get("especificacao"), "composition_value": comp_fields.get("descricao") or comp_fields.get("especificacao"), "reason": "budget_composition_description_divergence"})
        b_und = _norm_text(budget_fields.get("und"))
        c_und = _norm_text(comp_fields.get("und"))
        if b_und and c_und:
            if b_und == c_und:
                confirmations.append({"key": key, "field": "und", "status": "compatible_budget_composition_unit"})
            else:
                conflicts.append({"key": key, "field": "und", "severity": "strong", "budget_value": budget_fields.get("und"), "composition_value": comp_fields.get("und"), "reason": "budget_composition_unit_conflict"})
        price_ok = _similar_price(budget_fields.get("custo_unitario_com_bdi"), comp_fields.get("valor_unit"))
        if price_ok is True:
            confirmations.append({"key": key, "field": "unit_price", "status": "budget_price_compatible_with_composition_value"})
        elif price_ok is False:
            conflicts.append({"key": key, "field": "unit_price", "severity": "warning", "budget_value": budget_fields.get("custo_unitario_com_bdi"), "composition_value": comp_fields.get("valor_unit"), "reason": "budget_price_differs_from_composition_value_possible_bdi_or_rounding"})
        if chain.get("missing_global_auxiliary_count"):
            conflicts.append({"key": key, "field": "auxiliary_chain", "severity": "info", "missing_global_auxiliary_count": chain.get("missing_global_auxiliary_count"), "reason": "contextual_auxiliary_without_global_expansion_non_fatal"})
    summary = {
        "conflicts": len(conflicts),
        "strong_conflicts": sum(1 for c in conflicts if c.get("severity") == "strong"),
        "warnings": sum(1 for c in conflicts if c.get("severity") == "warning"),
        "info": sum(1 for c in conflicts if c.get("severity") == "info"),
        "confirmations": len(confirmations),
    }
    return {"version": VERSION, "mode": "entity_chain_conflict_resolver", "summary": summary, "conflicts": conflicts[:500], "confirmations": confirmations[:500]}
