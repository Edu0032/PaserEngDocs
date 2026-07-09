from __future__ import annotations

"""Clean stale diagnostics from the final contract.

The final JSON must show the current, repaired state.  Historical/pre-repair
snapshots remain useful, but they must be clearly moved to analytics so Lovable
or human reviewers do not read them as current errors.
"""

from typing import Any, Dict, Iterator, Tuple
from app.config.version import CURRENT_RELEASE


def _iter_blocks(composicoes: Dict[str, Any]) -> Iterator[Tuple[str, Dict[str, Any]]]:
    if not isinstance(composicoes, dict):
        return
    seen: set[int] = set()
    for fam_name in ("sinapi_like", "sicro"):
        fam = composicoes.get(fam_name)
        if isinstance(fam, dict):
            for collection in ("principais", "auxiliares_globais"):
                blocks = fam.get(collection)
                if isinstance(blocks, dict):
                    for key, block in blocks.items():
                        if isinstance(block, dict) and id(block) not in seen:
                            seen.add(id(block)); yield str(key), block
    for collection in ("principais", "auxiliares_globais"):
        blocks = composicoes.get(collection)
        if isinstance(blocks, dict):
            for key, block in blocks.items():
                if isinstance(block, dict) and id(block) not in seen:
                    seen.add(id(block)); yield str(key), block


def apply_clean_final_contract(result: Dict[str, Any]) -> Dict[str, Any]:
    report = {"version": CURRENT_RELEASE, "attempted": True, "snapshots_moved": 0, "stale_repair_results_marked_resolved": 0}
    corr = result.get("documento_correcao") if isinstance(result.get("documento_correcao"), dict) else {}
    analytics = result.setdefault("analise_orcamentaria", {})
    if isinstance(corr, dict):
        for key in list(corr.keys()):
            low = str(key).lower()
            if "preliminary" in low or "preliminar" in low or "pre_repair" in low:
                analytics.setdefault("pre_repair_snapshots", {})[key] = corr.pop(key)
                report["snapshots_moved"] += 1
        # Current final summary marker for downstream consumers.
        corr["final_contract_state"] = {
            "version": CURRENT_RELEASE,
            "current_quality_gate_path": "auditoria_final.quality_gate",
            "pre_repair_snapshots_moved_to": "analise_orcamentaria.pre_repair_snapshots",
            "supersedes_pre_repair_snapshots": True,
        }
    for _key, block in _iter_blocks(result.get("composicoes") if isinstance(result.get("composicoes"), dict) else {}):
        details = block.get("detalhes") if isinstance(block.get("detalhes"), dict) else {}
        math = details.get("math_status") if isinstance(details.get("math_status"), dict) else {}
        assist = details.get("docling_assistance") if isinstance(details.get("docling_assistance"), dict) else {}
        if math.get("ok") is True and str(assist.get("repair_result") or "").startswith("needs_"):
            assist["previous_repair_result"] = assist.get("repair_result")
            assist["repair_result"] = "resolved_after_final_integrity_orchestrator"
            assist["resolved_version"] = CURRENT_RELEASE
            report["stale_repair_results_marked_resolved"] += 1
    result.setdefault("meta", {}).setdefault("performance", {})["clean_final_contract"] = report
    result.setdefault("analise_orcamentaria", {}).setdefault("debug_recovery", {})["clean_final_contract"] = report
    return report
