from __future__ import annotations

import io
import json
import re
import time
from copy import deepcopy
from hashlib import sha256
from typing import Any, Dict, Iterable, Iterator, List, Tuple

from pypdf import PdfReader

from app.core.pdf_session import PdfDocumentSession
from app.parser.compositions import (
    _detect_comp_header_positions_from_word_lines,
    _extract_structured_text_events_from_page,
    _group_words_by_visual_line,
    _kind_from_structured_label,
    _make_line,
    _normalize_output_tipo,
    _runtime_rules,
    _structured_line_columns,
    _structured_row_is_noise,
)


def _norm_text(value: Any) -> str:
    text = str(value or "").upper()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _norm_token(value: Any) -> str:
    text = _norm_text(value)
    return re.sub(r"[^A-Z0-9]+", "", text)


def _is_sicro_bank(bank: Any) -> bool:
    token = _norm_token(bank)
    return token.startswith("SICRO")


def _short_snippet(value: Any, *, limit: int = 120) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _hash_bytes(pdf_bytes: bytes) -> str:
    return sha256(pdf_bytes or b"").hexdigest()


def _line_vertical_bounds(line_words: List[dict]) -> Tuple[float, float]:
    tops = [float(word.get("top", 0) or 0) for word in line_words if word]
    bottoms = [float(word.get("bottom", word.get("top", 0)) or 0) for word in line_words if word]
    if not tops:
        return 0.0, 0.0
    return min(tops), max(bottoms or tops)


def _header_columns_snapshot(header: dict) -> dict:
    columns: Dict[str, List[float | None]] = {}
    for col in list(header.get("columns") or []):
        key = str(col.get("key") or "").strip()
        if not key:
            continue
        left = col.get("left")
        right = col.get("right")
        x = col.get("x")
        left_val = float(left if left is not None else x if x is not None else 0)
        right_val = float(right) if right is not None else None
        columns[key] = [left_val, right_val]
    return columns


def _candidate_from_structured_acc(page_no: int, table_id: str, current: dict, runtime: dict) -> dict | None:
    label = _clean_text(" ".join(current.get("label_parts", []) or []))
    kind = _kind_from_structured_label(label, runtime=runtime)
    code = _clean_text(current.get("codigo", ""))
    bank = _clean_text(current.get("banco", ""))
    if not kind or not code or not bank:
        return None
    desc = _clean_text(" ".join(current.get("descricao_parts", []) or []))
    tipo_raw = _clean_text(" ".join(current.get("tipo_parts", []) or []))
    cells = [
        label,
        code,
        bank,
        desc,
        tipo_raw,
        _clean_text(current.get("und", "")),
        _clean_text(current.get("quant", "")),
        _clean_text(current.get("valor", "")),
        _clean_text(current.get("total", "")),
    ]
    line, _ = _make_line(cells, runtime=runtime, kind=kind)
    tipo = _normalize_output_tipo(tipo_raw or str(line.tipo or ""), bank=str(line.banco or line.banco_coluna or ""))
    return {
        "page_no": page_no,
        "table_id": table_id,
        "codigo": str(line.codigo or "").strip(),
        "banco": str(line.banco or line.banco_coluna or "").strip(),
        "natureza": str(line.natureza or "").strip(),
        "tipo": tipo,
        "descricao": str(line.descricao or "").strip(),
        "und": str(line.und or "").strip(),
        "score_desc": _norm_token(line.descricao or ""),
        "y_top": float(current.get("y_top", 0) or 0),
        "y_bottom": float(current.get("y_bottom", 0) or 0),
    }


