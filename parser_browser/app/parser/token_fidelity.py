from __future__ import annotations

"""Public token fidelity pass for SINAPI-like compositions.

This stage keeps the public JSON aligned with physical PDF tokens.  It does not
calculate values.  It looks for the row's physical ``und quant valor_unit total``
tail in the same composition/page context and, when the numeric meaning matches
or the field is empty, rewrites the public field with the exact PDF token.

SICRO is deliberately skipped; the native SICRO engine remains authoritative.
"""

from decimal import Decimal, InvalidOperation
import re
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

from app.config.version import CURRENT_RELEASE
from app.core.numeric_fidelity import numeric_source
from app.core.pdf_session import PdfDocumentSession
from app.parser.global_code_bank_search import search_code_bank_occurrences
from app.parser.math_status import compute_component_math

_NUM = r"-?\d{1,3}(?:\.\d{3})*,\d+|-?\d+,\d+|-?\d+"
_UNIT = r"[%A-Za-zÀ-ÿ0-9²³./]+"
_TAIL_RE = re.compile(rf"(?P<und>{_UNIT})\s+(?P<quant>{_NUM})\s+(?P<valor_unit>{_NUM})\s+(?P<total>{_NUM})", re.IGNORECASE | re.DOTALL)
_UNIT_BLACKLIST = {"DE", "DO", "DA", "DAS", "DOS", "E", "A", "O", "AS", "OS", "COM", "SEM", "PARA", "MATERIAL", "SERVICO", "SERVIÇO", "TIPO"}
_FIELDS = ("und", "quant", "valor_unit", "total")
_NUM_FIELDS = ("quant", "valor_unit", "total")


def _clean(value: Any) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split()).strip()


def _norm(value: Any) -> str:
    import unicodedata
    text = _clean(value).upper()
    return "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))


def _norm_code(value: Any) -> str:
    return re.sub(r"[^0-9A-Z]", "", _norm(value))


def _decimal(value: Any) -> Optional[Decimal]:
    text = _clean(value).replace("R$", "").replace(" ", "")
    if not text:
        return None
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _same_number(a: Any, b: Any) -> bool:
    da = _decimal(a); db = _decimal(b)
    if da is None or db is None:
        return _clean(a) == _clean(b)
    return da == db


def _iter_blocks(composicoes: Dict[str, Any]) -> Iterator[Tuple[str, str, str, Dict[str, Any]]]:
    if not isinstance(composicoes, dict):
        return
    seen: set[int] = set()
    fam = composicoes.get("sinapi_like") if isinstance(composicoes.get("sinapi_like"), dict) else {}
    for collection in ("principais", "auxiliares_globais"):
        blocks = fam.get(collection) if isinstance(fam, dict) else None
        if isinstance(blocks, dict):
            for key, block in list(blocks.items()):
                if isinstance(block, dict) and id(block) not in seen:
                    seen.add(id(block)); yield "sinapi_like", collection, str(key), block
    for collection in ("principais", "auxiliares_globais"):
        blocks = composicoes.get(collection)
        if isinstance(blocks, dict):
            for key, block in list(blocks.items()):
                if not isinstance(block, dict) or id(block) in seen:
                    continue
                principal = block.get("principal") if isinstance(block.get("principal"), dict) else {}
                if _norm(principal.get("banco") or "").startswith("SICRO"):
                    continue
                seen.add(id(block)); yield "sinapi_like", collection, str(key), block


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
                    if ip > 0 and ip not in pages: pages.append(ip)
                except Exception: pass
        for k in ("pagina_inicio", "pagina_fim", "page", "page_hint"):
            try:
                ip = int(src.get(k) or 0)
                if ip > 0 and ip not in pages: pages.append(ip)
            except Exception: pass
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




def _target_blocks_from_result(result: Dict[str, Any], options: Dict[str, Any] | None = None) -> set[str]:
    options = options or {}
    targets: set[str] = set()
    for raw in (options.get("target_blocks"), options.get("target_compositions")):
        if isinstance(raw, list):
            targets.update(str(x) for x in raw if str(x or "").strip())
        elif isinstance(raw, str) and raw.strip():
            targets.add(raw.strip())
    gate = ((result.get("auditoria_final") or {}).get("quality_gate") or {}) if isinstance(result.get("auditoria_final"), dict) else {}
    if isinstance(gate, dict):
        for issue in gate.get("issues") or []:
            if isinstance(issue, dict):
                block = issue.get("block") or issue.get("composition") or issue.get("chave")
                if block:
                    targets.add(str(block))
    return targets

def _valid_tail_match(m: re.Match) -> bool:
    return _norm(m.group("und")) not in _UNIT_BLACKLIST


def _tail_from_window(text: str, row: Dict[str, Any]) -> Optional[Dict[str, str]]:
    matches = [m for m in _TAIL_RE.finditer(" ".join(str(text or "").split())) if _valid_tail_match(m)]
    if not matches:
        return None
    current_total = _clean(row.get("total"))
    current_vu = _clean(row.get("valor_unit"))
    current_q = _clean(row.get("quant"))
    scored: List[Tuple[int, re.Match]] = []
    for m in matches:
        score = 0
        if current_total and _same_number(current_total, m.group("total")): score += 40
        if current_vu and _same_number(current_vu, m.group("valor_unit")): score += 20
        if current_q and _same_number(current_q, m.group("quant")): score += 10
        # Prefer later tails: extracted row windows often contain description
        # numbers before the real right-side tail.
        score += min(m.start(), 10000) // 1000
        scored.append((score, m))
    scored.sort(key=lambda x: x[0])
    best = scored[-1][1]
    return {f: _clean(best.group(f)) for f in _FIELDS}


