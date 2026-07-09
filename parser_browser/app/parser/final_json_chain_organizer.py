from __future__ import annotations

"""Final JSON organization for chain-aware budget analysis (v61.0.44)."""

from typing import Any, Dict

VERSION = "v61.0.75-correction-output-contract-and-review-index"


def organize_chain_analysis(final_result: Dict[str, Any], puzzle_context: Dict[str, Any] | None) -> Dict[str, Any]:
    """Attach compact chain-aware analysis without disturbing legacy fields."""
    if not isinstance(final_result, dict):
        return final_result
    ctx = puzzle_context if isinstance(puzzle_context, dict) else {}
    analysis = final_result.setdefault("analise_orcamentaria", {})
    if not isinstance(analysis, dict):
        final_result["analise_orcamentaria"] = analysis = {}
    analysis["version"] = VERSION
    analysis["budget_reconstruction"] = {
        "summary": ((ctx.get("budget_reconstruction_graph") or {}).get("summary") or {}),
        "composition_cost_reconciliation": ((ctx.get("composition_cost_reconciliation") or {}).get("summary") or {}),
        "budget_hierarchy_reconciliation": ((ctx.get("budget_hierarchy_reconciliation") or {}).get("summary") or {}),
        "entity_chain_conflicts": ((ctx.get("entity_chain_conflict_resolver") or {}).get("summary") or {}),
        "principle": "orcamento_composicoes_auxiliares_e_insumos_como_quebra_cabecas_de_entidades_relacionadas",
    }
    return final_result
