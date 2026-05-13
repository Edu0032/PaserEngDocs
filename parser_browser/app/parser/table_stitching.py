from __future__ import annotations

from typing import Any, Dict, List


def stitch_table_segments(segments: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Agrupa segmentos compatíveis de páginas consecutivas.

    A heurística é propositalmente conservadora: só costura segmentos quando o kind
    e o conjunto de colunas canônicas coincidem. Isso ajuda a não encerrar composição
    longa apenas porque a página mudou, mas evita misturar famílias diferentes.
    """
    if not segments:
        return {"groups": [], "group_count": 0}
    ordered = sorted(segments, key=lambda seg: int(seg.get("page_no") or 0))
    groups: List[Dict[str, Any]] = []
    current: Dict[str, Any] | None = None
    for seg in ordered:
        cols = tuple(sorted((seg.get("column_map") or {}).keys()))
        signature = (seg.get("table_kind"), cols)
        if current is None:
            current = {
                "signature": signature,
                "pages": [seg.get("page_no")],
                "segments": [seg],
                "confidence": float(seg.get("confidence") or 0.0),
            }
            continue
        prev_page = int(current["pages"][-1] or 0)
        page_no = int(seg.get("page_no") or 0)
        if page_no == prev_page + 1 and signature == current["signature"]:
            current["pages"].append(page_no)
            current["segments"].append(seg)
            current["confidence"] = max(float(current.get("confidence") or 0.0), float(seg.get("confidence") or 0.0))
        else:
            groups.append(current)
            current = {
                "signature": signature,
                "pages": [page_no],
                "segments": [seg],
                "confidence": float(seg.get("confidence") or 0.0),
            }
    if current is not None:
        groups.append(current)
    for group in groups:
        group["cross_page_continuation"] = len(group["pages"]) > 1
    return {"groups": groups, "group_count": len(groups)}
