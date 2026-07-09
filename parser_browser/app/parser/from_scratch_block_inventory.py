from __future__ import annotations

"""Compact PDF-first physical block inventory for the real final flow.

This module does not create public values and does not duplicate the extractor.
It scans the supplied PDF text using generic SINAPI-like anchors to prove that
critical physical blocks can be inventoried from the document itself.  The
result is intentionally compact: counts, pages, anchors and short row samples,
never raw full-page text.

Policy:
- every physical composition block should have a row inventory;
- row anchors are generic (Composição, Composição Auxiliar, Insumo), not
  document-specific;
- public JSON remains the source of final fields; this inventory is used by
  coverage/recovery/gates to detect rows/fragments that would otherwise be
  invisible.
"""

import re
from typing import Any, Dict, Iterable, Iterator, List, Tuple

from app.config.version import CURRENT_RELEASE
from app.core.pdf_session import PdfDocumentSession

_ROW_RE = re.compile(r"(?:^|\n)\s*(?P<natureza>Composi[cç][aã]o\s+Auxiliar|Composi[cç][aã]o|Insumo)\s+(?P<codigo>[A-Z0-9./ -]{2,30})\s+(?P<banco>SINAPI|PR[ÓO]PRIO|SICRO\w*)\b", re.IGNORECASE)
_HEADER_RE = re.compile(r"(?:^|\n)\s*(?P<item>\d+(?:\.\d+)*)\s+C[ÓO]DIGO\s+Banco\s+Descri", re.IGNORECASE)
_NUM = r"-?\d{1,3}(?:\.\d{3})*,\d+|-?\d+,\d+|-?\d+"
_UNIT = r"[%A-Za-zÀ-ÿ0-9²³./]+"
_TAIL_RE = re.compile(rf"(?P<und>{_UNIT})\s+(?P<quant>{_NUM})\s+(?P<valor_unit>{_NUM})\s+(?P<total>{_NUM})", re.IGNORECASE)


def _clean(value: Any) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split()).strip()


def _norm_code(value: Any) -> str:
    return re.sub(r"[^0-9A-Z]", "", _clean(value).upper())


def _short(text: Any, limit: int = 180) -> str:
    t = _clean(text)
    return t if len(t) <= limit else t[: limit - 1].rstrip() + "…"


def _iter_sinapi_blocks(composicoes: Dict[str, Any]) -> Iterator[Tuple[str, str, Dict[str, Any]]]:
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
                if _clean(principal.get("banco") or principal.get("fonte")).upper().startswith("SICRO"):
                    continue
                seen.add(id(block)); yield collection, str(key), block


def _pages_for_block(block: Dict[str, Any], options: Dict[str, Any] | None = None) -> List[int]:
    pages: List[int] = []
    for src in (block, block.get("detalhes") if isinstance(block.get("detalhes"), dict) else {}):
        if not isinstance(src, dict):
            continue
        raw = src.get("paginas")
        if isinstance(raw, list):
            for p in raw:
                try:
                    ip = int(p)
                    if ip > 0 and ip not in pages:
                        pages.append(ip)
                except Exception:
                    pass
        for k in ("pagina_inicio", "pagina_fim", "page", "page_hint"):
            try:
                ip = int(src.get(k) or 0)
                if ip > 0 and ip not in pages:
                    pages.append(ip)
            except Exception:
                pass
    if pages:
        return sorted(pages)
    ranges = (options or {}).get("ranges") if isinstance(options, dict) else {}
    comps = ranges.get("compositions") or ranges.get("composicoes") if isinstance(ranges, dict) else {}
    if isinstance(comps, dict):
        try:
            start = int(comps.get("start") or comps.get("inicio") or 0)
            end = int(comps.get("end") or comps.get("fim") or 0)
            if start > 0 and end >= start:
                return list(range(start, min(end, start + 8) + 1))
        except Exception:
            pass
    return []