def _collect_geometric_candidates_by_page(pdf_bytes: bytes, pages: Iterable[int], config_all: dict | None = None) -> tuple[Dict[int, List[dict]], Dict[str, dict]]:
    runtime = _runtime_rules(config_all or {})
    out: Dict[int, List[dict]] = {}
    tables: Dict[str, dict] = {}
    unique_pages = sorted({int(p) for p in pages if int(p) > 0})
    if not unique_pages:
        return out, tables
    with PdfDocumentSession(pdf_bytes) as session:
        for page_no in unique_pages:
            words = session.get_words(page_no)
            if not words:
                continue
            lines = _group_words_by_visual_line(words)
            header = _detect_comp_header_positions_from_word_lines(lines, runtime=runtime)
            if not header:
                continue
            table_id = f"tbl_{page_no}_0"
            tables[table_id] = {
                "table_id": table_id,
                "page_no": page_no,
                "columns": _header_columns_snapshot(header),
                "header_line_index": int(header.get("line_index", -1) or -1),
            }
            current: dict | None = None
            page_candidates: List[dict] = []
            for line_words in lines[int(header.get("line_index", -1) or -1) + 1:]:
                cols = _structured_line_columns(line_words, header)
                joined = _clean_text(" ".join(v for v in cols.values() if v))
                if not joined:
                    continue
                if _structured_row_is_noise(cols, dynamic_markers=[]):
                    continue
                has_code_bank = bool(cols.get("codigo") and cols.get("banco"))
                kind = _kind_from_structured_label(cols.get("label", ""), runtime=runtime)
                starts_row = has_code_bank and bool(kind)
                y_top, y_bottom = _line_vertical_bounds(line_words)
                if starts_row:
                    if current:
                        candidate = _candidate_from_structured_acc(page_no, table_id, current, runtime)
                        if candidate:
                            page_candidates.append(candidate)
                    current = {
                        "label_parts": [cols.get("label", "")],
                        "codigo": cols.get("codigo", ""),
                        "banco": cols.get("banco", ""),
                        "descricao_parts": [cols.get("descricao", "")] if cols.get("descricao") else [],
                        "tipo_parts": [cols.get("tipo", "")] if cols.get("tipo") else [],
                        "und": cols.get("und", ""),
                        "quant": cols.get("quant", ""),
                        "valor": cols.get("valor", ""),
                        "total": cols.get("total", ""),
                        "y_top": y_top,
                        "y_bottom": y_bottom,
                    }
                    continue
                if current is None:
                    continue
                if cols.get("codigo") or cols.get("banco"):
                    candidate = _candidate_from_structured_acc(page_no, table_id, current, runtime)
                    if candidate:
                        page_candidates.append(candidate)
                    current = None
                    continue
                continuation_payload = cols.get("descricao") or cols.get("tipo") or cols.get("label")
                if not continuation_payload:
                    continue
                if cols.get("label"):
                    current.setdefault("label_parts", []).append(cols.get("label", ""))
                if cols.get("descricao"):
                    current.setdefault("descricao_parts", []).append(cols.get("descricao", ""))
                if cols.get("tipo"):
                    current.setdefault("tipo_parts", []).append(cols.get("tipo", ""))
                current["y_top"] = min(float(current.get("y_top", y_top) or y_top), y_top)
                current["y_bottom"] = max(float(current.get("y_bottom", y_bottom) or y_bottom), y_bottom)
            if current:
                candidate = _candidate_from_structured_acc(page_no, table_id, current, runtime)
                if candidate:
                    page_candidates.append(candidate)
            out[page_no] = page_candidates
    return out, tables


def _match_pending_row_support(pending_row: dict, candidates: List[dict]) -> dict | None:
    code = str(pending_row.get("codigo") or "").strip().upper()
    banco = str(pending_row.get("banco") or "").strip().upper()
    natureza = str(pending_row.get("natureza") or "").strip().upper()
    und = str(pending_row.get("und") or "").strip().upper()
    desc = _norm_token(pending_row.get("desc_snippet") or "")
    filtered = [c for c in candidates if str(c.get("codigo") or "").strip().upper() == code]
    if banco:
        by_bank = [c for c in filtered if str(c.get("banco") or "").strip().upper() == banco]
        if by_bank:
            filtered = by_bank
    if natureza:
        by_nat = [c for c in filtered if str(c.get("natureza") or "").strip().upper() == natureza]
        if by_nat:
            filtered = by_nat
    if und:
        by_und = [c for c in filtered if str(c.get("und") or "").strip().upper() == und]
        if by_und:
            filtered = by_und
    if desc:
        by_desc = [c for c in filtered if desc[:24] and desc[:24] in str(c.get("score_desc") or "")]
        if by_desc:
            filtered = by_desc
    if not filtered:
        return None
    filtered.sort(key=lambda item: (0 if item.get("tipo") else 1, -(len(str(item.get("score_desc") or ""))), float(item.get("y_top") or 0)))
    return filtered[0]


