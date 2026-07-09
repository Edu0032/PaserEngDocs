from __future__ import annotations

"""Physical Evidence Index (v61.0.42).

Builds a single PDF-backed evidence index by codigo+banco.  This is deliberately
separate from the extracted Document Evidence Index: the physical index opens the
PDF once, reads word geometry, groups physical lines, and records candidates that
can later be merged into the logical evidence index used by the closure engine.

The module is Pyodide/PyMuPDF friendly: it imports fitz lazily and degrades to an
empty index if the PDF cannot be opened.  SICRO is not revalidated here; SICRO
blocks remain under the native ``sicro_only`` engine.  This index only provides
physical evidence candidates for fields that the main closure can safely consume.
"""

import copy
import re
import unicodedata
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from app.parser.raw_occurrence_context_parser import parse_raw_occurrence_context
from app.parser.document_section_classifier import classify_document_section, section_evidence_policy, summarize_section_counts

VERSION = "v61.0.75-correction-output-contract-and-review-index"

_NUMERIC_RE = re.compile(r"(?<![A-Za-z0-9])(?:\d{1,3}(?:\.\d{3})+|\d+),\d{1,7}(?![A-Za-z0-9])")
_UNIT_CANON = {
    "M": "m",
    "M2": "m²",
    "M²": "m²",
    "M3": "m³",
    "M³": "m³",
    "CM": "cm",
    "MM": "mm",
    "KM": "km",
    "UN": "un",
    "UND": "und",
    "UNID": "und",
    "H": "h",
    "HH": "h",
    "KG": "kg",
    "T": "t",
    "TON": "t",
    "L": "l",
    "LITRO": "l",
    "MÊS": "mês",
    "MES": "mês",
    "VB": "vb",
    "CJ": "cj",
    "PAR": "par",
    "T.KM": "t.km",
    "TKM": "t.km",
    "M3.KM": "m³.km",
    "M³.KM": "m³.km",
}
_STOP = {"SINAPI", "SICRO", "PROPRIO", "PRÓPRIO", "CPU", "COMPOSICAO", "COMPOSIÇÃO", "AUXILIAR", "INSUMO"}


def _clean(value: Any) -> str:
    return " ".join(str(value or "").replace("\u00a0", " ").split())


