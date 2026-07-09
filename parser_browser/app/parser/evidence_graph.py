from __future__ import annotations

import difflib
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Tuple

from app.core.schemas import BlocoComposicao, Composicoes, LinhaComposicao, OrcamentoItem, OrcamentoSintetico
from app.parser.broken_line_recovery import (
    canon_bank,
    clean_text,
    codebank,
    is_sicro_bank,
    is_truncated_text,
    norm_code,
    norm_text,
    pollution_reason,
    similarity,
    text_quality_score,
)

VERSION = "v61.0.75-correction-output-contract-and-review-index"


def _all_budget_items(nodes: Iterable[OrcamentoItem]) -> Iterable[OrcamentoItem]:
    for node in nodes or []:
        yield node
        yield from _all_budget_items(getattr(node, "filhos", []) or [])


def _iter_blocks(comp: Composicoes):
    for collection, blocks in (("principais", comp.principais), ("auxiliares_globais", comp.auxiliares_globais)):
        for key, block in (blocks or {}).items():
            yield collection, key, block


def _iter_lines(block: BlocoComposicao) -> Iterable[Tuple[str, int | None, LinhaComposicao]]:
    if getattr(block, "principal", None) is not None:
        yield "principal", None, block.principal
    for idx, row in enumerate(block.composicoes_auxiliares or []):
        yield "composicoes_auxiliares", idx, row
    for idx, row in enumerate(block.insumos or []):
        yield "insumos", idx, row


def _quality(desc: Any, *, source_weight: float = 1.0) -> float:
    text = clean_text(desc)
    if not text or pollution_reason(text):
        return 0.0
    score = text_quality_score(text) * source_weight
    if len(text) >= 45 and not is_truncated_text(text):
        score += 0.5
    return round(max(score, 0.0), 4)


def _add_occurrence(graph: Dict[str, Any], key: str, *, codigo: Any, banco: Any, descricao: Any, source: str, source_type: str, path: str = "", item: str = "") -> None:
    desc = clean_text(descricao)
    if not key or not desc or pollution_reason(desc):
        return
    source_weight = 1.08 if source_type == "composition_principal" else 1.0 if source_type.startswith("composition") else 0.96
    q = _quality(desc, source_weight=source_weight)
    if q <= 0:
        return
    entry = graph.setdefault(key, {
        "codebank": key,
        "codigo": clean_text(codigo),
        "banco_canonico": canon_bank(banco),
        "occurrences": [],
        "description_clusters": [],
        "best_description": "",
        "best_score": 0.0,
        "confirmed": False,
        "conflicts": [],
        "locked_negative_evidence": False,
    })
    occurrence = {
        "descricao": desc,
        "score": q,
        "source": source,
        "source_type": source_type,
        "path": path,
        "item": item,
        "truncated": is_truncated_text(desc),
        "length": len(desc),
    }
    entry["occurrences"].append(occurrence)


