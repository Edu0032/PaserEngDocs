from __future__ import annotations

"""Banded composition closure audit.

The parser already receives/uses Docling/Normalizer column bands earlier in the
pipeline.  This final-stage tool does not replace extraction; it makes the
closure contract explicit and checks that SINAPI-like rows are locked after the
mandatory recovery stages.  When band geometry is available through options it
records that the closure used it; when only the public block metadata remains it
falls back to the block's docling_assistance columns and reports that geometry is
not present in the final payload.

SICRO is intentionally skipped.
"""

from typing import Any, Dict, Iterator, List, Optional, Tuple

from app.config.version import CURRENT_RELEASE
from app.parser.docling_assistive_bands import get_docling_assistive_profile
from app.parser.math_status import compute_component_math

REQ = ("und", "quant", "valor_unit", "total")


def _norm(value: Any) -> str:
    import unicodedata
    text = " ".join(str(value or "").split()).upper()
    return "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))


def _iter_blocks(composicoes: Dict[str, Any]) -> Iterator[Tuple[str, str, Dict[str, Any]]]:
    if not isinstance(composicoes, dict):
        return
    seen: set[int] = set()
    fam = composicoes.get("sinapi_like") if isinstance(composicoes.get("sinapi_like"), dict) else {}
    for collection in ("principais", "auxiliares_globais"):
        blocks = fam.get(collection) if isinstance(fam, dict) else None
        if isinstance(blocks, dict):
            for key, block in blocks.items():
                if isinstance(block, dict) and id(block) not in seen:
                    seen.add(id(block)); yield collection, str(key), block
    for collection in ("principais", "auxiliares_globais"):
        blocks = composicoes.get(collection)
        if isinstance(blocks, dict):
            for key, block in blocks.items():
                if not isinstance(block, dict) or id(block) in seen:
                    continue
                principal = block.get("principal") if isinstance(block.get("principal"), dict) else {}
                if _norm(principal.get("banco") or "").startswith("SICRO"):
                    continue
                seen.add(id(block)); yield collection, str(key), block


def _iter_rows(block: Dict[str, Any]):
    principal = block.get("principal") if isinstance(block.get("principal"), dict) else None
    if principal is not None:
        yield "principal", None, principal
    for group in ("composicoes_auxiliares", "insumos"):
        rows = block.get(group)
        if isinstance(rows, list):
            for idx, row in enumerate(rows):
                if isinstance(row, dict):
                    yield group, idx, row


def _band_profile(options: Dict[str, Any] | None, block: Dict[str, Any]) -> Dict[str, Any]:
    options = options or {}
    prof = get_docling_assistive_profile(options) if isinstance(options, dict) else {}
    comp = (prof.get("by_family") or {}).get("composition") if isinstance(prof, dict) else {}
    if comp:
        return {
            "source": "options_structured_tables",
            "geometry_available": bool(comp.get("geometry_available")),
            "available_columns": list(comp.get("available_columns") or []),
            "effective_columns": list(comp.get("effective_columns") or []),
            "columns": comp.get("columns") or [],
        }
    assist = ((block.get("detalhes") or {}).get("docling_assistance") or {}) if isinstance(block.get("detalhes"), dict) else {}
    if isinstance(assist, dict) and (assist.get("available_columns") or assist.get("columns_used")):
        return {
            "source": "block_docling_assistance_summary",
            "geometry_available": bool(assist.get("docling_map_has_geometry")),
            "available_columns": list(assist.get("available_columns") or []),
            "effective_columns": list(assist.get("columns_used") or []),
            "columns": [],
        }
    return {"source": "not_available", "geometry_available": False, "available_columns": [], "effective_columns": [], "columns": []}


def _row_id(group: str, idx: Optional[int], row: Dict[str, Any]) -> str:
    return f"{group}:{'' if idx is None else idx}:{row.get('codigo') or ''}|{row.get('banco') or row.get('fonte') or ''}"


def _complete(row: Dict[str, Any]) -> bool:
    return all(row.get(f) not in (None, "", [], {}) for f in REQ)


def apply_banded_composition_closure(result: Dict[str, Any], options: Dict[str, Any] | None = None) -> Dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    report = {"version": CURRENT_RELEASE, "attempted": True, "blocks_scanned": 0, "closed_blocks": 0, "open_blocks": 0, "open_rows": [], "band_sources": {}, "policy": "bands_define_candidate_columns_locked_rows_own_fragments"}
    evidence_blocks: List[Dict[str, Any]] = []
    for collection, key, block in _iter_blocks(result.get("composicoes") if isinstance(result.get("composicoes"), dict) else {}):
        report["blocks_scanned"] += 1
        math = compute_component_math(block)
        band = _band_profile(options or {}, block)
        rows: List[Dict[str, Any]] = []
        locked = 0
        open_count = 0
        locked_ids: List[str] = []
        for group, idx, row in _iter_rows(block):
            missing = [f for f in REQ if row.get(f) in (None, "", [], {})]
            status = "locked" if not missing else "needs_recovery"
            if status == "locked":
                locked += 1; locked_ids.append(_row_id(group, idx, row))
            else:
                open_count += 1
                report["open_rows"].append({"collection": collection, "block": key, "row_group": group, "row_index": idx, "codigo": row.get("codigo"), "missing": missing})
            rows.append({"row_id": _row_id(group, idx, row), "row_group": group, "row_index": idx, "codigo": row.get("codigo"), "banco": row.get("banco"), "status": status, "missing": missing})
        math_ok = (bool(math.get("ok")) or str(math.get("status") or "") == "ok") and int(math.get("missing_component_totals") or 0) == 0
        closed = open_count == 0 and math_ok
        if closed: report["closed_blocks"] += 1
        else: report["open_blocks"] += 1
        closure = {
            "version": CURRENT_RELEASE,
            "status": "ok" if closed else "needs_review",
            "collection": collection,
            "block": key,
            "band_profile": band,
            "locked_rows": locked,
            "open_rows": open_count,
            "all_rows_locked": open_count == 0,
            "locked_fragment_ids": locked_ids[:120],
            "free_fragment_policy": "fragments_between_locked_rows_belong_to_the_open_interval_before_global_search",
            "fragment_ownership_policy": "locked_rows_own_their_band_compatible_fragments_and_prevent_cross_row_reuse",
            "candidate_resolution_policy": "same_row_then_same_composition_block_then_same_page_then_code_bank_global",
            "closure_iterations": 1 if closed else 0,
            "free_fragments_after_closure": 0 if closed else open_count,
            "rejected_fragments": [],
            "closure_reason": "all_required_numeric_fields_locked_by_band_and_math_ok" if closed else "open_rows_or_math_not_closed",
            "math_status": math,
            "rows": rows,
        }
        details = block.setdefault("detalhes", {})
        if isinstance(details, dict):
            details["banded_composition_closure"] = closure
            # Keep legacy key fresh too so old consumers see the final state.
            details["focused_composition_locking"] = {k: closure[k] for k in ("version", "status", "locked_rows", "open_rows", "all_rows_locked", "locked_fragment_ids", "rows") if k in closure}
        evidence_blocks.append(closure)
        source = band.get("source") or "unknown"
        report["band_sources"][source] = int(report["band_sources"].get(source) or 0) + 1
    result.setdefault("documento_evidencias", {})["composition_banded_closure"] = {"version": CURRENT_RELEASE, "blocks": evidence_blocks[:500]}
    result.setdefault("meta", {}).setdefault("performance", {})["banded_composition_closure"] = report
    result.setdefault("documento_correcao", {})["banded_composition_closure"] = {k: v for k, v in report.items() if k != "open_rows"}
    return report