def _build_tipo_support(*, pdf_bytes: bytes, manifest: dict, config_all: dict | None = None) -> dict:
    pending_rows = [row for row in (manifest.get("pending_rows") or []) if isinstance(row, dict)]
    if not pending_rows:
        return {"tables": {}, "rows": {}}
    pages = sorted({int(row.get("page_hint") or 0) for row in pending_rows if int(row.get("page_hint") or 0) > 0} | {int(p) for p in (manifest.get("pending_pages") or []) if int(p) > 0})
    try:
        geometric_by_page, tables = _collect_geometric_candidates_by_page(pdf_bytes, pages, config_all=config_all)
    except Exception:
        return {"tables": {}, "rows": {}}
    if not geometric_by_page:
        return {"tables": {}, "rows": {}}
    block_page_map = {str(block.get("block_uid") or ""): [int(block.get("page_start") or 0), int(block.get("page_end") or 0)] for block in (manifest.get("pending_blocks") or []) if isinstance(block, dict)}
    row_support: Dict[str, dict] = {}
    used_table_ids: set[str] = set()
    for row in pending_rows:
        candidate_pages: List[int] = []
        page_hint = int(row.get("page_hint") or 0)
        if page_hint > 0:
            candidate_pages.append(page_hint)
        block_pages = block_page_map.get(str(row.get("block_uid") or ""), [])
        for page_val in block_pages:
            if page_val > 0 and page_val not in candidate_pages:
                candidate_pages.append(page_val)
        if not candidate_pages:
            candidate_pages = pages
        found = None
        for page_no in candidate_pages:
            found = _match_pending_row_support(row, geometric_by_page.get(page_no) or [])
            if found:
                break
        if not found:
            continue
        row_uid = str(row.get("row_uid") or "")
        if not row_uid:
            continue
        row_support[row_uid] = {
            "table_id": found.get("table_id"),
            "page_no": found.get("page_no"),
            "y_top": found.get("y_top"),
            "y_bottom": found.get("y_bottom"),
            "initial_tipo_guess": found.get("tipo") or "",
        }
        if found.get("table_id"):
            used_table_ids.add(str(found.get("table_id")))
    return {
        "tables": {table_id: clone for table_id, clone in tables.items() if table_id in used_table_ids},
        "rows": row_support,
    }


def _iter_block_lines(result: dict) -> Iterator[Tuple[str, str, dict, str, int]]:
    composicoes = (result or {}).get("composicoes") or {}
    for collection_name in ("principais", "auxiliares_globais"):
        blocks = composicoes.get(collection_name) or {}
        if not isinstance(blocks, dict):
            continue
        for block_key, block in blocks.items():
            if not isinstance(block, dict):
                continue
            principal = block.get("principal")
            if isinstance(principal, dict):
                yield collection_name, block_key, principal, "principal", 0
            for idx, line in enumerate(block.get("composicoes_auxiliares") or []):
                if isinstance(line, dict):
                    yield collection_name, block_key, line, "composicao_auxiliar", idx
            for idx, line in enumerate(block.get("insumos") or []):
                if isinstance(line, dict):
                    yield collection_name, block_key, line, "insumo", idx


def _build_row_uid(block_uid: str, kind: str, row_index: int, line: dict) -> str:
    codigo = _norm_token(line.get("codigo") or "SEM_CODIGO") or "SEM_CODIGO"
    banco = _norm_token(line.get("banco") or "SEM_BANCO") or "SEM_BANCO"
    return f"{block_uid}:{kind}:{row_index}:{codigo}|{banco}"


def _composition_page_texts(pdf_bytes: bytes, ranges: dict | None) -> Dict[int, str]:
    comp_range = ((ranges or {}).get("composicoes") or (0, 0))
    if not comp_range or comp_range == (0, 0):
        return {}
    start, end = comp_range
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        page_count = len(reader.pages)
    except Exception:
        return {}
    if start < 1 or start > page_count:
        return {}
    end = min(end, page_count)
    out: Dict[int, str] = {}
    for page_no in range(start, end + 1):
        try:
            text = reader.pages[page_no - 1].extract_text() or ""
        except Exception:
            text = ""
        out[page_no] = _norm_text(text)
    return out


