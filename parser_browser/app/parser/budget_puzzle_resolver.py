from __future__ import annotations

"""Budget Puzzle Resolver (v61.0.44).

Orchestrates entity relations, physical/raw evidence, fragment ownership and
budget reconstruction so line closure treats the document as an interconnected
budget puzzle.  SICRO remains governed by the native sicro_only pipeline; this
module only integrates/audits what is already present.
"""

from typing import Any, Dict, List

from app.parser.entity_relation_graph import build_entity_relation_graph, compact_entity_relation_graph
from app.parser.fragment_ownership_graph import build_fragment_ownership_graph, compact_fragment_ownership_graph
from app.parser.strict_but_realistic_closure import build_strict_realistic_closure_report
from app.parser.budget_reconstruction_graph import build_budget_reconstruction_graph, compact_budget_reconstruction_graph
from app.parser.composition_cost_reconciliation import build_composition_cost_reconciliation
from app.parser.budget_hierarchy_reconciliation import build_budget_hierarchy_reconciliation
from app.parser.entity_chain_conflict_resolver import build_entity_chain_conflict_report

VERSION = "v61.0.75-correction-output-contract-and-review-index"


def build_budget_puzzle_context(final_result: Dict[str, Any] | None, physical_index: Dict[str, Any] | None, row_reports: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
    entity_graph = build_entity_relation_graph(final_result or {})
    reconstruction_graph = build_budget_reconstruction_graph(final_result or {}, entity_graph, physical_index or {})
    ownership_graph = build_fragment_ownership_graph(entity_graph, physical_index or {}, row_reports or [])
    composition_cost = build_composition_cost_reconciliation(final_result or {})
    hierarchy = build_budget_hierarchy_reconciliation(final_result or {})
    chain_conflicts = build_entity_chain_conflict_report(reconstruction_graph)
    strict_report = build_strict_realistic_closure_report(row_reports or [], entity_graph=entity_graph, ownership_graph=ownership_graph)
    return {
        "version": VERSION,
        "mode": "budget_puzzle_budget_reconstruction_context",
        "entity_relation_graph": entity_graph,
        "budget_reconstruction_graph": reconstruction_graph,
        "fragment_ownership_graph": ownership_graph,
        "composition_cost_reconciliation": composition_cost,
        "budget_hierarchy_reconciliation": hierarchy,
        "entity_chain_conflict_resolver": chain_conflicts,
        "strict_but_realistic_closure": strict_report,
        "summary": {
            "entities": entity_graph.get("entity_count", 0),
            "relations": entity_graph.get("relation_count", 0),
            "chains": (reconstruction_graph.get("summary") or {}).get("chains", 0),
            "internal_rows": (reconstruction_graph.get("summary") or {}).get("internal_rows", 0),
            "missing_global_auxiliaries": (reconstruction_graph.get("summary") or {}).get("missing_global_auxiliaries", 0),
            "composition_cost_mismatches": (composition_cost.get("summary") or {}).get("mismatch", 0),
            "budget_hierarchy_mismatches": (hierarchy.get("summary") or {}).get("mismatch", 0),
            "chain_conflicts": (chain_conflicts.get("summary") or {}).get("conflicts", 0),
            "fragments": ownership_graph.get("fragment_count", 0),
            "locked_fragments": ownership_graph.get("locked_count", 0),
            "closed_by_strong_consensus": (strict_report.get("summary") or {}).get("closed_by_strong_consensus", 0),
        },
    }


def compact_budget_puzzle_context(context: Dict[str, Any]) -> Dict[str, Any]:
    context = context if isinstance(context, dict) else {}
    strict = context.get("strict_but_realistic_closure") if isinstance(context.get("strict_but_realistic_closure"), dict) else {}
    return {
        "version": VERSION,
        "mode": context.get("mode") or "budget_puzzle_budget_reconstruction_context",
        "summary": context.get("summary", {}),
        "entity_relation_graph": compact_entity_relation_graph(context.get("entity_relation_graph") or {}),
        "budget_reconstruction_graph": compact_budget_reconstruction_graph(context.get("budget_reconstruction_graph") or {}),
        "fragment_ownership_graph": compact_fragment_ownership_graph(context.get("fragment_ownership_graph") or {}),
        "composition_cost_reconciliation": {
            "version": VERSION,
            "summary": ((context.get("composition_cost_reconciliation") or {}).get("summary") or {}),
            "sample_rows": ((context.get("composition_cost_reconciliation") or {}).get("rows") or [])[:80],
        },
        "budget_hierarchy_reconciliation": {
            "version": VERSION,
            "summary": ((context.get("budget_hierarchy_reconciliation") or {}).get("summary") or {}),
            "sample_rows": ((context.get("budget_hierarchy_reconciliation") or {}).get("rows") or [])[:80],
        },
        "entity_chain_conflict_resolver": {
            "version": VERSION,
            "summary": ((context.get("entity_chain_conflict_resolver") or {}).get("summary") or {}),
            "conflicts": ((context.get("entity_chain_conflict_resolver") or {}).get("conflicts") or [])[:120],
            "confirmations": ((context.get("entity_chain_conflict_resolver") or {}).get("confirmations") or [])[:120],
        },
        "strict_but_realistic_closure": {
            "version": VERSION,
            "summary": strict.get("summary") or {},
            "sample_rows": (strict.get("rows") or [])[:80],
        },
    }