def _strip_accents(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def _norm(value: Any) -> str:
    return _strip_accents(_clean(value)).upper()


def _bank_norm(value: Any) -> str:
    text = _norm(value)
    return "PROPRIO" if text in {"PROPRIO", "PROPRIO"} else text


def code_bank_key(codigo: Any, banco: Any) -> str:
    code = _clean(codigo)
    bank = _bank_norm(banco)
    return f"{code}|{bank}" if code else ""


def _identity_pairs_from_final(final_result: Dict[str, Any]) -> List[Dict[str, Any]]:
    identities: Dict[str, Dict[str, Any]] = {}

    def add(codigo: Any, banco: Any, *, family: str = "", path: Sequence[Any] | None = None, fields: Sequence[str] | None = None) -> None:
        key = code_bank_key(codigo, banco)
        if not key:
            return
        bucket = identities.setdefault(key, {"key": key, "codigo": _clean(codigo), "banco": _clean(banco), "families": set(), "paths": [], "requested_fields": set()})
        if family:
            bucket["families"].add(family)
        if path is not None and len(bucket["paths"]) < 20:
            bucket["paths"].append(list(path))
        for f in fields or []:
            bucket["requested_fields"].add(str(f))

    def walk_budget(nodes: Any, base: List[Any]) -> None:
        if not isinstance(nodes, list):
            return
        for idx, node in enumerate(nodes):
            if not isinstance(node, dict):
                continue
            path = base + [idx]
            if node.get("codigo"):
                add(node.get("codigo"), node.get("fonte") or node.get("banco"), family="budget", path=path, fields=["especificacao", "und", "quant", "custo_unitario_com_bdi", "custo_parcial"])
            walk_budget(node.get("filhos"), path + ["filhos"])

    walk_budget(((final_result.get("orcamento_sintetico") or {}).get("itens_raiz") or []), ["orcamento_sintetico", "itens_raiz"])
    comp = final_result.get("composicoes") if isinstance(final_result.get("composicoes"), dict) else {}
    sources: List[Tuple[str, str, Dict[str, Any]]] = []
    if isinstance(comp.get("sinapi_like"), dict) or isinstance(comp.get("sicro"), dict):
        for family in ("sinapi_like", "sicro"):
            fam = comp.get(family) if isinstance(comp.get(family), dict) else {}
            for collection in ("principais", "auxiliares_globais"):
                blocks = fam.get(collection) if isinstance(fam, dict) else None
                if isinstance(blocks, dict):
                    sources.append((family, collection, blocks))
    else:
        for collection in ("principais", "auxiliares_globais"):
            blocks = comp.get(collection)
            if isinstance(blocks, dict):
                sources.append(("sinapi_like", collection, blocks))
    for family, collection, blocks in sources:
        for key, block in (blocks or {}).items():
            if not isinstance(block, dict):
                continue
            principal = block.get("principal") if isinstance(block.get("principal"), dict) else {}
            if principal:
                code = principal.get("codigo") or (str(key).split("|", 1)[0] if "|" in str(key) else "")
                bank = principal.get("banco") or principal.get("fonte") or (str(key).split("|", 1)[1] if "|" in str(key) else "")
                add(code, bank, family=family, path=["composicoes", family, collection, key, "principal"], fields=["descricao", "und", "quant", "valor_unit", "total"])
            if family == "sinapi_like":
                for group in ("composicoes_auxiliares", "insumos", "materiais", "mao_obra", "equipamentos", "auxiliares"):
                    rows = block.get(group) if isinstance(block.get(group), list) else []
                    for idx, row in enumerate(rows):
                        if not isinstance(row, dict):
                            continue
                        add(row.get("codigo"), row.get("banco") or row.get("fonte"), family=family, path=["composicoes", family, collection, key, group, idx], fields=["descricao", "und", "quant", "valor_unit", "total"])
    out: List[Dict[str, Any]] = []
    for bucket in identities.values():
        out.append({**bucket, "families": sorted(bucket["families"]), "requested_fields": sorted(bucket["requested_fields"])})
    return out


def _pages_from_ranges(options: Dict[str, Any], final_result: Dict[str, Any]) -> List[int]:
    ranges = options.get("ranges") or (options.get("parser_contract") or {}).get("ranges") or ((final_result.get("meta") or {}).get("input_metadata") or {}).get("ranges") or {}
    pages: List[int] = []

    def add_range(r: Any) -> None:
        if not r:
            return
        if isinstance(r, (list, tuple)) and len(r) >= 2:
            start, end = int(r[0] or 0), int(r[1] or 0)
        elif isinstance(r, dict):
            start = int(r.get("start") or r.get("inicio") or r.get(0) or 0)
            end = int(r.get("end") or r.get("fim") or r.get(1) or 0)
        else:
            return
        if start > 0 and end >= start:
            pages.extend(range(start, end + 1))

    add_range(ranges.get("budget") or ranges.get("orcamento"))
    add_range(ranges.get("compositions") or ranges.get("composicoes"))
    return sorted(set(pages))


def _group_words_into_lines(words: List[Tuple[float, float, float, float, str, int, int, int]], *, y_tol: float = 3.5) -> List[Dict[str, Any]]:
    lines: List[Dict[str, Any]] = []
    for w in sorted(words, key=lambda x: (round(float(x[1]) / y_tol), float(x[0]))):
        x0, y0, x1, y1, text, block_no, line_no, word_no = w[:8]
        if not _clean(text):
            continue
        placed = False
        for line in lines:
            if abs(float(y0) - float(line["y0"])) <= y_tol:
                line["words"].append({"x0": x0, "y0": y0, "x1": x1, "y1": y1, "text": _clean(text)})
                line["y0"] = min(line["y0"], y0)
                line["y1"] = max(line["y1"], y1)
                line["x0"] = min(line["x0"], x0)
                line["x1"] = max(line["x1"], x1)
                placed = True
                break
        if not placed:
            lines.append({"x0": x0, "y0": y0, "x1": x1, "y1": y1, "words": [{"x0": x0, "y0": y0, "x1": x1, "y1": y1, "text": _clean(text)}]})
    for line in lines:
        line["words"] = sorted(line["words"], key=lambda d: float(d.get("x0") or 0.0))
        line["text"] = _clean(" ".join(w["text"] for w in line["words"]))
        line["bbox"] = [line["x0"], line["y0"], line["x1"], line["y1"]]
    return sorted(lines, key=lambda d: (float(d.get("y0") or 0.0), float(d.get("x0") or 0.0)))


def _unit_value(token: str) -> str:
    raw = _clean(token).replace("²", "2").replace("³", "3")
    norm = _norm(raw).strip(".,;:()[]")
    original_norm = _norm(token).strip(".,;:()[]")
    return _UNIT_CANON.get(original_norm) or _UNIT_CANON.get(norm) or ""


def _numeric_tokens(words: List[Dict[str, Any]]) -> List[Tuple[int, str]]:
    out: List[Tuple[int, str]] = []
    for idx, w in enumerate(words):
        text = _clean(w.get("text"))
        if _NUMERIC_RE.fullmatch(text):
            out.append((idx, text))
    return out


def _extract_fields_from_line(line: Dict[str, Any], code: str, bank: str, families: Sequence[str]) -> Dict[str, Any]:
    words = line.get("words") or []
    word_texts = [_clean(w.get("text")) for w in words]
    norm_words = [_norm(t) for t in word_texts]
    norm_code = _norm(code)
    norm_bank = _bank_norm(bank)
    code_idx = next((i for i, t in enumerate(norm_words) if t == norm_code or norm_code in t or t in {norm_code.replace(" ", "")}), -1)
    bank_idx = next((i for i, t in enumerate(norm_words) if norm_bank and (t == norm_bank or t.startswith(norm_bank))), -1)
    nums = _numeric_tokens(words)
    first_num_idx = nums[0][0] if nums else len(words)
    unit_idx = -1
    unit = ""
    for i, token in enumerate(word_texts):
        u = _unit_value(token)
        if u and i < first_num_idx:
            unit_idx, unit = i, u
    start = max(code_idx, bank_idx) + 1
    if start <= 0:
        start = code_idx + 1 if code_idx >= 0 else 0
    stop = unit_idx if unit_idx >= 0 else first_num_idx
    desc_tokens = []
    for token in word_texts[start:stop]:
        if _norm(token) in _STOP:
            continue
        if _NUMERIC_RE.fullmatch(token):
            break
        if _unit_value(token):
            break
        desc_tokens.append(token)
    descricao = _clean(" ".join(desc_tokens))
    numeric_values = [v for _idx, v in nums]
    fields: Dict[str, Any] = {}
    if descricao and len(descricao) >= 3:
        fields["descricao"] = descricao
        fields["especificacao"] = descricao
    if unit:
        fields["und"] = unit
    if numeric_values:
        fields["quant"] = numeric_values[0]
    if len(numeric_values) >= 2:
        fields["valor_unit"] = numeric_values[-2] if len(numeric_values) >= 3 else numeric_values[1]
        fields["custo_unitario_com_bdi"] = fields["valor_unit"]
    if len(numeric_values) >= 3:
        fields["total"] = numeric_values[-1]
        fields["custo_parcial"] = numeric_values[-1]
    # Budget lines commonly contain sem_bdi, com_bdi, parcial after quantity.
    if "budget" in set(families) and len(numeric_values) >= 4:
        fields["custo_unitario_sem_bdi"] = numeric_values[-3]
        fields["custo_unitario_com_bdi"] = numeric_values[-2]
        fields["custo_parcial"] = numeric_values[-1]
    return fields


def _key_match(line_text: str, code: str, bank: str) -> bool:
    nline = _norm(line_text)
    ncode = _norm(code)
    nbank = _bank_norm(bank)
    if not ncode or ncode not in nline:
        return False
    if nbank and nbank not in nline:
        # Some PDFs omit the bank in continuation/physical occurrences.  Do not
        # accept these for generic matching because codigo+banco is the id.
        return False
    return True



_ITEM_ID_RE = re.compile(r"^\s*\d+(?:\.\d+)+\s+")
_HEADER_NOISE_RE = re.compile(r"(ITEM\s+C[OÓ]DIGO|C[OÓ]DIGO\s+BANCO\s+DESCRI|ANEXO\s+\d+|DERACRE\s+P[ÁA]GINA)", re.I)


def _line_has_any_identity(line_text: str, identities: Sequence[Dict[str, Any]], *, except_key: str = "") -> bool:
    for ident in identities or []:
        key = str(ident.get("key") or "")
        if except_key and key == except_key:
            continue
        if _key_match(line_text, ident.get("codigo"), ident.get("banco")):
            return True
    return False


def _looks_like_new_item_boundary(line_text: str, identities: Sequence[Dict[str, Any]], *, except_key: str = "") -> bool:
    text = _clean(line_text)
    if not text:
        return False
    if _HEADER_NOISE_RE.search(text):
        return True
    if _line_has_any_identity(text, identities, except_key=except_key):
        return True
    # In DERACRE PDFs the visual row may start with description and the code
    # appears on the following baseline.  A line that starts with another item
    # number/section is a boundary even when the numeric tail is on a neighbour.
    if _ITEM_ID_RE.match(text):
        return True
    return False


def _include_previous_baseline(text: str) -> bool:
    text = _clean(text)
    if not text or _HEADER_NOISE_RE.search(text):
        return False
    if text.upper().startswith("AF_") and len(text) < 18:
        return False
    # Previous baselines are useful when PyMuPDF placed the description+numeric
    # tail slightly above the identity baseline.  Without numbers they are often
    # previous-row continuations, so be conservative.
    return bool(_NUMERIC_RE.search(text))


def _include_following_baseline(text: str) -> bool:
    text = _clean(text)
    if not text or _HEADER_NOISE_RE.search(text):
        return False
    # Following numeric lines are frequently the next row's description+tail.
    # Following non-numeric lines are usually continuations like "FORNECIMENTO E
    # INSTALAÇÃO..." and are safe within the local vertical window.
    return not bool(_NUMERIC_RE.search(text))


def _combined_line_from_words(words: List[Dict[str, Any]]) -> Dict[str, Any]:
    clean_words = [w for w in words if _clean(w.get("text"))]
    # Rebuild a table-like row by column first, vertical second.  This fixes the
    # common case where PyMuPDF splits one visual row into left identity, middle
    # description and right numeric baselines.
    ordered = sorted(clean_words, key=lambda d: (float(d.get("x0") or 0.0), float(d.get("y0") or 0.0)))
    if not ordered:
        return {"words": [], "text": "", "bbox": []}
    x0 = min(float(w.get("x0") or 0.0) for w in ordered)
    y0 = min(float(w.get("y0") or 0.0) for w in ordered)
    x1 = max(float(w.get("x1") or 0.0) for w in ordered)
    y1 = max(float(w.get("y1") or 0.0) for w in ordered)
    return {"x0": x0, "y0": y0, "x1": x1, "y1": y1, "words": ordered, "text": _clean(" ".join(w.get("text") or "" for w in ordered)), "bbox": [x0, y0, x1, y1]}


def _fuse_visual_row(lines: List[Dict[str, Any]], idx: int, identities: Sequence[Dict[str, Any]], ident: Dict[str, Any], *, y_window: float = 8.5) -> Dict[str, Any]:
    """Fuse split baselines belonging to the same visual budget row.

    This is intentionally local and safe: it only uses neighbouring baselines
    within a small vertical window and stops at another code+banco/item boundary.
    It improves DERACRE rows such as ``89446 SINAPI M`` whose description and
    numbers are on adjacent baselines.
    """
    current = lines[idx]
    key = str(ident.get("key") or "")
    y0 = float(current.get("y0") or 0.0)
    y1 = float(current.get("y1") or y0)
    chosen = [current]
    # Previous baselines often contain the description + numeric tail.  Include
    # only one numeric-bearing previous baseline to avoid stealing the previous
    # item's short continuation (for example a lone AF_... line).
    j = idx - 1
    prev_added = 0
    while j >= 0 and prev_added < 1:
        line = lines[j]
        line_text = line.get("text") or ""
        if y0 - float(line.get("y1") or 0.0) > y_window:
            break
        if _looks_like_new_item_boundary(line_text, identities, except_key=key):
            break
        if _include_previous_baseline(line_text):
            chosen.insert(0, line)
            prev_added += 1
        j -= 1
    # Following baselines often contain a non-numeric continuation of the
    # description.  Never include a following numeric-bearing baseline because it
    # is usually the next item's numeric tail in DERACRE PDFs.
    j = idx + 1
    next_added = 0
    while j < len(lines) and next_added < 2:
        line = lines[j]
        line_text = line.get("text") or ""
        if float(line.get("y0") or 0.0) - y1 > y_window:
            break
        if _looks_like_new_item_boundary(line_text, identities, except_key=key):
            break
        if _include_following_baseline(line_text):
            chosen.append(line)
            next_added += 1
        j += 1
    words: List[Dict[str, Any]] = []
    for line in chosen:
        words.extend(line.get("words") or [])
    fused = _combined_line_from_words(words)
    fused["fusion"] = {"source_line_count": len(chosen), "source_line_texts": [c.get("text") for c in chosen[:6]], "method": "local_visual_row_fusion"}
    return fused


def _apply_section_policy_to_fields(fields: Dict[str, Any], raw_context: Dict[str, Any], policy: Dict[str, Any]) -> Dict[str, Any]:
    fields = dict(fields or {})
    section = policy.get("section") or "unknown"
    allowed = set(policy.get("repair_allowed_fields") or [])
    # Calculation memory has dimension/coefficient columns. Treat the last numeric
    # candidate as the measured total quantity for diagnostics, never as price.
    if section == "memoria_calculo":
        nums = list((raw_context or {}).get("fields", {}).get("numeric_candidates") or [])
        for f in ["valor_unit", "total", "custo_unitario_sem_bdi", "custo_unitario_com_bdi", "custo_parcial", "custo_total"]:
            fields.pop(f, None)
        if nums:
            fields["quant"] = nums[-1]
            fields["memoria_quant_total"] = nums[-1]
    # Non-target financial/support sections are valuable for locating a code but
    # should not write public fields.
    if policy.get("diagnostic_only"):
        return {"diagnostic_raw_text": _clean((raw_context or {}).get("raw_text") or "")}
    # Keep only public-write-safe fields plus diagnostic memoria_quant_total.
    safe = {k: v for k, v in fields.items() if k in allowed or k in {"memoria_quant_total", "diagnostic_raw_text"}}
    return safe

def build_physical_evidence_index(pdf_path: str, final_result: Dict[str, Any] | None = None, options: Dict[str, Any] | None = None, *, max_keys: int = 120, max_occurrences_per_key: int = 80) -> Dict[str, Any]:
    final_result = final_result if isinstance(final_result, dict) else {}
    options = options if isinstance(options, dict) else {}
    identities = _identity_pairs_from_final(final_result)[:max_keys]
    if not identities:
        return {"version": VERSION, "mode": "physical_pdf_evidence_index", "status": "skipped", "reason": "no_codigo_banco_identities", "key_count": 0, "occurrence_count": 0, "keys": {}}
    try:
        import fitz  # type: ignore
    except Exception as exc:
        return {"version": VERSION, "mode": "physical_pdf_evidence_index", "status": "skipped", "reason": "pymupdf_unavailable", "error": str(exc), "key_count": 0, "occurrence_count": 0, "keys": {}}
    known_interval_pages = set(_pages_from_ranges(options, final_result))
    # v61.0.46: scan the whole PDF once, but classify each page/section before
    # giving evidence permission to write fields.  This prevents calculation
    # memory, BDI, schedule and ABC rows from polluting prices while still
    # letting them help as context.
    by_key: Dict[str, Dict[str, Any]] = {i["key"]: {"key": i["key"], "codigo": i["codigo"], "banco": i["banco"], "families": i.get("families") or [], "requested_fields": i.get("requested_fields") or [], "occurrences": [], "fields": defaultdict(list), "pages": set()} for i in identities}
    page_sections: List[Dict[str, Any]] = []
    policy_counts: Dict[str, int] = defaultdict(int)
    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:
        return {"version": VERSION, "mode": "physical_pdf_evidence_index", "status": "error", "reason": "pdf_open_failed", "error": str(exc), "key_count": 0, "occurrence_count": 0, "keys": {}}
    try:
        for zero_idx in range(doc.page_count):
            page_num = zero_idx + 1
            # Whole-document scan is intentional. known_interval_pages is used to
            # classify the source zone and evidence policy, not to skip pages.
            page = doc.load_page(zero_idx)
            try:
                page_text = page.get_text("text") or ""
            except Exception:
                page_text = ""
            section_info = classify_document_section(page_text, page_num=page_num, in_declared_range=page_num in known_interval_pages)
            page_sections.append(section_info)
            try:
                words = page.get_text("words") or []
            except Exception:
                words = []
            lines = _group_words_into_lines(words)
            for idx, line in enumerate(lines):
                text = line.get("text") or ""
                if not text:
                    continue
                for ident in identities:
                    key = ident["key"]
                    bucket = by_key.get(key)
                    if bucket is None or len(bucket["occurrences"]) >= max_occurrences_per_key:
                        continue
                    if not _key_match(text, ident.get("codigo"), ident.get("banco")):
                        continue
                    section = section_info.get("section") or "unknown"
                    if page_num in known_interval_pages and section in {"orcamento_sintetico", "composicoes_analiticas", "declared_range_unknown_layout"}:
                        source_zone = "known_budget_or_composition_interval"
                    elif page_num in known_interval_pages:
                        source_zone = f"known_interval_non_target_section:{section}"
                    else:
                        source_zone = "outside_known_intervals" if known_interval_pages else "unknown_or_all_document"
                    policy = section_evidence_policy(section, source_zone=source_zone)
                    policy_counts[str(policy.get("policy"))] += 1
                    # Structured budget/composition rows are often split across
                    # baselines. Fuse locally before field extraction. Other
                    # sections remain raw/contextual.
                    fused_line = _fuse_visual_row(lines, idx, identities, ident) if section in {"orcamento_sintetico", "composicoes_analiticas", "declared_range_unknown_layout"} else line
                    fused_text = fused_line.get("text") or text
                    raw_context = parse_raw_occurrence_context(fused_text, ident.get("codigo"), ident.get("banco"))
                    raw_lower = str((raw_context or {}).get("raw_text") or fused_text).lower()
                    if source_zone != "known_budget_or_composition_interval" and ("valor" in raw_lower and ("total" in raw_lower or "custo parcial" in raw_lower)):
                        # Explicit labelled raw contexts are stronger than random
                        # text outside ranges.  They remain below table evidence,
                        # but can close a missing numeric field when math agrees.
                        policy = dict(policy)
                        allowed = set(policy.get("repair_allowed_fields") or [])
                        allowed.update({"valor_unit", "total", "custo_unitario_com_bdi", "custo_parcial"})
                        policy["repair_allowed_fields"] = sorted(allowed)
                        policy["policy"] = "labeled_raw_occurrence_context"
                        policy["diagnostic_only"] = False
                    if source_zone == "known_budget_or_composition_interval":
                        fields = _extract_fields_from_line(fused_line, ident.get("codigo"), ident.get("banco"), ident.get("families") or [])
                        # If structured extraction got little because the row is
                        # unusual, keep safe raw hints too.
                        for fk, fv in (raw_context.get("fields") or {}).items():
                            if fk != "numeric_candidates" and fk not in fields:
                                fields[fk] = fv
                        confidence = min(0.99, 0.90 * float(policy.get("weight") or 1.0) + (0.06 if fields else 0.0))
                    else:
                        fields = dict(raw_context.get("fields") or {})
                        fields.pop("numeric_candidates", None)
                        confidence = min(0.90, 0.70 * float(policy.get("weight") or 0.55) + (0.12 if fields else 0.0))
                        if policy.get("policy") == "labeled_raw_occurrence_context" and fields:
                            confidence = max(confidence, 0.84)
                    fields = _apply_section_policy_to_fields(fields, raw_context, policy)
                    occurrence = {
                        "page": page_num,
                        "line_text": fused_text,
                        "original_line_text": text,
                        "bbox": fused_line.get("bbox") or line.get("bbox") or [],
                        "source": "physical_pdf_index",
                        "source_zone": source_zone,
                        "document_section": section,
                        "section_confidence": section_info.get("confidence"),
                        "evidence_policy": policy,
                        "confidence": confidence,
                        "fields_detected": fields,
                        "raw_context": raw_context,
                        "fusion": fused_line.get("fusion") or {},
                    }
                    bucket["occurrences"].append(occurrence)
                    bucket["pages"].add(page_num)
                    for field, value in fields.items():
                        if value in (None, "") or field in {"diagnostic_raw_text"}:
                            continue
                        field_allowed = field in set(policy.get("repair_allowed_fields") or [])
                        bucket["fields"][field].append({
                            "field": field,
                            "value": _clean(value),
                            "page": page_num,
                            "source": "physical_pdf_index",
                            "confidence": occurrence["confidence"],
                            "line_text": fused_text,
                            "bbox": fused_line.get("bbox") or line.get("bbox") or [],
                            "evidence_grade": "physical_pdf_evidence" if source_zone == "known_budget_or_composition_interval" else "raw_physical_occurrence_evidence",
                            "source_zone": source_zone,
                            "document_section": section,
                            "evidence_policy": policy.get("policy"),
                            "repair_allowed_fields": policy.get("repair_allowed_fields") or [],
                            "field_public_write_allowed": bool(field_allowed),
                            "fusion": fused_line.get("fusion") or {},
                        })
    finally:
        try:
            doc.close()
        except Exception:
            pass
    keys_out: Dict[str, Any] = {}
    occurrence_count = 0
    for key, bucket in by_key.items():
        occ = list(bucket.get("occurrences") or [])
        if not occ:
            continue
        occurrence_count += len(occ)
        fields_summary: Dict[str, Any] = {}
        for field, records in (bucket.get("fields") or {}).items():
            grouped: Dict[str, Dict[str, Any]] = {}
            for rec in records:
                value = _clean(rec.get("value"))
                if not value:
                    continue
                g = grouped.setdefault(value, {"value": value, "count": 0, "sources": [], "pages": set(), "max_confidence": 0.0, "records": []})
                g["count"] += 1
                g["sources"].append("physical_pdf_index")
                g["pages"].add(int(rec.get("page") or 0))
                g["max_confidence"] = max(float(g.get("max_confidence") or 0.0), float(rec.get("confidence") or 0.0))
                if len(g["records"]) < 12:
                    g["records"].append(rec)
            values = []
            for data in grouped.values():
                data["pages"] = sorted(p for p in data.pop("pages") if p)
                data["source_count"] = len(set(data.get("sources") or []))
                values.append(data)
            values.sort(key=lambda d: (d.get("count", 0), d.get("source_count", 0), d.get("max_confidence", 0.0)), reverse=True)
            fields_summary[field] = {"values": values[:20], "candidate_count": len(records), "source": "physical_pdf_index"}
        keys_out[key] = {
            "key": key,
            "codigo": bucket.get("codigo"),
            "banco": bucket.get("banco"),
            "families": bucket.get("families") or [],
            "requested_fields": bucket.get("requested_fields") or [],
            "occurrences": occ[:max_occurrences_per_key],
            "occurrence_count": len(occ),
            "pages": sorted(bucket.get("pages") or []),
            "fields": fields_summary,
        }
    zone_counts: Dict[str, int] = defaultdict(int)
    for bucket in keys_out.values():
        for occ in bucket.get("occurrences") or []:
            zone_counts[str(occ.get("source_zone") or "unknown")] += 1
    return {"version": VERSION, "mode": "physical_pdf_evidence_index", "status": "ok", "scan_scope": "whole_document_with_section_aware_policies", "known_interval_pages": sorted(known_interval_pages), "source_zone_counts": dict(zone_counts), "document_section_counts": summarize_section_counts(page_sections), "page_sections": page_sections[:220], "evidence_policy_counts": dict(policy_counts), "key_count": len(keys_out), "occurrence_count": occurrence_count, "keys": keys_out}


def merge_physical_evidence_into_document_index(document_index: Dict[str, Any], physical_index: Dict[str, Any] | None) -> Dict[str, Any]:
    if not isinstance(document_index, dict):
        document_index = {"version": VERSION, "mode": "global_extracted_document_evidence_index", "keys": {}}
    if not isinstance(physical_index, dict) or not physical_index.get("keys"):
        return document_index
    merged = copy.deepcopy(document_index)
    keys = merged.setdefault("keys", {})
    for key, pbucket in (physical_index.get("keys") or {}).items():
        if not isinstance(pbucket, dict):
            continue
        bucket = keys.setdefault(key, {"key": key, "occurrences": [], "occurrence_count": 0, "families": {}, "pages": [], "fields": {}})
        existing_occ = bucket.setdefault("occurrences", [])
        for occ in (pbucket.get("occurrences") or [])[:80]:
            existing_occ.append({**occ, "source": "physical_pdf_index"})
        bucket["occurrence_count"] = len(existing_occ)
        bucket["pages"] = sorted(set(list(bucket.get("pages") or []) + list(pbucket.get("pages") or [])))
        families = bucket.setdefault("families", {})
        for fam in pbucket.get("families") or []:
            families[fam] = int(families.get(fam) or 0) + 1
        fields = bucket.setdefault("fields", {})
        for field, pdata in (pbucket.get("fields") or {}).items():
            fbucket = fields.setdefault(field, {"values": [], "candidate_count": 0})
            current_by_value = {_clean(v.get("value")): v for v in fbucket.get("values") or [] if isinstance(v, dict)}
            for v in pdata.get("values") or []:
                value = _clean(v.get("value"))
                if not value:
                    continue
                cur = current_by_value.get(value)
                if cur is None:
                    cur = {"value": value, "count": 0, "sources": [], "pages": [], "max_confidence": 0.0, "records": []}
                    current_by_value[value] = cur
                    fbucket.setdefault("values", []).append(cur)
                cur["count"] = int(cur.get("count") or 0) + int(v.get("count") or 1)
                cur["sources"] = list(cur.get("sources") or []) + list(v.get("sources") or ["physical_pdf_index"])
                cur["pages"] = sorted(set(list(cur.get("pages") or []) + list(v.get("pages") or [])))
                cur["source_count"] = len(set(s for s in cur.get("sources") or [] if s))
                cur["max_confidence"] = max(float(cur.get("max_confidence") or 0.0), float(v.get("max_confidence") or 0.0))
                cur["records"] = (list(cur.get("records") or []) + list(v.get("records") or []))[:12]
            fbucket["candidate_count"] = int(fbucket.get("candidate_count") or 0) + int(pdata.get("candidate_count") or 0)
            fbucket["values"] = sorted(fbucket.get("values") or [], key=lambda d: (d.get("count", 0), d.get("source_count", 0), d.get("max_confidence", 0.0)), reverse=True)[:20]
    merged["physical_evidence_index"] = {"version": physical_index.get("version"), "key_count": physical_index.get("key_count", 0), "occurrence_count": physical_index.get("occurrence_count", 0), "status": physical_index.get("status"), "scan_scope": physical_index.get("scan_scope"), "source_zone_counts": physical_index.get("source_zone_counts") or {}}
    merged["mode"] = "global_extracted_plus_physical_document_evidence_index"
    merged["key_count"] = len(keys)
    merged["occurrence_count"] = sum(len((b or {}).get("occurrences") or []) for b in keys.values() if isinstance(b, dict))
    return merged


def compact_physical_index_report(index: Dict[str, Any], *, max_keys: int = 40) -> Dict[str, Any]:
    keys = index.get("keys") if isinstance(index, dict) else {}
    sample = {}
    for key, bucket in list((keys or {}).items())[:max_keys]:
        sample[key] = {
            "occurrence_count": bucket.get("occurrence_count"),
            "pages": bucket.get("pages"),
            "fields": {f: {"candidate_count": d.get("candidate_count"), "top": (d.get("values") or [])[:3]} for f, d in (bucket.get("fields") or {}).items()},
        }
    return {"version": VERSION, "mode": index.get("mode"), "status": index.get("status"), "scan_scope": index.get("scan_scope"), "source_zone_counts": index.get("source_zone_counts") or {}, "document_section_counts": index.get("document_section_counts") or {}, "evidence_policy_counts": index.get("evidence_policy_counts") or {}, "key_count": index.get("key_count", 0), "occurrence_count": index.get("occurrence_count", 0), "sample_keys": sample}