def _infer_block_page(block: dict, block_key: str, page_texts: Dict[int, str], comp_range: tuple[int, int] | None) -> int | None:
    principal = (block or {}).get("principal") or {}
    code = _norm_token(principal.get("codigo") or block_key.split("|")[0])
    bank = _norm_token(principal.get("banco") or (block_key.split("|")[1] if "|" in block_key else ""))
    desc = _norm_token(_short_snippet(principal.get("descricao") or "", limit=36))
    candidates: List[int] = []
    for page_no, text in page_texts.items():
        has_code = bool(code and code in _norm_token(text))
        has_bank = bool(bank and bank in _norm_token(text))
        has_desc = bool(desc and desc[:16] and desc[:16] in _norm_token(text))
        if has_code and has_bank:
            return page_no
        if has_code and has_desc:
            candidates.append(page_no)
        elif has_code:
            candidates.append(page_no)
    if candidates:
        return min(candidates)
    if comp_range and comp_range != (0, 0):
        return int(comp_range[0])
    return None


def prepare_result_for_deferred_tipo(
    result: dict,
    *,
    pdf_bytes: bytes,
    ranges: dict,
    parser_version: str,
    mode: str,
    config_all: dict | None = None,
) -> dict:
    """Converte o resultado em JSON base v53, deixando `tipo` pendente para a API e gerando um manifest enxuto."""
    payload = deepcopy(result)
    meta = payload.setdefault("meta", {})
    page_texts = _composition_page_texts(pdf_bytes, ranges)
    comp_range = (ranges or {}).get("composicoes") or (0, 0)
    pending_pages: set[int] = set()
    pending_blocks: Dict[str, dict] = {}
    pending_rows: List[dict] = []
    eligible_rows = 0
    not_applicable_rows = 0

    block_page_map: Dict[str, int | None] = {}
    composicoes = (payload.get("composicoes") or {})
    for collection_name in ("principais", "auxiliares_globais"):
        blocks = composicoes.get(collection_name) or {}
        if not isinstance(blocks, dict):
            continue
        for block_key, block in blocks.items():
            if not isinstance(block, dict):
                continue
            block_uid = f"block:{collection_name}:{block_key}"
            block_page_map[block_uid] = _infer_block_page(block, block_key, page_texts, comp_range)

    for collection_name, block_key, line, kind, row_index in _iter_block_lines(payload):
        block_uid = f"block:{collection_name}:{block_key}"
        page_hint = block_page_map.get(block_uid)
        row_uid = _build_row_uid(block_uid, kind, row_index, line)
        line["row_uid"] = row_uid
        line["block_uid"] = block_uid
        line["page_hint"] = page_hint
        line["row_index_in_block"] = row_index
        bank = line.get("banco") or line.get("banco_coluna") or ""
        if _is_sicro_bank(bank):
            line["tipo"] = ""
            line["tipo_status"] = "not_applicable"
            not_applicable_rows += 1
            continue

        line["tipo"] = None
        line["tipo_status"] = "pending"
        eligible_rows += 1
        if block_uid not in pending_blocks:
            pending_blocks[block_uid] = {
                "block_uid": block_uid,
                "collection": collection_name,
                "block_key": block_key,
                "page_start": page_hint,
                "page_end": page_hint,
                "banco": str((((composicoes.get(collection_name) or {}).get(block_key) or {}).get("principal") or {}).get("banco") or "").strip(),
                "principal_codigo": str((((composicoes.get(collection_name) or {}).get(block_key) or {}).get("principal") or {}).get("codigo") or "").strip(),
            }
        if page_hint:
            pending_pages.add(page_hint)
        pending_rows.append({
            "row_uid": row_uid,
            "block_uid": block_uid,
            "collection": collection_name,
            "block_key": block_key,
            "page_hint": page_hint,
            "row_index_in_block": row_index,
            "codigo": str(line.get("codigo") or "").strip(),
            "banco": str(bank or "").strip(),
            "natureza": str(line.get("natureza") or "").strip(),
            "desc_snippet": _short_snippet(line.get("descricao") or ""),
            "und": str(line.get("und") or "").strip(),
            "tipo_status": "pending",
        })

    manifest = {
        "document_id": meta.get("request_id") or "",
        "parser_version": parser_version,
        "source_hash": _hash_bytes(pdf_bytes),
        "ranges": {
            "orcamento_inicio": int(((ranges or {}).get("orcamento") or (0, 0))[0] or 0),
            "orcamento_fim": int(((ranges or {}).get("orcamento") or (0, 0))[1] or 0),
            "composicoes_inicio": int((comp_range or (0, 0))[0] or 0),
            "composicoes_fim": int((comp_range or (0, 0))[1] or 0),
        },
        "pending_pages": sorted(p for p in pending_pages if p),
        "pending_blocks": list(pending_blocks.values()),
        "pending_rows": pending_rows,
    }

    tipo_support = _build_tipo_support(pdf_bytes=pdf_bytes, manifest=manifest, config_all=config_all)
    meta["tipo_enrichment"] = {
        "status": "pending" if pending_rows else "complete",
        "mode": "api_patch",
        "job_id": None,
        "job_revision": 1,
        "eligible_rows": eligible_rows,
        "filled_rows": 0,
        "failed_rows": 0,
        "not_applicable_rows": not_applicable_rows,
        "source_hash": manifest["source_hash"],
        "api_version": parser_version,
        "support_rows": len((tipo_support or {}).get("rows") or {}),
        "support_tables": len((tipo_support or {}).get("tables") or {}),
    }
    payload["meta"] = meta
    payload["tipo_manifest"] = manifest
    if (tipo_support or {}).get("rows"):
        payload["_tipo_support"] = tipo_support
    return payload