def _extract_window_for_block(page_text: str, block: Dict[str, Any]) -> Tuple[str, str]:
    """Return a likely physical block window and a reason."""
    text = str(page_text or "")
    principal = block.get("principal") if isinstance(block.get("principal"), dict) else {}
    item = _clean(block.get("item"))
    code = _norm_code(principal.get("codigo") or "")
    bank = _clean(principal.get("banco") or "SINAPI").upper()
    candidates: List[int] = []
    if item:
        m = re.search(rf"(?:^|\n)\s*{re.escape(item)}\s+C[ÓO]DIGO\s+Banco\s+Descri", text, flags=re.IGNORECASE)
        if m:
            candidates.append(m.start())
    if code:
        m = re.search(rf"(?:Composi[cç][aã]o|Insumo)\s+{re.escape(code)}\s+{re.escape(bank)}\b", text, flags=re.IGNORECASE)
        if m:
            candidates.append(m.start())
    start = min(candidates) if candidates else 0
    # Stop at the next composition header after start, or at common SINAPI summary lines.
    end = len(text)
    for m in _HEADER_RE.finditer(text):
        if m.start() > start + 20:
            end = min(end, m.start()); break
    summary = re.search(r"\n\s*(?:MO\s+sem\s+LS|Valor\s+do\s+BDI|Valor\s+com\s+BDI|Total\s+sem\s+BDI)\b", text[start:], flags=re.IGNORECASE)
    if summary:
        end = min(end, start + summary.start())
    return text[start:end], "anchor_code_or_item" if candidates else "page_fallback"


def _inventory_rows(window: str) -> List[Dict[str, Any]]:
    matches = list(_ROW_RE.finditer(window or ""))
    rows: List[Dict[str, Any]] = []
    for i, m in enumerate(matches):
        seg_end = matches[i + 1].start() if i + 1 < len(matches) else len(window)
        seg = window[m.start():seg_end]
        tail = None
        tail_matches = list(_TAIL_RE.finditer(" ".join(seg.split())))
        if tail_matches:
            tm = tail_matches[-1]
            tail = {"und": _clean(tm.group("und")), "quant": _clean(tm.group("quant")), "valor_unit": _clean(tm.group("valor_unit")), "total": _clean(tm.group("total"))}
        rows.append({
            "row_index": i,
            "natureza": _clean(m.group("natureza")),
            "codigo": _clean(m.group("codigo")),
            "banco": _clean(m.group("banco")),
            "has_numeric_tail": bool(tail),
            "tail": tail,
            "sample": _short(seg, 160),
        })
    return rows


def _json_row_count(block: Dict[str, Any]) -> int:
    count = 1 if isinstance(block.get("principal"), dict) else 0
    for group in ("composicoes_auxiliares", "insumos"):
        if isinstance(block.get(group), list):
            count += sum(1 for r in block[group] if isinstance(r, dict))
    return count


