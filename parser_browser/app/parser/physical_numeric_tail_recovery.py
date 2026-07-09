from __future__ import annotations

"""Physical numeric tail recovery for SINAPI-like composition rows.

v61.0.62 policy:
- public numeric fields must be physical PDF tokens, not recalculated values;
- if math/review detects a missing component total and the parser already knows
  composition/page/code, re-open the same composition block and recover the tail
  ``und quant valor_unit total`` from the PDF text;
- calculations may rank/validate candidates, but only physical tokens can patch
  public fields.
"""

from decimal import Decimal, InvalidOperation
import copy
import re
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

from app.core.numeric_fidelity import numeric_source
from app.core.pdf_session import PdfDocumentSession
from app.parser.math_status import compute_component_math, as_float

_VERSION = "v61.0.75-correction-output-contract-and-review-index"

_NUM = r"-?\d{1,3}(?:\.\d{3})*,\d+|-?\d+,\d+|-?\d+"
_UNIT = r"[%A-Za-zÀ-ÿ0-9²³./]+"
_TAIL_RE = re.compile(
    rf"(?P<und>{_UNIT})\s+(?P<quant>{_NUM})\s+(?P<valor_unit>{_NUM})\s+(?P<total>{_NUM})\s*$",
    flags=re.IGNORECASE | re.DOTALL,
)
_ANY_TAIL_RE = re.compile(
    rf"(?P<und>{_UNIT})\s+(?P<quant>{_NUM})\s+(?P<valor_unit>{_NUM})\s+(?P<total>{_NUM})",
    flags=re.IGNORECASE | re.DOTALL,
)
_BLOCK_HEADER_RE = re.compile(r"(?:^|\n)\s*(\d+(?:\.\d+)*)\s+C[ÓO]DIGO\s+Banco\s+Descri", re.IGNORECASE)
_ROW_START_RE = re.compile(r"(?:^|\n)\s*(Composi[cç][aã]o\s+Auxiliar|Composi[cç][aã]o|Insumo)\s+", re.IGNORECASE)
_SUMMARY_STOP_RE = re.compile(r"\n\s*(?:MO\s+sem\s+LS|Valor\s+do\s+BDI|Valor\s+com\s+BDI|Total\s+sem\s+BDI)\b", re.IGNORECASE)

_UNIT_BLACKLIST = {
    "DE", "DO", "DA", "DAS", "DOS", "E", "A", "O", "AS", "OS", "COM", "SEM", "PARA", "ATE", "ATÉ",
    "MAIOR", "MENOR", "IGUAL", "PADRAO", "POPULAR", "MATERIAL", "SERVICO", "SERVIÇO", "TIPO",
}


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split()).strip()


def _normalize_ascii(value: Any) -> str:
    import unicodedata

    text = _clean_text(value).upper()
    text = "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))
    return text


def _norm_code(value: Any) -> str:
    return re.sub(r"[^0-9A-Z]", "", _normalize_ascii(value))