class TipoEnrichmentError(RuntimeError):
    def __init__(self, message: str, *, code: str = "tipo_enrichment_error", detail: Any = None):
        super().__init__(message)
        self.code = code
        self.detail = detail


def _candidate_from_event(page_no: int, event: dict, runtime: dict) -> dict | None:
    if not isinstance(event, dict) or event.get("event") != "row":
        return None
    cells = list(event.get("cells") or [])
    if not cells:
        return None
    try:
        line, _ = _make_line(cells, runtime=runtime, kind=str(event.get("kind") or ""))
    except Exception:
        return None
    tipo = str(line.tipo or "").strip()
    if not tipo:
        return None
    return {
        "page_no": page_no,
        "codigo": str(line.codigo or "").strip(),
        "banco": str(line.banco or line.banco_coluna or "").strip(),
        "natureza": str(line.natureza or "").strip(),
        "tipo": tipo,
        "descricao": str(line.descricao or "").strip(),
        "und": str(line.und or "").strip(),
        "score_desc": _norm_token(line.descricao or ""),
    }


def _collect_candidates_by_page(pdf_bytes: bytes, pages: Iterable[int], config_all: dict | None = None) -> Dict[int, List[dict]]:
    runtime = _runtime_rules(config_all or {})
    out: Dict[int, List[dict]] = {}
    unique_pages = sorted({int(p) for p in pages if int(p) > 0})
    if not unique_pages:
        return out
    with PdfDocumentSession(pdf_bytes) as session:
        for page_no in unique_pages:
            events = _extract_structured_text_events_from_page(page_no, pdf_session=session, runtime=runtime, dynamic_markers=[])
            candidates: List[dict] = []
            for event in events:
                candidate = _candidate_from_event(page_no, event, runtime)
                if candidate:
                    candidates.append(candidate)
            out[page_no] = candidates
    return out


def _match_pending_row(pending_row: dict, candidates: List[dict]) -> dict | None:
    code = str(pending_row.get("codigo") or "").strip().upper()
    banco = str(pending_row.get("banco") or "").strip().upper()
    natureza = str(pending_row.get("natureza") or "").strip().upper()
    und = str(pending_row.get("und") or "").strip().upper()
    desc = _norm_token(pending_row.get("desc_snippet") or "")
    filtered = [c for c in candidates if str(c.get("codigo") or "").strip().upper() == code]
    if banco:
        by_bank = [c for c in filtered if str(c.get("banco") or "").strip().upper() == banco]
        if by_bank:
            filtered = by_bank
    if natureza:
        by_nat = [c for c in filtered if str(c.get("natureza") or "").strip().upper() == natureza]
        if by_nat:
            filtered = by_nat
    if und:
        by_und = [c for c in filtered if str(c.get("und") or "").strip().upper() == und]
        if by_und:
            filtered = by_und
    if desc:
        by_desc = [c for c in filtered if desc[:24] and desc[:24] in c.get("score_desc", "")]
        if by_desc:
            filtered = by_desc
    if not filtered:
        return None
    filtered.sort(key=lambda item: len(str(item.get("tipo") or "")), reverse=True)
    return filtered[0]