def build_from_scratch_block_inventory(result: Dict[str, Any], *, pdf_session: PdfDocumentSession, options: Dict[str, Any] | None = None) -> Dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    options = options or {}
    blocks: List[Dict[str, Any]] = []
    full_scan = bool(options.get("from_scratch_inventory_full_scan") or ((options.get("accuracy_profile") or {}).get("from_scratch_inventory_full_scan") if isinstance(options.get("accuracy_profile"), dict) else False))
    target_blocks = set()
    for raw in (options.get("target_blocks"), options.get("target_compositions")):
        if isinstance(raw, list):
            target_blocks.update(str(x) for x in raw if str(x or "").strip())
    if not full_scan and not target_blocks:
        manifest = {
            "version": CURRENT_RELEASE,
            "summary": {
                "version": CURRENT_RELEASE,
                "policy": "pdf_first_compact_inventory_runs_on_target_blocks_or_explicit_full_scan",
                "block_count": 0,
                "complete_block_count": 0,
                "partial_block_count": 0,
                "not_found_block_count": 0,
                "physical_rows_total": 0,
                "rows_with_numeric_tail_total": 0,
                "overall_status": "skipped_no_target_blocks",
            },
            "blocks": [],
            "incomplete_blocks": [],
        }
        result.setdefault("documento_evidencias", {})["from_scratch_block_inventory"] = manifest
        result.setdefault("meta", {}).setdefault("performance", {})["from_scratch_block_inventory"] = dict(manifest["summary"])
        return manifest

    for _collection, key, block in _iter_sinapi_blocks(result.get("composicoes") if isinstance(result.get("composicoes"), dict) else {}):
        if target_blocks and key not in target_blocks:
            continue
        pages = _pages_for_block(block, options)
        if not pages:
            continue
        best_rows: List[Dict[str, Any]] = []
        best_page = None
        best_reason = "not_found"
        best_window_chars = 0
        for p in pages[:4]:
            try:
                txt = pdf_session.get_page_text(int(p))
            except Exception:
                continue
            window, reason = _extract_window_for_block(txt, block)
            rows = _inventory_rows(window)
            if len(rows) > len(best_rows):
                best_rows = rows; best_page = p; best_reason = reason; best_window_chars = len(window)
        expected_json_rows = _json_row_count(block)
        inventory_status = "complete" if best_rows and len(best_rows) >= expected_json_rows else ("partial" if best_rows else "not_found")
        missing_physical_vs_json = max(0, expected_json_rows - len(best_rows))
        blocks.append({
            "key": key,
            "item": block.get("item"),
            "pages_checked": pages[:4],
            "best_page": best_page,
            "window_reason": best_reason,
            "window_chars": best_window_chars,
            "json_row_count": expected_json_rows,
            "physical_row_count": len(best_rows),
            "rows_with_numeric_tail": sum(1 for r in best_rows if r.get("has_numeric_tail")),
            "missing_physical_rows_vs_json": missing_physical_vs_json,
            "inventory_status": inventory_status,
            "row_samples": best_rows[:12],
        })
    incomplete = [b for b in blocks if b.get("inventory_status") != "complete"]
    summary = {
        "version": CURRENT_RELEASE,
        "policy": "pdf_first_compact_inventory_for_known_composition_blocks_no_public_value_write",
        "block_count": len(blocks),
        "complete_block_count": sum(1 for b in blocks if b.get("inventory_status") == "complete"),
        "partial_block_count": sum(1 for b in blocks if b.get("inventory_status") == "partial"),
        "not_found_block_count": sum(1 for b in blocks if b.get("inventory_status") == "not_found"),
        "physical_rows_total": sum(int(b.get("physical_row_count") or 0) for b in blocks),
        "rows_with_numeric_tail_total": sum(int(b.get("rows_with_numeric_tail") or 0) for b in blocks),
        "overall_status": "complete" if not incomplete else "needs_review",
    }
    manifest = {"version": CURRENT_RELEASE, "summary": summary, "blocks": blocks[:500], "incomplete_blocks": incomplete[:100]}
    result.setdefault("documento_evidencias", {})["from_scratch_block_inventory"] = manifest
    result.setdefault("meta", {}).setdefault("performance", {})["from_scratch_block_inventory"] = {k: v for k, v in summary.items()}
    return manifest


def build_from_scratch_block_inventory_file(file_path: str, result: Dict[str, Any], options: Dict[str, Any] | None = None) -> Dict[str, Any]:
    from pathlib import Path
    with PdfDocumentSession(Path(file_path).read_bytes()) as sess:
        return build_from_scratch_block_inventory(result, pdf_session=sess, options=options)


def build_from_scratch_block_inventory_bytes(pdf_bytes: bytes, result: Dict[str, Any], options: Dict[str, Any] | None = None) -> Dict[str, Any]:
    with PdfDocumentSession(pdf_bytes) as sess:
        return build_from_scratch_block_inventory(result, pdf_session=sess, options=options)
