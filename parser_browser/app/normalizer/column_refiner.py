from __future__ import annotations

import time
from copy import deepcopy
from typing import Any, Dict, List, Tuple

from app.normalizer.geometry_extractor import extract_page_geometry, _clean, _norm
from app.normalizer.sicro_section_maps import build_sicro_section_maps

VERSION = "v61.0.75-correction-output-contract-and-review-index"


def _as_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _canonical(col: Dict[str, Any] | None) -> str:
    if not isinstance(col, dict):
        return ""
    return str(col.get("canonical") or col.get("canonical_name") or "").strip()


def _expected_headers(table_hint: Dict[str, Any] | None) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for raw in list(dict(table_hint or {}).get("observed_headers") or []):
        if not isinstance(raw, dict):
            continue
        canonical = str(raw.get("canonical") or raw.get("canonical_name") or "").strip()
        if not canonical:
            continue
        item = dict(raw)
        item["canonical"] = canonical
        item["header_text"] = _clean(raw.get("header_text") or raw.get("text") or raw.get("header") or canonical)
        item["sample_text"] = _clean(raw.get("sample_text") or raw.get("content_text") or raw.get("first_row_text") or raw.get("first_content_text") or "")
        item["content_text"] = _clean(raw.get("content_text") or raw.get("sample_text") or raw.get("first_row_text") or "")
        out.append(item)
    return out


def _expected_order(expected: List[Dict[str, Any]]) -> List[str]:
    return [str(x.get("canonical") or "").strip() for x in expected if str(x.get("canonical") or "").strip()]


def _sample_candidates(header: Dict[str, Any], *, include_header: bool = False) -> List[str]:
    vals = [header.get("sample_text"), header.get("content_text"), header.get("first_row_text"), header.get("first_content_text")]
    if include_header:
        vals.append(header.get("header_text"))
    out: List[str] = []
    for v in vals:
        s = _clean(v)
        if s and s not in out:
            out.append(s)
    return out


def _tokens(value: Any) -> List[str]:
    return [t for t in _norm(value).split() if t]


def _word_texts(line: Dict[str, Any]) -> List[str]:
    return [_norm((w or {}).get("text")) for w in list(line.get("words") or [])]


def _find_sequence_in_line(line: Dict[str, Any], text: str) -> Dict[str, Any] | None:
    target = _tokens(text)
    if not target:
        return None
    words = list(line.get("words") or [])
    norm_words = _word_texts(line)
    if len(target) <= len(norm_words):
        for idx in range(0, len(norm_words) - len(target) + 1):
            if norm_words[idx:idx + len(target)] == target:
                matched = words[idx:idx + len(target)]
                return {
                    "text": " ".join(str(w.get("text") or "") for w in matched),
                    "x0": round(min(float(w.get("x0", 0)) for w in matched), 3),
                    "y0": round(min(float(w.get("y0", 0)) for w in matched), 3),
                    "x1": round(max(float(w.get("x1", 0)) for w in matched), 3),
                    "y1": round(max(float(w.get("y1", 0)) for w in matched), 3),
                    "line_text": line.get("text", ""),
                    "match_type": "token_sequence",
                }
    # Soft fallback: use the full line only for long text fragments that are present.
    if len(target) >= 3 and _norm(text) in str(line.get("norm_text") or ""):
        return {
            "text": text,
            "x0": line.get("x0"),
            "y0": line.get("y0"),
            "x1": line.get("x1"),
            "y1": line.get("y1"),
            "line_text": line.get("text", ""),
            "match_type": "line_contains",
        }
    return None


def _find_bbox_anywhere(page_geometry: Dict[str, Any], text: str) -> Dict[str, Any] | None:
    for line in list(page_geometry.get("lines") or []):
        match = _find_sequence_in_line(line, text)
        if match:
            return match
    return None