def _extract_tipo_text_from_support(*, pdf_bytes: bytes, support: dict, config_all: dict | None = None) -> Dict[str, dict]:
    tables = (support or {}).get("tables") or {}
    rows = (support or {}).get("rows") or {}
    if not tables or not rows:
        return {}
    results: Dict[str, dict] = {}
    with PdfDocumentSession(pdf_bytes) as session:
        page_words_cache: Dict[int, List[dict]] = {}
        page_frag_cache: Dict[int, List[dict]] = {}
        for row_uid, row_meta in rows.items():
            if not isinstance(row_meta, dict):
                continue
            table = tables.get(str(row_meta.get("table_id") or "")) or {}
            tipo_bounds = ((table.get("columns") or {}).get("tipo") or [])
            if len(tipo_bounds) < 2:
                continue
            x_left = float(tipo_bounds[0] or 0)
            x_right = tipo_bounds[1]
            if x_right is None:
                continue
            x_right = float(x_right)
            if x_right <= x_left:
                continue
            page_no = int(row_meta.get("page_no") or table.get("page_no") or 0)
            if page_no <= 0:
                continue
            y_top = float(row_meta.get("y_top") or 0)
            y_bottom = float(row_meta.get("y_bottom") or 0)
            if y_bottom <= y_top:
                continue
            tokens: List[Tuple[float, float, str]] = []
            words = page_words_cache.get(page_no)
            if words is None:
                words = session.get_words(page_no) or []
                page_words_cache[page_no] = words
            for word in words:
                text = _clean_text(word.get("text", ""))
                if not text:
                    continue
                wx0 = float(word.get("x0", 0) or 0)
                wx1 = float(word.get("x1", wx0) or wx0)
                wtop = float(word.get("top", 0) or 0)
                wbottom = float(word.get("bottom", wtop) or wtop)
                if wx1 <= x_left or wx0 >= x_right:
                    continue
                if wbottom < (y_top - 1.5) or wtop > (y_bottom + 1.5):
                    continue
                tokens.append((wtop, wx0, text))
            if not tokens:
                frags = page_frag_cache.get(page_no)
                if frags is None:
                    frags = session.get_text_fragments(page_no) or []
                    page_frag_cache[page_no] = frags
                for frag in frags:
                    text = _clean_text(frag.get("text", ""))
                    if not text:
                        continue
                    fx0 = float(frag.get("x0", 0) or 0)
                    ftop = float(frag.get("top", 0) or 0)
                    if fx0 < x_left or fx0 >= x_right:
                        continue
                    if ftop < (y_top - 1.5) or ftop > (y_bottom + 1.5):
                        continue
                    tokens.append((ftop, fx0, text))
            if not tokens:
                initial_guess = _normalize_output_tipo(str(row_meta.get("initial_tipo_guess") or ""), bank="")
                if initial_guess:
                    results[str(row_uid)] = {"tipo": initial_guess, "page_no": page_no, "support_source": "initial_guess"}
                continue
            tokens.sort(key=lambda item: (item[0], item[1]))
            tipo_text = _normalize_output_tipo(" ".join(text for _, _, text in tokens), bank="")
            if not tipo_text:
                initial_guess = _normalize_output_tipo(str(row_meta.get("initial_tipo_guess") or ""), bank="")
                if initial_guess:
                    tipo_text = initial_guess
            if tipo_text:
                results[str(row_uid)] = {"tipo": tipo_text, "page_no": page_no, "support_source": "tipo_support"}
    return results