def _ptbr_decimal(value: Any) -> Optional[Decimal]:
    text = _clean_text(value).replace("R$", "").replace(" ", "")
    if not text:
        return None
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _money_text(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    dec = _ptbr_decimal(text)
    if dec is None:
        return text
    q = dec.quantize(Decimal("0.01"))
    base = f"{q:.2f}".replace(".", ",")
    inteiro, frac = base.split(",", 1)
    neg = inteiro.startswith("-")
    if neg:
        inteiro = inteiro[1:]
    groups: List[str] = []
    while inteiro:
        groups.append(inteiro[-3:])
        inteiro = inteiro[:-3]
    return ("-" if neg else "") + ".".join(reversed(groups or ["0"])) + "," + frac


def _page_numbers_for_block(block: Dict[str, Any], options: Dict[str, Any] | None = None) -> List[int]:
    pages: List[int] = []
    for src in (block, block.get("detalhes") if isinstance(block.get("detalhes"), dict) else {}):
        raw = src.get("paginas") if isinstance(src, dict) else None
        if isinstance(raw, list):
            for p in raw:
                try:
                    ip = int(p)
                    if ip > 0 and ip not in pages:
                        pages.append(ip)
                except Exception:
                    pass
        for key in ("pagina_inicio", "pagina_fim", "page", "page_hint"):
            try:
                ip = int(src.get(key) or 0) if isinstance(src, dict) else 0
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


def _code_regex(code: Any) -> str:
    # Spaces and punctuation inside codes are sometimes rendered with variable
    # spacing. Keep punctuation meaningful but allow whitespace around it.
    text = _clean_text(code)
    parts = []
    for ch in text:
        if ch.isspace():
            parts.append(r"\s*")
        elif ch in {"-", "/", "."}:
            parts.append(r"\s*" + re.escape(ch) + r"\s*")
        else:
            parts.append(re.escape(ch))
    return "".join(parts) or r"a^"


def _bank_regex(bank: Any) -> str:
    norm = _normalize_ascii(bank)
    if norm in {"PROPRIO", "PRÓPRIO"}:
        return r"(?:Pr[óo]prio|PROPRIO|PRÓPRIO)"
    if norm.startswith("SICRO"):
        return r"SICRO\s*3?|SICRO3|DNIT"
    return re.escape(_clean_text(bank) or "SINAPI")


def _row_kind_regex(group: str) -> str:
    if group == "principal":
        return r"Composi[cç][aã]o"
    if group == "composicoes_auxiliares":
        return r"Composi[cç][aã]o\s+Auxiliar"
    return r"Insumo"


def _iter_family_blocks(composicoes: Dict[str, Any]) -> Iterator[Tuple[str, str, str, Dict[str, Any]]]:
    if not isinstance(composicoes, dict):
        return
    for family in ("sinapi_like", "sicro"):
        fam = composicoes.get(family)
        if isinstance(fam, dict):
            for collection in ("principais", "auxiliares_globais"):
                blocks = fam.get(collection)
                if isinstance(blocks, dict):
                    for key, block in list(blocks.items()):
                        if isinstance(block, dict):
                            yield family, collection, str(key), block
    for collection in ("principais", "auxiliares_globais"):
        blocks = composicoes.get(collection)
        if isinstance(blocks, dict):
            for key, block in list(blocks.items()):
                if isinstance(block, dict):
                    bank = _normalize_ascii((block.get("principal") or {}).get("banco") if isinstance(block.get("principal"), dict) else "")
                    family = "sicro" if bank.startswith("SICRO") else "sinapi_like"
                    yield family, collection, str(key), block


def _iter_rows(block: Dict[str, Any]) -> Iterator[Tuple[str, Optional[int], Dict[str, Any]]]:
    principal = block.get("principal") if isinstance(block.get("principal"), dict) else None
    if principal is not None:
        yield "principal", None, principal
    for group in ("composicoes_auxiliares", "insumos"):
        rows = block.get(group)
        if isinstance(rows, list):
            for idx, row in enumerate(rows):
                if isinstance(row, dict):
                    yield group, idx, row


def _select_best_tail(text: str, expected_totals: Iterable[str] | None = None):
    """Return the safest physical ``und quant valor_unit total`` candidate.

    This keeps v61.0.60 behavior, but upgrades candidate selection to use the
    existing math delta only as a selector.  It never creates a public value: the
    returned values are still tokens that already exist in ``text``.
    """
    body_clean = " ".join(str(text or "").split())
    if not body_clean:
        return None
    expected = {_money_text(v) for v in (expected_totals or []) if _clean_text(v)}
    end_tail = _TAIL_RE.search(body_clean)
    candidates = []
    if end_tail:
        candidates.append(end_tail)
    for cand in _ANY_TAIL_RE.finditer(body_clean):
        if cand not in candidates:
            candidates.append(cand)
    valid = []
    for cand in candidates:
        unit_norm = _normalize_ascii(cand.group('und'))
        if unit_norm in _UNIT_BLACKLIST:
            continue
        total_txt = _clean_text(cand.group('total'))
        # Score: expected math delta (if any) is a tie-breaker only.  Last
        # candidate wins otherwise because wrapped descriptions often appear
        # after the right-side numeric cells in extracted text.
        score = 0
        if expected and _money_text(total_txt) in expected:
            score += 100
        if cand is end_tail:
            score += 10
        score += min(cand.start(), 10_000) / 10_000
        valid.append((score, cand))
    if not valid:
        return None
    valid.sort(key=lambda x: x[0])
    return valid[-1][1]


def _extract_context_tail_by_expected_value(block_text: str, row: Dict[str, Any], group: str, expected_totals: Iterable[str] | None = None) -> Optional[Dict[str, Any]]:
    """Fallback recovery: use code/bank context + expected total token.

    The normal row segmenter is still preferred.  This fallback only runs inside
    the already-known composition block, and only writes tokens physically found
    near the target code/bank.  It is useful when a PDF text extractor separates
    the visual numeric tail from the row segment while the value that closes the
    math is visible in the same local context.
    """
    code = row.get('codigo')
    bank = row.get('banco') or row.get('fonte') or 'SINAPI'
    if not code:
        return None
    expected = {_money_text(v) for v in (expected_totals or []) if _clean_text(v)}
    pat = re.compile(rf"{_code_regex(code)}\s+{_bank_regex(bank)}\b", flags=re.IGNORECASE)
    matches = list(pat.finditer(block_text or ""))
    if not matches:
        return None
    current_desc = _normalize_ascii(row.get('descricao'))
    windows: List[Tuple[int, str]] = []
    for m in matches:
        start = max(0, m.start() - 160)
        # Stop at the next typed row/header/summary when possible, but keep a
        # short physical lookahead so a detached numeric tail on the following
        # visual line is still considered.
        next_stop = re.search(r"(?:\n\s*(?:Composi[cç][aã]o\s+Auxiliar|Composi[cç][aã]o|Insumo)\s+)|(?:\n\s*\d+(?:\.\d+)*\s+C[ÓO]DIGO\s+Banco)|(?:\n\s*MO\s+sem\s+LS)|(?:\n\s*Valor\s+do\s+BDI)", (block_text or "")[m.end():], flags=re.IGNORECASE)
        stop = (m.end() + next_stop.start()) if next_stop else min(len(block_text or ""), m.end() + 900)
        stop = min(len(block_text or ""), max(stop, m.end() + 320))
        window = (block_text or "")[start:stop]
        score = 0
        wnorm = _normalize_ascii(window)
        for tok in current_desc.split()[:14]:
            if len(tok) >= 4 and tok in wnorm:
                score += 1
        windows.append((score, window))
    windows.sort(key=lambda x: x[0], reverse=True)
    for _score, window in windows:
        clean = " ".join(window.split())
        tails = []
        for cand in _ANY_TAIL_RE.finditer(clean):
            unit_norm = _normalize_ascii(cand.group('und'))
            if unit_norm in _UNIT_BLACKLIST:
                continue
            total_txt = _money_text(cand.group('total'))
            if expected and total_txt not in expected:
                # The user's requested strategy: when we already know the value
                # that closes the row, first look for that exact physical token
                # in the same local context.
                continue
            tails.append(cand)
        tail = tails[-1] if tails else _select_best_tail(clean, expected_totals=expected)
        if tail:
            tail_data = {k: _clean_text(tail.group(k)) for k in ("und", "quant", "valor_unit", "total")}
            before_tail = clean[: tail.start()].strip(" -:;,")
            after_tail = clean[tail.end():].strip(" -:;,")
            before_tail = re.sub(r"(?i)\s+(?:Material|M[aã]o de Obra|Servi[cç]o|Equipamento|Livro SINAPI:\s*C[aá]lculos\s+e|Livro SINAPI:\s*C[aá]lculos|PISO\s*-\s*PISOS|REVE\s*-.*|REJUNTE\s*-.*)$", "", before_tail).strip(" -:;,")
            after_norm = _normalize_ascii(after_tail)
            append_after = bool(after_tail and len(after_tail.split()) >= 2 and after_norm not in {"PARAMETROS", "CALCULOS E PARAMETROS"})
            desc_text = _clean_text((before_tail + (" " + after_tail if append_after else "")).strip())
            return {"row_text": _clean_text(clean), "tail": tail_data, "body": clean, "description": desc_text, "strategy": "context_expected_value" if expected else "context_near_code"}
    return None


def _extract_block_text(page_text: str, block: Dict[str, Any]) -> str:
    text = str(page_text or "")
    item = _clean_text(block.get("item"))
    start = -1
    if item:
        m = re.search(rf"(?:^|\n)\s*{re.escape(item)}\s+C[ÓO]DIGO\s+Banco\s+Descri", text, flags=re.IGNORECASE)
        if m:
            start = m.start()
    principal = block.get("principal") if isinstance(block.get("principal"), dict) else {}
    if start < 0 and isinstance(principal, dict):
        code = principal.get("codigo")
        bank = principal.get("banco")
        if code:
            m = re.search(rf"(?:^|\n)\s*Composi[cç][aã]o\s+{_code_regex(code)}\s+{_bank_regex(bank)}\b", text, flags=re.IGNORECASE)
            if m:
                start = m.start()
    if start < 0:
        return text
    next_header = _BLOCK_HEADER_RE.search(text, start + 8)
    summary_stop = _SUMMARY_STOP_RE.search(text, start + 8)
    candidates = [m.start() for m in (next_header, summary_stop) if m is not None]
    end = min(candidates) if candidates else len(text)
    return text[start:end]


def _extract_row_segment(block_text: str, row: Dict[str, Any], group: str) -> Optional[Dict[str, Any]]:
    code = row.get("codigo")
    bank = row.get("banco") or row.get("fonte") or "SINAPI"
    if not code:
        return None
    kind_pat = _row_kind_regex(group)
    row_pat = re.compile(
        rf"(?:^|\n)\s*(?P<kind>{kind_pat})\s+{_code_regex(code)}\s+{_bank_regex(bank)}\b(?P<body>.*?)(?=(?:\n\s*(?:Composi[cç][aã]o\s+Auxiliar|Composi[cç][aã]o|Insumo)\s+)|(?:\n\s*\d+(?:\.\d+)*\s+C[ÓO]DIGO\s+Banco)|(?:\n\s*MO\s+sem\s+LS)|(?:\n\s*Valor\s+do\s+BDI)|$)",
        flags=re.IGNORECASE | re.DOTALL,
    )
    matches = list(row_pat.finditer(block_text or ""))
    if not matches:
        # Last defensive fallback: code/bank in same composition block, but still
        # stops before the next typed row. It is only used inside a known block.
        row_pat = re.compile(
            rf"(?:^|\n).*?{_code_regex(code)}\s+{_bank_regex(bank)}\b(?P<body>.*?)(?=(?:\n\s*(?:Composi[cç][aã]o\s+Auxiliar|Composi[cç][aã]o|Insumo)\s+)|(?:\n\s*\d+(?:\.\d+)*\s+C[ÓO]DIGO\s+Banco)|(?:\n\s*MO\s+sem\s+LS)|(?:\n\s*Valor\s+do\s+BDI)|$)",
            flags=re.IGNORECASE | re.DOTALL,
        )
        matches = list(row_pat.finditer(block_text or ""))
    if not matches:
        return None
    # If duplicated, prefer the one whose normalized description overlaps the
    # current row description. Otherwise the first match in this block is safest.
    current_desc = _normalize_ascii(row.get("descricao"))
    best = matches[0]
    best_score = -1
    for m in matches:
        body_norm = _normalize_ascii(m.group("body"))
        score = 0
        for tok in current_desc.split()[:12]:
            if len(tok) >= 4 and tok in body_norm:
                score += 1
        if score > best_score:
            best = m
            best_score = score
    body = best.group("body") or ""
    row_text = best.group(0) or ""
    body_clean = " ".join(body.split())
    tail = _select_best_tail(body_clean, expected_totals=None)
    if not tail:
        return {"row_text": _clean_text(row_text), "tail": None, "body": body_clean}
    tail_data = {k: _clean_text(tail.group(k)) for k in ("und", "quant", "valor_unit", "total")}
    if _normalize_ascii(tail_data.get("und")) in _UNIT_BLACKLIST:
        return {"row_text": _clean_text(row_text), "tail": None, "body": body_clean, "rejected": "unit_blacklist"}

    before_tail = body_clean[: tail.start()].strip(" -:;,")
    after_tail = body_clean[tail.end():].strip(" -:;,")
    # Remove Tipo-column text that can be interleaved before the numeric tail.
    before_tail = re.sub(
        r"(?i)\s+(?:Material|M[aã]o de Obra|Servi[cç]o|Equipamento|Livro SINAPI:\s*C[aá]lculos\s+e|Livro SINAPI:\s*C[aá]lculos|PISO\s*-\s*PISOS|REVE\s*-.*|REJUNTE\s*-.*)$",
        "",
        before_tail,
    ).strip(" -:;,")
    after_norm = _normalize_ascii(after_tail)
    append_after = bool(after_tail and len(after_tail.split()) >= 2 and after_norm not in {"PARAMETROS", "CALCULOS E PARAMETROS"})
    desc_text = _clean_text((before_tail + (" " + after_tail if append_after else "")).strip())
    return {"row_text": _clean_text(row_text), "tail": tail_data, "body": body_clean, "description": desc_text}


def _row_needs_recovery(row: Dict[str, Any], *, force_block: bool = False) -> bool:
    if not isinstance(row, dict):
        return False
    if force_block:
        return True
    return any(row.get(f) in (None, "", [], {}) for f in ("und", "quant", "valor_unit", "total"))


def _same_numeric_value(current: Any, source: Any) -> bool:
    c = _ptbr_decimal(current)
    s = _ptbr_decimal(source)
    return c is not None and s is not None and c == s


def _apply_tail_to_row(row: Dict[str, Any], tail: Dict[str, str], evidence: Dict[str, Any], *, allow_existing_format_upgrade: bool = True) -> List[Dict[str, Any]]:
    patches: List[Dict[str, Any]] = []
    detalhes = row.setdefault("detalhes", {})
    if not isinstance(detalhes, dict):
        row["detalhes"] = detalhes = {}
    src = detalhes.setdefault("numeric_source", {})
    if not isinstance(src, dict):
        detalhes["numeric_source"] = src = {}
    for field in ("und", "quant", "valor_unit", "total"):
        source_text = _clean_text(tail.get(field))
        if not source_text:
            continue
        current = row.get(field)
        should_patch = current in (None, "", [], {})
        if not should_patch and field != "und" and allow_existing_format_upgrade and _same_numeric_value(current, source_text) and _clean_text(current) != source_text:
            should_patch = True
        if not should_patch and field == "und" and _normalize_ascii(current) == _normalize_ascii(source_text) and _clean_text(current) != source_text:
            should_patch = True
        if should_patch:
            previous = row.get(field)
            row[field] = source_text
            if field != "und":
                src[field] = numeric_source(source_text)
            patches.append({"field": field, "previous_value": previous, "value": source_text, **evidence})
    return patches


def _maybe_patch_description(row: Dict[str, Any], desc: str, evidence: Dict[str, Any]) -> List[Dict[str, Any]]:
    patches: List[Dict[str, Any]] = []
    desc = _clean_text(desc)
    current = _clean_text(row.get("descricao"))
    if not desc or len(desc) <= len(current):
        return patches
    cur_norm = _normalize_ascii(current)
    desc_norm = _normalize_ascii(desc)
    # Safe only when current is a prefix/subsequence of the physical PDF text.
    if cur_norm and (cur_norm in desc_norm or desc_norm.startswith(cur_norm[: max(8, min(len(cur_norm), 40))])):
        previous = row.get("descricao")
        row["descricao"] = desc
        patches.append({"field": "descricao", "previous_value": previous, "value": desc, **evidence})
    return patches


def _delta_candidates(block: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    for source in (block.get("detalhes") if isinstance(block.get("detalhes"), dict) else {},):
        for payload in (source.get("math_triage"), source.get("math_status"), source.get("_calc")):
            if isinstance(payload, dict):
                for key in ("delta", "missing_delta", "principal_minus_components"):
                    if payload.get(key) not in (None, ""):
                        out.append(_money_text(payload.get(key)))
                ms = payload.get("math_status") if isinstance(payload.get("math_status"), dict) else {}
                if ms.get("delta") not in (None, ""):
                    out.append(_money_text(ms.get("delta")))
    return [x for x in out if x]




def _quality_gate_target_blocks(result: Dict[str, Any], options: Dict[str, Any] | None = None) -> set[str]:
    """Return composition keys that must be revisited before final export.

    This makes recovery mandatory but targeted: when the current JSON already
    tells us which blocks are broken, we do not scan the whole PDF/composition
    interval.  It is the key difference between a passive audit and an effective
    repair pass.
    """
    targets: set[str] = set()
    options = options or {}
    for raw in (options.get("target_blocks"), options.get("target_compositions")):
        if isinstance(raw, list):
            targets.update(str(x) for x in raw if str(x or "").strip())
        elif isinstance(raw, str) and raw.strip():
            targets.add(raw.strip())
    containers: List[Dict[str, Any]] = []
    gate = ((result.get("auditoria_final") or {}).get("quality_gate") or {}) if isinstance(result.get("auditoria_final"), dict) else {}
    if isinstance(gate, dict):
        containers.append(gate)
    corr = result.get("documento_correcao") if isinstance(result.get("documento_correcao"), dict) else {}
    if isinstance(corr.get("quality_gate"), dict):
        containers.append(corr.get("quality_gate"))
    for container in containers:
        for issue in list(container.get("issues") or []):
            if isinstance(issue, dict):
                block = issue.get("block") or issue.get("composition") or issue.get("chave")
                if block:
                    targets.add(str(block))
    perf = ((result.get("meta") or {}).get("performance") or {}) if isinstance(result.get("meta"), dict) else {}
    for rep_name in ("physical_numeric_tail_recovery", "physical_numeric_tail_recovery_finalize", "physical_numeric_tail_recovery_accuracy_flow", "physical_numeric_tail_recovery_standalone"):
        rep = perf.get(rep_name) if isinstance(perf, dict) else None
        if isinstance(rep, dict):
            for unresolved in list(rep.get("blocking_unresolved") or []):
                if isinstance(unresolved, dict) and unresolved.get("block"):
                    targets.add(str(unresolved.get("block")))
    return targets


def _row_public_numeric_complete(row: Dict[str, Any]) -> bool:
    return isinstance(row, dict) and all(row.get(f) not in (None, "", [], {}) for f in ("und", "quant", "valor_unit", "total"))


def _row_lock_state(row: Dict[str, Any], math: Dict[str, Any] | None = None) -> str:
    if not isinstance(row, dict):
        return "unresolved"
    return "locked" if _row_public_numeric_complete(row) else "needs_recovery"


def _build_composition_lock_report(block: Dict[str, Any], *, pages: List[int], before_math: Dict[str, Any], after_math: Dict[str, Any], patches: List[Dict[str, Any]]) -> Dict[str, Any]:
    rows = []
    locked = 0
    needs = 0
    locked_fragment_ids: List[str] = []
    patch_by_row: Dict[Tuple[str, Optional[int]], int] = {}
    for p in patches:
        if isinstance(p, dict):
            k = (str(p.get("row_group") or ""), p.get("row_index"))
            patch_by_row[k] = patch_by_row.get(k, 0) + 1
    for group, idx, row in _iter_rows(block):
        status = _row_lock_state(row, after_math)
        if status == "locked":
            locked += 1
        else:
            needs += 1
        rid = f"{group}:{'' if idx is None else idx}:{_norm_code(row.get('codigo'))}|{_normalize_ascii(row.get('banco'))}"
        if status == "locked":
            locked_fragment_ids.append(rid)
        rows.append({
            "row_id": rid,
            "row_group": group,
            "row_index": idx,
            "codigo": row.get("codigo"),
            "banco": row.get("banco"),
            "status": status,
            "missing": [f for f in ("und", "quant", "valor_unit", "total") if row.get(f) in (None, "", [], {})],
            "patch_count": patch_by_row.get((group, idx), 0),
        })
    return {
        "version": _VERSION,
        "mode": "focused_composition_locking",
        "pages": pages,
        "before_math": before_math,
        "after_math": after_math,
        "locked_rows": locked,
        "open_rows": needs,
        "all_rows_locked": needs == 0,
        "locked_fragment_count": len(locked_fragment_ids),
        "locked_fragment_ids": locked_fragment_ids[:80],
        "rows": rows,
        "policy": "locked_rows_own_their_fragments_open_rows_receive_only_free_local_fragments",
    }

def apply_physical_numeric_tail_recovery(
    result: Dict[str, Any],
    *,
    pdf_session: PdfDocumentSession,
    options: Dict[str, Any] | None = None,
    force_all_rows_in_problem_blocks: bool = True,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Patch missing/format-lost SINAPI-like numeric tails from the same PDF page.

    The function mutates and returns ``result`` for runtime compatibility.
    """
    options = options or {}
    report: Dict[str, Any] = {
        "version": _VERSION,
        "attempted": True,
        "blocks_scanned": 0,
        "rows_scanned": 0,
        "rows_with_physical_tail": 0,
        "patches_applied": 0,
        "patches": [],
        "unresolved": [],
        "math_before_after": [],
        "policy": "physical_pdf_token_only_math_as_selector_mandatory_for_blockers",
        "target_blocks": [],
        "focused_locking": [],
    }
    composicoes = result.get("composicoes") if isinstance(result.get("composicoes"), dict) else {}
    target_keys = _quality_gate_target_blocks(result, options)
    report["target_blocks"] = sorted(target_keys)
    acc = options.get("accuracy_profile") if isinstance(options.get("accuracy_profile"), dict) else {}
    full_scan = bool(options.get("physical_numeric_tail_full_scan") or acc.get("physical_numeric_tail_full_scan"))
    mandatory_targeted = bool(target_keys) and bool(options.get("mandatory_targeted", True))
    if not target_keys and not full_scan and bool(options.get("skip_if_no_targets")):
        report["skipped"] = True
        report["reason"] = "no_problem_blocks_for_targeted_physical_numeric_tail_recovery"
        report["blocking_unresolved"] = []
        result.setdefault("meta", {}).setdefault("performance", {})["physical_numeric_tail_recovery"] = report
        result.setdefault("documento_correcao", {})["physical_numeric_tail_recovery"] = report
        return result, report
    page_cache: Dict[int, str] = {}
    for family, collection, key, block in list(_iter_family_blocks(composicoes)):
        if mandatory_targeted and str(key) not in target_keys:
            continue
        if family == "sicro" or not isinstance(block, dict):
            continue
        pages = _page_numbers_for_block(block, options)
        if not pages:
            continue
        before_math = compute_component_math(block)
        problem_block = str(before_math.get("status") or "") in {"component_sum_lower_than_principal", "component_sum_greater_than_principal", "not_validatable"} or int(before_math.get("missing_component_totals") or 0) > 0
        missing_rows = [r for _, _, r in _iter_rows(block) if _row_needs_recovery(r)]
        if not problem_block and not missing_rows and not force_all_rows_in_problem_blocks:
            continue
        report["blocks_scanned"] += 1
        block_text = "\n".join(
            _extract_block_text(page_cache.setdefault(p, pdf_session.get_page_text(p, engine="auto")), block)
            for p in pages
            if p > 0
        )
        deltas = set(_delta_candidates(block))
        block_patches: List[Dict[str, Any]] = []
        for group, idx, row in _iter_rows(block):
            force_row = problem_block and force_all_rows_in_problem_blocks
            if not _row_needs_recovery(row, force_block=force_row):
                continue
            report["rows_scanned"] += 1
            segment = _extract_row_segment(block_text, row, group)
            target = {"collection": collection, "block": key, "row_group": group, "row_index": idx, "codigo": row.get("codigo"), "banco": row.get("banco"), "pages": pages}
            if not segment or not segment.get("tail"):
                context_segment = _extract_context_tail_by_expected_value(block_text, row, group, expected_totals=deltas)
                if context_segment and context_segment.get("tail"):
                    segment = context_segment
                else:
                    report["unresolved"].append({**target, "reason": "physical_tail_not_found", "row_text": (segment or {}).get("row_text")})
                    continue
            report["rows_with_physical_tail"] += 1
            tail = dict(segment.get("tail") or {})
            evidence = {
                "source": "physical_numeric_tail_recovery",
                "confidence": 0.99,
                "evidence": {
                    "pages": pages,
                    "row_text": segment.get("row_text"),
                    "tail": tail,
                    "math_delta_candidates": sorted(deltas),
                    "matched_delta_token": _money_text(tail.get("total")) in set(deltas),
                    "recovery_strategy": segment.get("strategy") or "row_segment",
                },
            }
            patches = _apply_tail_to_row(row, tail, evidence)
            patches += _maybe_patch_description(row, str(segment.get("description") or ""), evidence)
            for patch in patches:
                report["patches"].append({**target, **patch})
            block_patches.extend(patches)
        if block_patches:
            details = block.setdefault("detalhes", {})
            if isinstance(details, dict):
                details.setdefault("physical_numeric_tail_recovery", {})
                details["physical_numeric_tail_recovery"].update({
                    "version": _VERSION,
                    "patch_count": len(block_patches),
                    "pages": pages,
                    "source": "same_composition_block_pdf_text",
                })
                after_math = compute_component_math(block)
                details["math_status"] = after_math
                lock_report = _build_composition_lock_report(block, pages=pages, before_math=before_math, after_math=after_math, patches=[p for p in report["patches"] if p.get("block") == key])
                details["focused_composition_locking"] = lock_report
                report["focused_locking"].append({"collection": collection, "block": key, **lock_report})
                report["math_before_after"].append({"collection": collection, "block": key, "before": before_math, "after": after_math, "patch_count": len(block_patches), "locked_rows": lock_report.get("locked_rows"), "open_rows": lock_report.get("open_rows")})
    report["patches_applied"] = len(report["patches"])
    # Current-state blocker list: after all physical recovery attempts, any
    # SINAPI-like row still missing public financial cells inside a math-problem
    # block must be visible to the final quality gate/correction document.
    blocking_unresolved: List[Dict[str, Any]] = []
    for family, collection, key, block in list(_iter_family_blocks(composicoes)):
        if family == "sicro" or not isinstance(block, dict):
            continue
        math = compute_component_math(block)
        math_status = str((math or {}).get("status") or "")
        problem = math_status in {"component_sum_lower_than_principal", "component_sum_greater_than_principal", "not_validatable"} or int((math or {}).get("missing_component_totals") or 0) > 0
        if not problem:
            continue
        for group, idx, row in _iter_rows(block):
            missing = [f for f in ("und", "quant", "valor_unit", "total") if row.get(f) in (None, "", [], {})]
            if missing:
                blocking_unresolved.append({"collection": collection, "block": key, "row_group": group, "row_index": idx, "codigo": row.get("codigo"), "banco": row.get("banco"), "missing": missing, "math_status": math_status, "severity": "blocking", "blocks_json_ok": True})
    report["blocking_unresolved"] = blocking_unresolved
    result.setdefault("meta", {}).setdefault("performance", {})["physical_numeric_tail_recovery"] = report
    result.setdefault("documento_correcao", {})["physical_numeric_tail_recovery"] = report
    return result, report


def apply_physical_numeric_tail_recovery_bytes(pdf_bytes: bytes, result: Dict[str, Any], options: Dict[str, Any] | None = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    with PdfDocumentSession(pdf_bytes) as session:
        return apply_physical_numeric_tail_recovery(result, pdf_session=session, options=options or {})


def apply_physical_numeric_tail_recovery_file(file_path: str | Path, result: Dict[str, Any], options: Dict[str, Any] | None = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    data = Path(file_path).read_bytes()
    return apply_physical_numeric_tail_recovery_bytes(data, result, options or {})