def _best_body_line(page_geometry: Dict[str, Any], expected: List[Dict[str, Any]]) -> Dict[str, Any] | None:
    lines = list(page_geometry.get("lines") or [])
    if not lines:
        return None
    candidates: List[Tuple[float, int, Dict[str, Any]]] = []
    for line in lines:
        score = 0.0
        matched = 0
        for header in expected:
            # Header text is kept as fallback, but body samples are weighted much higher.
            samples = _sample_candidates(header, include_header=False)
            for pos, sample in enumerate(samples):
                if not sample:
                    continue
                if _find_sequence_in_line(line, sample):
                    matched += 1
                    score += 3.0
                    break
        # A valid table body line usually contains at least two payload samples.
        if matched >= 2:
            width = (_as_float(line.get("x1")) or 0) - (_as_float(line.get("x0")) or 0)
            candidates.append((score + min(width, 500) / 1000.0, matched, line))
    if not candidates:
        return None
    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return candidates[0][2]


def _sample_bboxes(page_geometry: Dict[str, Any], expected: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Locate payload-provided first-row samples on the proper seed page.

    The line with the largest number of matched samples is selected first. This avoids
    accidentally matching repeated words in headers/footers or document metadata.
    """
    body_line = _best_body_line(page_geometry, expected)
    found: Dict[str, Dict[str, Any]] = {}
    for header in expected:
        can = str(header.get("canonical") or "").strip()
        if not can:
            continue
        for sample in _sample_candidates(header, include_header=False):
            bbox = _find_sequence_in_line(body_line, sample) if body_line else None
            if bbox:
                bbox["selected_body_line"] = True
                bbox["sample_text"] = sample
                found[can] = bbox
                break
    # Fallback only for columns not located on the best body line.
    for header in expected:
        can = str(header.get("canonical") or "").strip()
        if not can or can in found:
            continue
        for sample in _sample_candidates(header, include_header=True):
            bbox = _find_bbox_anywhere(page_geometry, sample)
            if bbox:
                bbox["selected_body_line"] = False
                bbox["sample_text"] = sample
                found[can] = bbox
                break
    return found


def _col_x0(col: Dict[str, Any] | None) -> float | None:
    if not isinstance(col, dict):
        return None
    meta = dict(col.get("metadata") or {})
    return _as_float(col.get("x0") if col.get("x0") is not None else meta.get("effective_x0"))


def _col_x1(col: Dict[str, Any] | None) -> float | None:
    if not isinstance(col, dict):
        return None
    meta = dict(col.get("metadata") or {})
    return _as_float(col.get("x1") if col.get("x1") is not None else meta.get("effective_x1"))


def _all_columns(table_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [c for c in list(table_payload.get("columns") or []) + list(table_payload.get("ignored_columns") or []) if isinstance(c, dict)]


def _find_column(table_payload: Dict[str, Any], canonical: str) -> Dict[str, Any] | None:
    if not canonical:
        return None
    for col in _all_columns(table_payload):
        if _canonical(col) == canonical:
            return col
    return None


def _neighbors(order: List[str], canonical: str) -> Tuple[str | None, str | None]:
    try:
        idx = order.index(canonical)
    except ValueError:
        return None, None
    left = order[idx - 1] if idx > 0 else None
    right = order[idx + 1] if idx + 1 < len(order) else None
    return left, right


def _bbox_x0(b: Dict[str, Any] | None) -> float | None:
    return _as_float((b or {}).get("x0"))


def _bbox_x1(b: Dict[str, Any] | None) -> float | None:
    return _as_float((b or {}).get("x1"))


def _infer_geometry(can: str, order: List[str], bboxes: Dict[str, Dict[str, Any]], table_payload: Dict[str, Any], page_width: float) -> Dict[str, Any] | None:
    bbox = bboxes.get(can)
    left, right = _neighbors(order, can)
    left_bbox = bboxes.get(left or "")
    right_bbox = bboxes.get(right or "")
    current_x0, current_x1 = _bbox_x0(bbox), _bbox_x1(bbox)
    if current_x0 is None or current_x1 is None or current_x1 <= current_x0:
        # Gap fallback when sample was not found.
        left_col = _find_column(table_payload, left or "")
        right_col = _find_column(table_payload, right or "")
        lx1 = _col_x1(left_col)
        rx0 = _col_x0(right_col)
        if lx1 is not None and rx0 is not None and rx0 - lx1 >= 4:
            return {"x0": round(lx1, 3), "x1": round(rx0, 3), "source": "gap_between_neighbor_columns"}
        return None

    # Boundaries are estimated from adjacent first-row samples when available.
    lx1 = _bbox_x1(left_bbox)
    rx0 = _bbox_x0(right_bbox)
    if lx1 is None:
        left_col = _find_column(table_payload, left or "")
        lx1 = _col_x1(left_col)
    if rx0 is None:
        right_col = _find_column(table_payload, right or "")
        rx0 = _col_x0(right_col)

    if lx1 is not None and lx1 <= current_x0:
        x0 = (lx1 + current_x0) / 2.0
    else:
        x0 = max(0.0, current_x0 - 2.0)
    if rx0 is not None and rx0 >= current_x1:
        x1 = (current_x1 + rx0) / 2.0
    else:
        x1 = min(page_width or (current_x1 + 8.0), current_x1 + 4.0)
    # Ensure the detected sample always stays inside its own refined band.
    x0 = min(x0, current_x0)
    x1 = max(x1, current_x1)
    left_col = _find_column(table_payload, left or "")
    right_col = _find_column(table_payload, right or "")
    left_boundary = _col_x1(left_col)
    right_boundary = _col_x0(right_col)
    if left_boundary is not None and left_boundary <= current_x0 and x0 < left_boundary:
        x0 = left_boundary
    if right_boundary is not None and right_boundary >= current_x1 and x1 > right_boundary:
        x1 = right_boundary
    if x1 <= x0:
        x0, x1 = current_x0, current_x1
    return {"x0": round(x0, 3), "x1": round(x1, 3), "source": "payload_first_row_geometry", "sample_bbox": bbox}


def _geometry_valid(col: Dict[str, Any] | None) -> bool:
    x0, x1 = _col_x0(col), _col_x1(col)
    return x0 is not None and x1 is not None and x1 > x0


def _has_overlap(can: str, order: List[str], table_payload: Dict[str, Any], tolerance: float = 0.75) -> bool:
    col = _find_column(table_payload, can)
    if not _geometry_valid(col):
        return True
    x0, x1 = _col_x0(col), _col_x1(col)
    left, right = _neighbors(order, can)
    left_col = _find_column(table_payload, left or "")
    right_col = _find_column(table_payload, right or "")
    if _geometry_valid(left_col) and _col_x1(left_col) is not None and x0 is not None and _col_x1(left_col) > x0 + tolerance:
        return True
    if _geometry_valid(right_col) and _col_x0(right_col) is not None and x1 is not None and x1 > _col_x0(right_col) + tolerance:
        return True
    return False


def _sample_outside(can: str, bboxes: Dict[str, Dict[str, Any]], table_payload: Dict[str, Any], margin: float = 2.0) -> bool:
    bbox = bboxes.get(can)
    col = _find_column(table_payload, can)
    if not bbox or not _geometry_valid(col):
        return False
    bx0, bx1 = _bbox_x0(bbox), _bbox_x1(bbox)
    x0, x1 = _col_x0(col), _col_x1(col)
    if bx0 is None or bx1 is None or x0 is None or x1 is None:
        return False
    return bx0 < x0 - margin or bx1 > x1 + margin


def _upsert_column(table_payload: Dict[str, Any], column: Dict[str, Any], order: List[str]) -> None:
    can = _canonical(column)
    cols = [dict(c) for c in list(table_payload.get("columns") or []) if isinstance(c, dict)]
    replaced = False
    for idx, existing in enumerate(cols):
        if _canonical(existing) == can:
            merged = dict(existing)
            merged.update(column)
            cols[idx] = merged
            replaced = True
            break
    if not replaced:
        cols.append(column)
    def sort_key(c: Dict[str, Any]) -> Tuple[int, float, int]:
        can2 = _canonical(c)
        x = _col_x0(c)
        order_idx = order.index(can2) if can2 in order else 999
        return (0 if x is not None else 1, x if x is not None else 999999.0, order_idx)
    cols.sort(key=sort_key)
    # Keep physical_index only for columns with real geometry; logical columns remain null.
    physical = 0
    for c in cols:
        if _geometry_valid(c):
            c["physical_index"] = physical
            physical += 1
        else:
            c["physical_index"] = None
    table_payload["columns"] = cols


def _make_logical_column(can: str, header: Dict[str, Any], left: str | None, right: str | None, page_no: int) -> Dict[str, Any]:
    return {
        "canonical": can,
        "header": _clean(header.get("header_text") or can),
        "header_text": _clean(header.get("header_text") or can),
        "sample_text": _clean(header.get("sample_text") or ""),
        "content_text": _clean(header.get("content_text") or header.get("sample_text") or ""),
        "kind": "synthetic",
        "mode": "classification_only",
        "status": "unresolved_logical_only",
        "physical_index": None,
        "position_after": left,
        "position_before": right,
        "expected_between": [x for x in (left, right) if x],
        "geometry_source": "normalizer_local_logical_only",
        "geometry_confidence": 0.35,
        "metadata": {"normalizer_local": True, "synthetic": True, "classification_only": True, "seed_local_page": page_no},
    }


def _page_for_family(seed_meta: Dict[str, Any], family: str) -> int:
    roles = {str(k): str(v) for k, v in dict(seed_meta.get("roles") or {}).items()}
    wanted = "budget" if family == "budget" else "composition"
    for local, role in roles.items():
        if wanted in role:
            try:
                return int(local)
            except Exception:
                pass
    return 1 if wanted == "budget" else 2


def _table_family(key: str, table_payload: Dict[str, Any]) -> str:
    raw = str(table_payload.get("kind") or key or "").lower()
    if "budget" in raw or "orcamento" in raw:
        return "budget"
    return "composition"


def _refresh_summary(table_payload: Dict[str, Any], order: List[str], expected_by: Dict[str, Dict[str, Any]]) -> None:
    final_cols = _all_columns(table_payload)
    found = [_canonical(c) for c in final_cols if _canonical(c)]
    found_set = set(found)
    table_payload["available_columns"] = list(dict.fromkeys(found))
    table_payload["missing_expected_columns"] = [c for c in order if c not in found_set]
    table_payload["missing_domain_columns"] = [c for c in order if c not in found_set and not bool((expected_by.get(c) or {}).get("ignore_in_domain"))]
    table_payload["usable_for"] = [c for c in order if c in found_set]
    table_payload["partial_structure"] = bool(table_payload["missing_expected_columns"])


def refine_table_structure(pdf_bytes: bytes, payload: Dict[str, Any]) -> Dict[str, Any]:
    started = time.perf_counter()
    source_payload = dict(payload or {})
    docling_payload = dict(source_payload.get("docling_clean_payload") or source_payload.get("docling_response") or source_payload.get("structured_tables") or source_payload)
    tables_hints = dict(source_payload.get("tables") or docling_payload.get("table_hints") or {})
    seed_meta = dict(source_payload.get("docling_seed_pdf") or docling_payload.get("docling_seed_pdf") or (docling_payload.get("metadata") or {}).get("docling_seed_pdf") or {})
    if not isinstance(docling_payload.get("tables"), dict):
        docling_payload.setdefault("tables", {})

    geometry_started = time.perf_counter()
    pages = extract_page_geometry(pdf_bytes)
    sicro_section_maps = build_sicro_section_maps(pages)
    geometry_ms = round((time.perf_counter() - geometry_started) * 1000, 3)

    out = deepcopy(docling_payload)
    out["version"] = VERSION
    out["source"] = "normalizer_local"
    out.setdefault("metadata", {})
    report: Dict[str, Any] = {
        "version": VERSION,
        "normalization_owner": "normalizer_local_exclusive",
        "local_seed_validator_removed": True,
        "process_only_anomalies": True,
        "seed_page_scoped": True,
        "tables": {},
        "sicro_section_maps": sicro_section_maps,
    }

    for key, table_payload in list(dict(out.get("tables") or {}).items()):
        if not isinstance(table_payload, dict):
            continue
        family = _table_family(key, table_payload)
        hint_key = "budget" if family == "budget" else "composition"
        expected = _expected_headers(tables_hints.get(hint_key) or {})
        order = _expected_order(expected)
        expected_by = {h["canonical"]: h for h in expected}
        if not order:
            table_payload.setdefault("warnings", []).append({"code": "normalizer_no_payload_expected_order", "action": "kept_docling_geometry"})
            continue

        page_no = _page_for_family(seed_meta, family)
        page_geometry = pages.get(page_no) or next(iter(pages.values()), {})
        page_width = _as_float(page_geometry.get("width")) or 9999.0
        bboxes = _sample_bboxes(page_geometry, expected)
        all_cols = _all_columns(table_payload)
        available = {_canonical(c) for c in all_cols if _canonical(c)}
        missing_before = [c for c in order if c not in available]
        locked: List[str] = []
        refined: List[str] = []
        unresolved: List[str] = []
        evidence: List[Dict[str, Any]] = []

        for can in order:
            header = expected_by.get(can, {})
            left, right = _neighbors(order, can)
            col = _find_column(table_payload, can)
            missing = col is None
            invalid = not _geometry_valid(col)
            overlap = False if missing else _has_overlap(can, order, table_payload)
            outside = False if missing else _sample_outside(can, bboxes, table_payload)
            suspected = missing or invalid or overlap or outside

            if not suspected:
                assert col is not None
                col.setdefault("status", "locked")
                col.setdefault("geometry_source", col.get("geometry_source") or "docling_locked_by_normalizer")
                locked.append(can)
                continue

            geom = _infer_geometry(can, order, bboxes, table_payload, page_width)
            item_evidence = {
                "canonical": can,
                "missing": missing,
                "invalid_geometry": invalid,
                "overlap_detected": overlap,
                "sample_outside_band": outside,
                "sample_bbox": bboxes.get(can),
                "inferred_geometry": geom,
                "expected_between": [x for x in (left, right) if x],
            }
            if geom and _as_float(geom.get("x1")) is not None and _as_float(geom.get("x0")) is not None and float(geom["x1"]) > float(geom["x0"]):
                new_col = dict(col or {})
                new_col.update({
                    "canonical": can,
                    "header": _clean(header.get("header_text") or (col or {}).get("header") or can),
                    "header_text": _clean(header.get("header_text") or (col or {}).get("header_text") or can),
                    "sample_text": _clean(header.get("sample_text") or (col or {}).get("sample_text") or ""),
                    "content_text": _clean(header.get("content_text") or header.get("sample_text") or (col or {}).get("content_text") or ""),
                    "kind": (col or {}).get("kind") or ("synthetic" if missing else "physical"),
                    "mode": "physical_refined",
                    "x0": round(float(geom["x0"]), 3),
                    "x1": round(float(geom["x1"]), 3),
                    "width": round(float(geom["x1"]) - float(geom["x0"]), 3),
                    "status": "refined" if missing or invalid or outside else "shifted_neighbor",
                    "geometry_source": f"normalizer_local_{geom.get('source')}",
                    "geometry_confidence": 0.93 if geom.get("source") == "payload_first_row_geometry" else 0.78,
                    "position_after": left,
                    "position_before": right,
                    "expected_between": [x for x in (left, right) if x],
                    "metadata": {**dict((col or {}).get("metadata") or {}), "normalizer_local": True, "exclusive_refinement": True, "sample_bbox": bboxes.get(can), "inferred_geometry": geom},
                })
                _upsert_column(table_payload, new_col, order)
                refined.append(can)
            else:
                logical = _make_logical_column(can, header, left, right, page_no)
                _upsert_column(table_payload, logical, order)
                unresolved.append(can)
            evidence.append(item_evidence)

        _refresh_summary(table_payload, order, expected_by)
        table_payload["normalizer_status"] = "ok"
        table_report = {
            "family": family,
            "local_seed_page": page_no,
            "missing_before": missing_before,
            "locked_columns": locked,
            "refined_columns": refined,
            "unresolved_columns": unresolved,
            "evidence": evidence,
            "sample_bboxes": bboxes,
        }
        table_payload.setdefault("metadata", {})["normalizer_local"] = table_report
        table_payload.setdefault("warnings", []).append({
            "code": "normalizer_local_exclusive_applied",
            "locked_columns": locked,
            "refined_columns": refined,
            "unresolved_columns": unresolved,
        })
        report["tables"][key] = table_report

    out["metadata"]["normalizer_report"] = report
    if sicro_section_maps:
        out["metadata"]["sicro_section_maps"] = sicro_section_maps
    out["metadata"]["performance_trace"] = {
        **dict(out["metadata"].get("performance_trace") or {}),
        "normalizer_geometry_ms": geometry_ms,
        "normalizer_total_ms": round((time.perf_counter() - started) * 1000, 3),
        "normalizer_page_count": len(pages),
    }
    out["metadata"]["normalizer_local"] = {"version": VERSION, "status": "ok", "tools": ["PyMuPDF.get_text(words)"], "exclusive_refinement": True}
    return out
