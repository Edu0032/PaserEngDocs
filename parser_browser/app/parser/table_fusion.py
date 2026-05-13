from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List


def _mapped_cell(row: List[str], semantics: Dict[str, Any] | None, canonical: str) -> str:
    semantics = semantics or {}
    mapping = (semantics.get("column_map") or {}).get(canonical) or {}
    idx = mapping.get("col_index")
    if idx is None:
        return ""
    try:
        return str((row or [])[int(idx)] or "").strip()
    except Exception:
        return ""


def _column_consensus(candidates: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    buckets: Dict[str, Counter] = defaultdict(Counter)
    by_detail: Dict[str, Dict[int, Dict[str, Any]]] = defaultdict(dict)
    for cand in candidates:
        semantic = dict(cand.get("semantic") or {})
        confidence = float((cand.get("scores") or {}).get("score") or cand.get("confidence") or 0.0)
        for canonical, detail in (semantic.get("column_map") or {}).items():
            try:
                col_index = int(detail.get("col_index"))
            except Exception:
                continue
            buckets[canonical][col_index] += max(int(round(confidence * 10)), 1)
            current = by_detail[canonical].get(col_index)
            if current is None or float(current.get("score") or 0.0) < confidence:
                by_detail[canonical][col_index] = {
                    "col_index": col_index,
                    "header_text": detail.get("header_text"),
                    "score": confidence,
                }
    out: Dict[str, Any] = {}
    for canonical, counter in buckets.items():
        col_index, votes = counter.most_common(1)[0]
        detail = dict(by_detail[canonical].get(col_index) or {})
        detail["votes"] = votes
        out[canonical] = detail
    return out


def fuse_table_candidates(candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not candidates:
        return {
            "matched": False,
            "confidence": 0.0,
            "candidate_count": 0,
            "column_map": {},
            "candidate_scores": [],
            "strategies": [],
            "table_kind": "generic",
        }
    ordered = sorted(candidates, key=lambda item: float(item.get("confidence") or 0.0), reverse=True)
    best = ordered[0]
    best_sem = dict(best.get("semantic") or {})
    column_map = _column_consensus(ordered)
    mean_conf = sum(float(item.get("confidence") or 0.0) for item in ordered) / max(len(ordered), 1)
    fusion_conf = round((float(best.get("confidence") or 0.0) * 0.65) + (mean_conf * 0.35), 3)
    return {
        "matched": bool(best_sem.get("matched") or column_map),
        "confidence": fusion_conf,
        "candidate_count": len(ordered),
        "candidate_scores": [
            {
                "candidate_id": item.get("candidate_id"),
                "strategy": item.get("strategy"),
                "score": float(item.get("confidence") or 0.0),
                "semantic_confidence": float((item.get("semantic") or {}).get("confidence") or 0.0),
                "row_count": item.get("row_count"),
                "col_count": item.get("col_count"),
            }
            for item in ordered
        ],
        "strategies": sorted({str(item.get("strategy") or "") for item in ordered if item.get("strategy")}),
        "table_kind": best_sem.get("table_kind") or best.get("family") or "generic",
        "header_index": best_sem.get("header_index"),
        "column_map": column_map or dict(best_sem.get("column_map") or {}),
        "first_column_role": best_sem.get("first_column_role") or "",
        "supports_blank_control_cells": bool(best_sem.get("supports_blank_control_cells")),
        "supports_auxiliares_globais_sem_item": bool(best_sem.get("supports_auxiliares_globais_sem_item")),
        "best_candidate_id": best.get("candidate_id"),
        "best_strategy": best.get("strategy"),
        "best_bbox": list(best.get("bbox") or []),
        "best_rows": list(best.get("rows") or []),
        "sample_rows": list(best_sem.get("sample_rows") or []),
    }


def fuse_candidates_to_matrix(candidates: List[Dict[str, Any]]) -> List[List[str]]:
    fused = fuse_table_candidates(candidates)
    return list(fused.get("best_rows") or [])


def collect_row_candidates(candidates: List[Dict[str, Any]], *, item: str = "", codigo: str = "") -> List[Dict[str, Any]]:
    """Expõe linhas compatíveis com um item/código através dos candidatos fundidos.

    Isso é útil para que o orçamento aproveite o consenso das estratégias sem depender
    de um único candidato vencedor.
    """
    item = str(item or "").strip()
    codigo = str(codigo or "").strip()
    out: List[Dict[str, Any]] = []
    for cand in candidates:
        sem = dict(cand.get("semantic") or {})
        for row in list(cand.get("rows") or []):
            cells = [str(c or "").strip() for c in row]
            if item and item not in cells:
                continue
            if codigo:
                code_cell = _mapped_cell(cells, sem, "codigo")
                joined = " ".join(cells)
                if codigo not in joined and codigo != code_cell:
                    continue
            out.append({
                "candidate_id": cand.get("candidate_id"),
                "strategy": cand.get("strategy"),
                "score": float(cand.get("confidence") or 0.0),
                "semantic": sem,
                "page_no": cand.get("page_no"),
                "row": cells,
            })
    out.sort(key=lambda entry: float(entry.get("score") or 0.0), reverse=True)
    return out
