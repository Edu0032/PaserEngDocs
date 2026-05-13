from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional
import unicodedata
import re

from app.core.table_models import get_table_model
from app.parser.table_candidates import build_table_candidates
from app.parser.table_fusion import fuse_table_candidates
from app.parser.table_stitching import stitch_table_segments
from app.parser.sicro_structure import classify_sicro_rows


def _norm(text: Any) -> str:
    s = str(text or "").strip().lower()
    s = "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _compact(text: Any) -> str:
    return re.sub(r"[^a-z0-9%²³]", "", _norm(text))


def _split_aliases(values: Iterable[str]) -> List[str]:
    return [str(v).strip() for v in values if str(v or "").strip()]


def resolve_table_columns(rows: List[List[str]], *, model: Dict[str, Any]) -> Dict[str, Any]:
    if not rows:
        return {"matched": False, "header_index": None, "column_map": {}, "confidence": 0.0, "table_kind": model.get("kind") or "generic"}
    columns = list(model.get("columns") or [])
    best: Dict[str, Any] = {"matched": False, "header_index": None, "column_map": {}, "confidence": 0.0, "table_kind": model.get("kind") or "generic"}
    max_rows = min(len(rows), max(int(model.get("header_rows_expected") or 1) + 3, 4))
    for header_index in range(max_rows):
        row = [str(c or "").strip() for c in (rows[header_index] or [])]
        if not row:
            continue
        column_map: Dict[str, Dict[str, Any]] = {}
        total_score = 0.0
        for col in columns:
            canonical = str(col.get("canonical") or "").strip()
            aliases = _split_aliases(col.get("labels") or [])
            best_match: Optional[Dict[str, Any]] = None
            for col_index, cell in enumerate(row):
                cell_norm = _norm(cell)
                cell_compact = _compact(cell)
                score = 0.0
                for alias in aliases:
                    alias_norm = _norm(alias)
                    alias_compact = _compact(alias)
                    if alias == "" and (cell.strip() == "" or re.fullmatch(r"\d+(?:\.\d+)*", cell.strip() or "")):
                        score = max(score, 0.6)
                    elif alias_norm and (cell_norm == alias_norm or cell_compact == alias_compact):
                        score = max(score, 1.0)
                    elif alias_norm and (alias_norm in cell_norm or cell_norm in alias_norm):
                        score = max(score, 0.8)
                    elif alias_compact and (alias_compact in cell_compact or cell_compact in alias_compact):
                        score = max(score, 0.75)
                if canonical == "controle_linha" and re.fullmatch(r"\d+(?:\.\d+)*", cell.strip() or ""):
                    score = max(score, 0.9)
                if best_match is None or score > best_match["score"]:
                    best_match = {"col_index": col_index, "score": score, "header_text": cell}
            if best_match and best_match["score"] >= 0.6:
                column_map[canonical] = best_match
                total_score += float(best_match["score"])
        confidence = round(total_score / max(len(columns), 1), 3)
        if confidence > float(best.get("confidence") or 0.0):
            best = {
                "matched": bool(column_map),
                "header_index": header_index,
                "column_map": column_map,
                "confidence": confidence,
                "table_kind": model.get("kind") or "generic",
                "first_column_role": model.get("first_column_role") or "",
                "supports_blank_control_cells": bool(model.get("supports_blank_control_cells")),
                "supports_auxiliares_globais_sem_item": bool(model.get("supports_auxiliares_globais_sem_item")),
            }
    return best


def mapped_cell(row: List[str], semantics: Dict[str, Any] | None, canonical: str) -> str:
    semantics = semantics or {}
    mapping = (semantics.get("column_map") or {}).get(canonical) or {}
    idx = mapping.get("col_index")
    if idx is None:
        return ""
    try:
        return str((row or [])[int(idx)] or "").strip()
    except Exception:
        return ""