def _patch_row_from_tail(row: Dict[str, Any], tail: Dict[str, str], evidence: Dict[str, Any]) -> List[Dict[str, Any]]:
    patches: List[Dict[str, Any]] = []
    ns = row.setdefault("numeric_source", {})
    if not isinstance(ns, dict):
        row["numeric_source"] = ns = {}
    for field in _FIELDS:
        new = _clean(tail.get(field))
        if not new:
            continue
        old = _clean(row.get(field))
        should = False
        if not old:
            should = True
        elif field in _NUM_FIELDS and old != new and _same_number(old, new):
            should = True
        elif field == "und" and _norm(old) == _norm(new) and old != new:
            should = True
        if not should:
            continue
        row[field] = new
        if field in _NUM_FIELDS:
            ns[field] = numeric_source(new)
        patches.append({"field": field, "previous_value": old, "value": new, **evidence})
    return patches


def apply_public_token_fidelity(
    result: Dict[str, Any],
    *,
    pdf_session: PdfDocumentSession,
    options: Dict[str, Any] | None = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    options = options or {}
    acc = options.get("accuracy_profile") if isinstance(options.get("accuracy_profile"), dict) else {}
    full_scan = bool(options.get("public_token_fidelity_full_scan") or acc.get("public_token_fidelity_full_scan"))
    target_blocks = _target_blocks_from_result(result, options)
    report: Dict[str, Any] = {
        "version": CURRENT_RELEASE,
        "attempted": True,
        "policy": "rewrite_public_composition_numbers_to_exact_pdf_tokens_when_same_numeric_value",
        "scope": "full_public_json" if full_scan else "targeted_problem_blocks",
        "target_blocks": sorted(target_blocks),
        "blocks_scanned": 0,
        "rows_scanned": 0,
        "patches_applied": 0,
        "patches": [],
        "global_code_bank_search_hits": 0,
    }
    composicoes = result.get("composicoes") if isinstance(result.get("composicoes"), dict) else {}
    if not full_scan and not target_blocks:
        report["skipped"] = True
        report["reason"] = "no_problem_blocks_for_targeted_token_fidelity"
        result.setdefault("meta", {}).setdefault("performance", {})["public_token_fidelity"] = report
        result.setdefault("documento_correcao", {})["public_token_fidelity"] = {k: v for k, v in report.items() if k != "patches"}
        return result, report
    for _family, collection, key, block in _iter_blocks(composicoes):
        if not full_scan and str(key) not in target_blocks:
            continue
        pages = _pages_for_block(block, options)
        if not pages:
            continue
        report["blocks_scanned"] += 1
        block_patch_count = 0
        for group, idx, row in _iter_rows(block):
            if not row.get("codigo"):
                continue
            report["rows_scanned"] += 1
            search = search_code_bank_occurrences(pdf_session, code=row.get("codigo"), bank=row.get("banco") or row.get("fonte") or "SINAPI", pages=pages, max_hits=3)
            report["global_code_bank_search_hits"] += int(search.get("hit_count") or 0)
            tail = None
            hit_for_ev: Dict[str, Any] | None = None
            for hit in search.get("hits") or []:
                tail = _tail_from_window(hit.get("text") or "", row)
                if tail:
                    hit_for_ev = hit
                    break
            if not tail:
                continue
            evidence = {
                "source": "public_token_fidelity",
                "confidence": hit_for_ev.get("confidence", 0.9) if isinstance(hit_for_ev, dict) else 0.9,
                "collection": collection,
                "block": key,
                "row_group": group,
                "row_index": idx,
                "codigo": row.get("codigo"),
                "banco": row.get("banco"),
                "evidence": {"pages": pages, "hit": hit_for_ev, "tail": tail, "strategy": "code_bank_same_block_tail"},
            }
            patches = _patch_row_from_tail(row, tail, evidence)
            for p in patches:
                report["patches"].append(p)
            block_patch_count += len(patches)
        if block_patch_count:
            details = block.setdefault("detalhes", {})
            if isinstance(details, dict):
                details.setdefault("public_token_fidelity", {})
                details["public_token_fidelity"].update({"version": CURRENT_RELEASE, "patch_count": block_patch_count, "pages": pages})
                try:
                    details["math_status"] = compute_component_math(block)
                except Exception:
                    pass
    report["patches_applied"] = len(report["patches"])
    result.setdefault("meta", {}).setdefault("performance", {})["public_token_fidelity"] = report
    result.setdefault("documento_correcao", {})["public_token_fidelity"] = {k: v for k, v in report.items() if k != "patches"}
    result.setdefault("documento_evidencias", {})["public_token_fidelity_patches"] = report["patches"][:300]
    return result, report


def apply_public_token_fidelity_bytes(pdf_bytes: bytes, result: Dict[str, Any], options: Dict[str, Any] | None = None):
    with PdfDocumentSession(pdf_bytes) as session:
        return apply_public_token_fidelity(result, pdf_session=session, options=options or {})


def apply_public_token_fidelity_file(file_path: str | Path, result: Dict[str, Any], options: Dict[str, Any] | None = None):
    return apply_public_token_fidelity_bytes(Path(file_path).read_bytes(), result, options or {})