def build_tipo_patch(
    *,
    pdf_bytes: bytes,
    manifest: dict,
    config_all: dict | None = None,
) -> dict:
    if not isinstance(manifest, dict):
        raise TipoEnrichmentError("Manifest de enrichment inválido.", code="invalid_manifest")

    started = time.perf_counter()
    pending_rows = [row for row in (manifest.get("pending_rows") or []) if isinstance(row, dict)]
    eligible_pages = [int(p) for p in (manifest.get("pending_pages") or []) if int(p) > 0]
    pages_by_row = {int(row.get("page_hint") or 0) for row in pending_rows if int(row.get("page_hint") or 0) > 0}
    pages = sorted(set(eligible_pages) | pages_by_row)
    if not pages and pending_rows:
        comp_inicio = int(((manifest.get("ranges") or {}).get("composicoes_inicio") or 0))
        comp_fim = int(((manifest.get("ranges") or {}).get("composicoes_fim") or 0))
        if comp_inicio and comp_fim and comp_fim >= comp_inicio:
            pages = list(range(comp_inicio, comp_fim + 1))

    candidates_by_page = _collect_candidates_by_page(pdf_bytes, pages, config_all=config_all)
    support_results = _extract_tipo_text_from_support(pdf_bytes=pdf_bytes, support=manifest.get("tipo_support") or {}, config_all=config_all)

    updates: List[dict] = []
    failed_rows = 0
    filled_rows = 0
    support_filled_rows = 0
    fallback_filled_rows = 0
    for row in pending_rows:
        row_uid = str(row.get("row_uid") or "")
        support_hit = support_results.get(row_uid)
        if support_hit:
            filled_rows += 1
            support_filled_rows += 1
            updates.append({
                "row_uid": row_uid,
                "tipo": support_hit.get("tipo") or "",
                "tipo_status": "filled",
                "page_no": support_hit.get("page_no"),
                "resolution": support_hit.get("support_source") or "tipo_support",
            })
            continue
        candidate_pages: List[int] = []
        if int(row.get("page_hint") or 0) > 0:
            candidate_pages.append(int(row.get("page_hint") or 0))
        block_uid = row.get("block_uid")
        for block in (manifest.get("pending_blocks") or []):
            if not isinstance(block, dict) or block.get("block_uid") != block_uid:
                continue
            for key in ("page_start", "page_end"):
                page_val = int(block.get(key) or 0)
                if page_val > 0 and page_val not in candidate_pages:
                    candidate_pages.append(page_val)
        if not candidate_pages:
            candidate_pages = pages
        found = None
        for page_no in candidate_pages:
            found = _match_pending_row(row, candidates_by_page.get(page_no) or [])
            if found:
                break
        if found:
            filled_rows += 1
            fallback_filled_rows += 1
            updates.append({
                "row_uid": row.get("row_uid"),
                "tipo": found.get("tipo") or "",
                "tipo_status": "filled",
                "page_no": found.get("page_no"),
            })
        else:
            failed_rows += 1
            updates.append({
                "row_uid": row.get("row_uid"),
                "tipo": None,
                "tipo_status": "failed",
            })

    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    status = "complete" if failed_rows == 0 else ("partial" if filled_rows else "failed")
    return {
        "status": status,
        "updates": updates,
        "metrics": {
            "tipo_enrichment_ms": elapsed_ms,
            "rows_attempted": len(pending_rows),
            "rows_filled": filled_rows,
            "rows_failed": failed_rows,
            "rows_filled_via_support": support_filled_rows,
            "rows_filled_via_fallback": fallback_filled_rows,
            "pages_scanned": len(pages),
            "blocks_scanned": len(manifest.get("pending_blocks") or []),
            "support_rows_available": len(((manifest.get("tipo_support") or {}).get("rows") or {})),
            "support_tables_available": len(((manifest.get("tipo_support") or {}).get("tables") or {})),
        },
    }


def apply_tipo_patch(base_payload: dict, patch_payload: dict) -> dict:
    payload = deepcopy(base_payload)
    updates = {str(item.get("row_uid") or ""): item for item in (patch_payload.get("updates") or []) if isinstance(item, dict)}
    if not updates:
        return payload
    for _collection_name, _block_key, line, _kind, _row_index in _iter_block_lines(payload):
        row_uid = str(line.get("row_uid") or "")
        if not row_uid or row_uid not in updates:
            continue
        update = updates[row_uid]
        line["tipo"] = update.get("tipo")
        line["tipo_status"] = update.get("tipo_status") or line.get("tipo_status") or "pending"

    filled_rows = 0
    failed_rows = 0
    pending_rows = 0
    not_applicable_rows = 0
    for _collection_name, _block_key, line, _kind, _row_index in _iter_block_lines(payload):
        status = str(line.get("tipo_status") or "")
        if status == "filled":
            filled_rows += 1
        elif status == "failed":
            failed_rows += 1
        elif status == "pending":
            pending_rows += 1
        elif status == "not_applicable":
            not_applicable_rows += 1

    meta = payload.setdefault("meta", {})
    tipo_meta = dict(meta.get("tipo_enrichment") or {})
    tipo_meta["filled_rows"] = filled_rows
    tipo_meta["failed_rows"] = failed_rows
    tipo_meta["not_applicable_rows"] = not_applicable_rows
    tipo_meta["status"] = "complete" if pending_rows == 0 and failed_rows == 0 else ("partial" if filled_rows else "failed")
    metrics = dict((patch_payload.get("metrics") or {}))
    if metrics:
        tipo_meta["metrics"] = metrics
    meta["tipo_enrichment"] = tipo_meta
    payload["meta"] = meta
    return payload
