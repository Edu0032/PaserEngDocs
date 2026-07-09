from __future__ import annotations

import statistics
from typing import Any, Dict, Iterable, List, Tuple

VERSION = "v61.0.39-deep-area-sweep-iterative-closure"


def _as_float(v: Any) -> float | None:
    try:
        if v in (None, ""):
            return None
        return float(v)
    except Exception:
        return None


def _clean(v: Any) -> str:
    return " ".join(str(v or "").replace("\u00a0", " ").split()).strip()


def _iter_tables(payload: Dict[str, Any] | None) -> Iterable[Tuple[str, Dict[str, Any]]]:
    data = payload or {}
    tables = data.get("tables") if isinstance(data.get("tables"), dict) else data
    if not isinstance(tables, dict):
        return
    for key, table in tables.items():
        if isinstance(table, dict):
            yield str(key), table


def _columns(table: Dict[str, Any]) -> List[Dict[str, Any]]:
    cols = []
    for c in list(table.get("columns") or []) + list(table.get("ignored_columns") or []):
        if isinstance(c, dict):
            canon = _clean(c.get("canonical") or c.get("canonical_name") or c.get("name"))
            x0 = _as_float(c.get("x0")); x1 = _as_float(c.get("x1"))
            if canon and (x0 is not None or x1 is not None):
                cols.append({**c, "canonical": canon, "x0": x0, "x1": x1, "width": _as_float(c.get("width"))})
    cols.sort(key=lambda c: (999999 if c.get("x0") is None else c.get("x0")))
    return cols


def _profile_bands_from_learning(profile: Dict[str, Any] | None, family: str) -> Dict[str, Dict[str, Any]]:
    profile = profile or {}
    key = "budget_profile" if family == "budget" else "sinapi_like_profile" if family in {"composition", "sinapi_like"} else f"{family}_profile"
    bands = ((profile.get(key) or {}).get("column_bands") or {}) if isinstance(profile.get(key), dict) else {}
    return bands if isinstance(bands, dict) else {}


def _band_median(values: List[float]) -> float | None:
    if not values:
        return None
    return round(float(statistics.median(values)), 3)


def calibrate_docling_profile(docling_payload: Dict[str, Any] | None, *, document_learning_profile: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Combine Docling seed geometry with the PyMuPDF/document-learning profile.

    Docling gives the first profile; local PyMuPDF/document_learning can adjust
    it when enough evidence exists. This function never mutates the input. It
    returns a stable, auditable profile used by targeted recovery and shown in
    Lovable's debug dashboard.
    """
    docling_payload = docling_payload or {}
    calibrated: Dict[str, Any] = {"version": VERSION, "tables": {}, "summary": {"tables": 0, "columns": 0, "pymupdf_adjusted_columns": 0, "low_confidence_columns": 0}}
    for family, table in _iter_tables(docling_payload):
        table_key = "budget" if family == "budget" else "composition" if family in {"composition", "sinapi_like"} else family
        learned = _profile_bands_from_learning(document_learning_profile, table_key)
        out_cols: List[Dict[str, Any]] = []
        for col in _columns(table):
            canon = _clean(col.get("canonical"))
            doc_x0 = _as_float(col.get("x0")); doc_x1 = _as_float(col.get("x1"))
            conf = _as_float(col.get("geometry_confidence"))
            if conf is None:
                conf = _as_float(col.get("confidence"))
            if conf is None:
                conf = 0.75
            learned_band = learned.get(canon) if isinstance(learned, dict) else None
            l_x0 = _as_float((learned_band or {}).get("x0_median") or (learned_band or {}).get("x0")) if isinstance(learned_band, dict) else None
            l_x1 = _as_float((learned_band or {}).get("x1_median") or (learned_band or {}).get("x1")) if isinstance(learned_band, dict) else None
            adjusted = False
            x0_values = [v for v in (doc_x0, l_x0) if v is not None]
            x1_values = [v for v in (doc_x1, l_x1) if v is not None]
            final_x0 = _band_median(x0_values)
            final_x1 = _band_median(x1_values)
            if l_x0 is not None and doc_x0 is not None and abs(l_x0 - doc_x0) > 2.0:
                adjusted = True
            if l_x1 is not None and doc_x1 is not None and abs(l_x1 - doc_x1) > 2.0:
                adjusted = True
            source = "docling+pymupdf_profile" if (l_x0 is not None or l_x1 is not None) else str(col.get("geometry_source") or "docling")
            c = {
                "canonical": canon,
                "header": col.get("header") or col.get("header_text") or col.get("text"),
                "x0": final_x0,
                "x1": final_x1,
                "width": round((final_x1 - final_x0), 3) if final_x0 is not None and final_x1 is not None else col.get("width"),
                "docling_x0": doc_x0,
                "docling_x1": doc_x1,
                "learned_x0": l_x0,
                "learned_x1": l_x1,
                "geometry_confidence": round(min(1.0, max(0.0, float(conf) + (0.08 if adjusted else 0.04 if source == "docling+pymupdf_profile" else 0))), 3),
                "geometry_source": source,
                "adjusted_by_pymupdf_profile": bool(adjusted),
                "status": "calibrated" if source == "docling+pymupdf_profile" else "docling_only",
            }
            out_cols.append(c)
            calibrated["summary"]["columns"] += 1
            if adjusted:
                calibrated["summary"]["pymupdf_adjusted_columns"] += 1
            if float(c["geometry_confidence"] or 0) < 0.80:
                calibrated["summary"]["low_confidence_columns"] += 1
        calibrated["tables"][table_key] = {
            "kind": table_key,
            "source": "docling_profile_calibrator",
            "columns": out_cols,
            "column_count": len(out_cols),
            "missing_expected_columns": list(table.get("missing_expected_columns") or []),
            "low_confidence_columns": [c["canonical"] for c in out_cols if float(c.get("geometry_confidence") or 0) < 0.80],
            "profile_ready_for_recovery": bool(out_cols),
        }
        calibrated["summary"]["tables"] += 1
    return calibrated


def merge_calibrated_profile_into_docling(docling_payload: Dict[str, Any] | None, document_learning_profile: Dict[str, Any] | None = None) -> Dict[str, Any]:
    payload = dict(docling_payload or {})
    profile = calibrate_docling_profile(payload.get("tables") or payload, document_learning_profile=document_learning_profile)
    payload.setdefault("metadata", {})
    payload["metadata"]["calibrated_document_profile"] = profile
    payload["calibrated_document_profile"] = profile
    return payload