def infer_control_line_kind(cell_text: str, *, table_kind: str = "composition", supports_blank_control_cells: bool = False) -> str:
    text = _norm(cell_text)
    if table_kind == "composition_sicro":
        if re.fullmatch(r"[a-f]", text):
            return "SECAO_SICRO"
    if not text:
        return "AUXILIAR_GLOBAL_SEM_ITEM" if supports_blank_control_cells else ""
    compact = _compact(text)
    if re.fullmatch(r"\d+(?:\.\d+)*", text):
        return "CABECALHO_ITEM"
    if text.startswith("insumo"):
        return "INSUMO"
    if "auxiliar" in text:
        return "AUXILIAR"
    if text.startswith("compos") or compact.startswith("composicao"):
        return "COMPOSICAO"
    return ""


def analyze_rows_with_model(rows: List[List[str]], *, model: Dict[str, Any]) -> Dict[str, Any]:
    semantics = resolve_table_columns(rows, model=model)
    header_index = semantics.get("header_index")
    sample_rows: List[Dict[str, Any]] = []
    if header_index is not None:
        for row in rows[header_index + 1: header_index + 6]:
            control_text = mapped_cell(row, semantics, "controle_linha")
            sample_rows.append({
                "control_text": control_text,
                "line_kind": infer_control_line_kind(
                    control_text,
                    table_kind=str(semantics.get("table_kind") or model.get("kind") or "composition"),
                    supports_blank_control_cells=bool(semantics.get("supports_blank_control_cells")),
                ),
                "codigo": mapped_cell(row, semantics, "codigo"),
                "banco": mapped_cell(row, semantics, "banco"),
                "descricao": mapped_cell(row, semantics, "descricao"),
            })
    semantics["sample_rows"] = sample_rows
    return semantics


def resolve_table_family(profile: Dict[str, Any] | None, *, bank_hint: str = "") -> Dict[str, Any]:
    bank_norm = _norm(bank_hint)
    if bank_norm in {"sicro", "dnit", "sicro3"}:
        return get_table_model(profile, "composicoes_sicro")
    return get_table_model(profile, "composicoes_sinapi")



def summarize_session_tables(session: Any, *, page_range: tuple[int, int], profile: Dict[str, Any] | None = None, family: str = "composition") -> Dict[str, Any]:
    start, end = page_range
    if start < 1 or end < start or not hasattr(session, "get_pymupdf_tables"):
        return {"enabled": False, "tables": []}
    bank_hint = "SICRO" if family == "sicro" else ""
    if family == "budget":
        model = get_table_model(profile, "orcamento_sintetico")
    elif family == "sicro":
        model = get_table_model(profile, "composicoes_sicro")
    else:
        model = resolve_table_family(profile, bank_hint=bank_hint)
    tables: List[Dict[str, Any]] = []
    inspected_pages = 0
    for page_no in range(start, end + 1):
        inspected_pages += 1
        candidates = build_table_candidates(session, page_no, family=family, profile=profile, bank_hint=bank_hint)
        if not candidates:
            continue
        fused = fuse_table_candidates(candidates)
        if not fused.get("matched"):
            continue
        tables.append({
            "page_no": page_no,
            "bbox": list(fused.get("best_bbox") or []),
            "row_count": len(fused.get("best_rows") or []),
            "col_count": max((len(r) for r in (fused.get("best_rows") or [])), default=0),
            "table_kind": fused.get("table_kind") or model.get("kind"),
            "confidence": fused.get("confidence"),
            "column_map": fused.get("column_map") or {},
            "sample_rows": fused.get("sample_rows") or [],
            "best_rows": fused.get("best_rows") or [],
            "candidate_scores": fused.get("candidate_scores") or [],
            "strategies": fused.get("strategies") or [],
            "best_strategy": fused.get("best_strategy"),
        })
    stitching = stitch_table_segments(tables)
    if family == "sicro":
        for entry in tables:
            entry["sicro_structure"] = classify_sicro_rows(list(entry.get("best_rows") or [])) if entry.get("best_rows") else classify_sicro_rows([])
    return {
        "enabled": True,
        "family": family,
        "inspected_pages": inspected_pages,
        "tables": tables,
        "matched_tables": len(tables),
        "stitching": stitching,
    }