def _cluster_descriptions(occurrences: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    clusters: List[Dict[str, Any]] = []
    for occ in sorted(occurrences, key=lambda x: (float(x.get("score") or 0), int(x.get("length") or 0)), reverse=True):
        desc = clean_text(occ.get("descricao"))
        if not desc:
            continue
        placed = False
        for cluster in clusters:
            rep = cluster.get("representative") or ""
            sim = similarity(desc, rep)
            if sim >= 0.88 or norm_text(desc).startswith(norm_text(rep)) or norm_text(rep).startswith(norm_text(desc)):
                cluster["occurrences"].append(occ)
                if float(occ.get("score") or 0) > float(cluster.get("score") or 0) or len(desc) > len(cluster.get("representative") or ""):
                    cluster["representative"] = desc
                    cluster["score"] = float(occ.get("score") or 0)
                placed = True
                break
        if not placed:
            clusters.append({"representative": desc, "score": float(occ.get("score") or 0), "occurrences": [occ]})
    for c in clusters:
        c["occurrence_count"] = len(c.get("occurrences") or [])
        c["source_types"] = sorted(set(str(o.get("source_type") or "") for o in c.get("occurrences") or []))
    return sorted(clusters, key=lambda c: (len(c.get("occurrences") or []), float(c.get("score") or 0), len(c.get("representative") or "")), reverse=True)


def _finalize_graph(graph: Dict[str, Any]) -> Dict[str, Any]:
    for entry in graph.values():
        clusters = _cluster_descriptions(entry.get("occurrences") or [])
        entry["description_clusters"] = [
            {
                "representative": c.get("representative"),
                "score": round(float(c.get("score") or 0), 4),
                "occurrence_count": c.get("occurrence_count"),
                "source_types": c.get("source_types"),
                "examples": [
                    {"source": o.get("source"), "path": o.get("path"), "descricao": o.get("descricao"), "score": o.get("score")}
                    for o in (c.get("occurrences") or [])[:4]
                ],
            }
            for c in clusters[:6]
        ]
        best = clusters[0] if clusters else {}
        best_desc = clean_text(best.get("representative"))
        best_count = int(best.get("occurrence_count") or 0)
        source_types = set(best.get("source_types") or [])
        entry["best_description"] = best_desc
        entry["best_score"] = round(float(best.get("score") or 0), 4)
        entry["confirmed"] = bool(
            best_desc
            and not is_truncated_text(best_desc)
            and not pollution_reason(best_desc)
            and (
                best_count >= 2
                or len(source_types) >= 2
                or (float(entry.get("best_score") or 0) >= 2.8 and len(best_desc) >= 45)
            )
        )
        entry["locked_negative_evidence"] = bool(entry["confirmed"] and len(best_desc) >= 45)
        conflicts = []
        for c in clusters[1:]:
            desc = clean_text(c.get("representative"))
            if desc and best_desc and similarity(desc, best_desc) < 0.72:
                conflicts.append({
                    "descricao": desc,
                    "score": round(float(c.get("score") or 0), 4),
                    "occurrence_count": c.get("occurrence_count"),
                    "similarity_to_best": round(similarity(desc, best_desc), 4),
                })
        entry["conflicts"] = conflicts[:5]
    return graph


def build_evidence_graph(orcamento: OrcamentoSintetico | None, comp: Composicoes | None, *, context: dict | None = None) -> Dict[str, Any]:
    """Build a document-wide evidence graph keyed by codigo|banco.

    The graph is intentionally descriptive: it records positive evidence
    (confirmed descriptions) and negative evidence (a row is already complete,
    so nearby fragments should not be attached to it).  No document-specific
    hardcode is used here; the decision is based on repetition, source diversity,
    text quality and cross-table agreement.
    """
    graph: Dict[str, Any] = {}
    if comp is not None:
        for collection, block_key, block in _iter_blocks(comp):
            for group, idx, line in _iter_lines(block):
                if is_sicro_bank(getattr(line, "banco", "")):
                    continue
                key = codebank(getattr(line, "codigo", ""), getattr(line, "banco", ""))
                source_type = "composition_principal" if group == "principal" else "composition_detail"
                _add_occurrence(
                    graph,
                    key,
                    codigo=getattr(line, "codigo", ""),
                    banco=getattr(line, "banco", ""),
                    descricao=getattr(line, "descricao", ""),
                    source=f"composition.{collection}.{block_key}.{group}{'' if idx is None else '.' + str(idx)}",
                    source_type=source_type,
                    path=f"composicoes.{collection}.{block_key}.{group}{'' if idx is None else '.' + str(idx)}",
                    item=getattr(block, "item", ""),
                )
    if orcamento is not None:
        for item in _all_budget_items(getattr(orcamento, "itens_raiz", []) or []):
            if str(getattr(item, "tipo", "")).lower() != "item":
                continue
            key = codebank(getattr(item, "codigo", ""), getattr(item, "fonte", ""))
            _add_occurrence(
                graph,
                key,
                codigo=getattr(item, "codigo", ""),
                banco=getattr(item, "fonte", ""),
                descricao=getattr(item, "especificacao", ""),
                source=f"budget.{getattr(item, 'item', '')}",
                source_type="budget_item",
                path=f"orcamento_sintetico.item.{getattr(item, 'item', '')}",
                item=getattr(item, "item", ""),
            )
    finalized = _finalize_graph(graph)
    return {
        "version": VERSION,
        "entries": finalized,
        "summary": {
            "entries": len(finalized),
            "confirmed": sum(1 for e in finalized.values() if e.get("confirmed")),
            "with_conflicts": sum(1 for e in finalized.values() if e.get("conflicts")),
        },
    }


def _should_apply_graph_patch(current: str, candidate: str) -> Tuple[bool, str, float]:
    current = clean_text(current)
    candidate = clean_text(candidate)
    if not candidate:
        return False, "empty_candidate", 0.0
    if pollution_reason(candidate):
        return False, pollution_reason(candidate), 0.0
    if current and norm_text(current) == norm_text(candidate):
        return False, "no_op_same_value", 1.0
    sim = similarity(current, candidate) if current else 0.0
    current_in_candidate = bool(current and norm_text(current) in norm_text(candidate))
    prefix_ok = bool(current and norm_text(candidate).startswith(norm_text(current)))
    current_weak = (not current) or is_truncated_text(current) or len(current) < 42 or (current_in_candidate and len(candidate) > len(current) + 6)
    if not current_weak:
        return False, "current_not_weak", sim
    if current and not (prefix_ok or current_in_candidate or sim >= 0.70):
        return False, "candidate_not_compatible_with_current", sim
    score = text_quality_score(candidate) + (1.0 if prefix_ok else 0.0) + (0.7 if current_in_candidate else 0.0) + sim
    if score < 3.0:
        return False, "score_below_graph_threshold", score
    return True, "graph_confirmed_description", round(score, 4)


def apply_evidence_graph_recheck(orcamento: OrcamentoSintetico, comp: Composicoes, evidence_graph: Dict[str, Any]) -> Dict[str, Any]:
    entries = (evidence_graph or {}).get("entries") or {}
    repairs: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    metrics = {"budget_scanned": 0, "composition_rows_scanned": 0, "repairs_applied": 0, "repairs_rejected": 0, "negative_locks": 0}

    def best_for_key(key: str) -> Dict[str, Any]:
        ent = entries.get(key) or {}
        if ent.get("confirmed") and ent.get("best_description"):
            return ent
        return {}

    for item in _all_budget_items(getattr(orcamento, "itens_raiz", []) or []):
        if str(getattr(item, "tipo", "")).lower() != "item":
            continue
        metrics["budget_scanned"] += 1
        key = codebank(getattr(item, "codigo", ""), getattr(item, "fonte", ""))
        ent = best_for_key(key)
        if not ent:
            continue
        current = clean_text(getattr(item, "especificacao", ""))
        candidate = clean_text(ent.get("best_description"))
        ok, reason, score = _should_apply_graph_patch(current, candidate)
        decision = {"target": "budget", "item": getattr(item, "item", ""), "codebank": key, "before": current, "candidate": candidate, "decision": "applied" if ok else "rejected", "reason": reason, "score": score}
        if ok:
            item.especificacao = candidate
            repairs.append(decision)
            metrics["repairs_applied"] += 1
        else:
            rejected.append(decision)
            metrics["repairs_rejected"] += 1
            if reason in {"no_op_same_value", "current_not_weak"} and ent.get("locked_negative_evidence"):
                metrics["negative_locks"] += 1

    for collection, block_key, block in _iter_blocks(comp):
        if is_sicro_bank(getattr(getattr(block, "principal", None), "banco", "")):
            continue
        block_repairs: List[Dict[str, Any]] = []
        for group, idx, line in _iter_lines(block):
            metrics["composition_rows_scanned"] += 1
            key = codebank(getattr(line, "codigo", ""), getattr(line, "banco", ""))
            ent = best_for_key(key)
            if not ent:
                continue
            current = clean_text(getattr(line, "descricao", ""))
            candidate = clean_text(ent.get("best_description"))
            ok, reason, score = _should_apply_graph_patch(current, candidate)
            decision = {"target": "composition", "collection": collection, "block": block_key, "row_group": group, "row_index": idx, "codebank": key, "before": current, "candidate": candidate, "decision": "applied" if ok else "rejected", "reason": reason, "score": score}
            if ok:
                line.descricao = candidate
                repairs.append(decision); block_repairs.append(decision)
                metrics["repairs_applied"] += 1
            else:
                rejected.append(decision)
                metrics["repairs_rejected"] += 1
                if reason in {"no_op_same_value", "current_not_weak"} and ent.get("locked_negative_evidence"):
                    metrics["negative_locks"] += 1
        if block_repairs:
            detalhes = dict(getattr(block, "detalhes", {}) or {})
            detalhes.setdefault("evidence_graph_recheck", {})
            detalhes["evidence_graph_recheck"].update({"version": VERSION, "repairs": block_repairs})
            block.detalhes = detalhes

    return {"version": VERSION, "metrics": metrics, "repairs": repairs[:100], "rejected": rejected[:100]}
