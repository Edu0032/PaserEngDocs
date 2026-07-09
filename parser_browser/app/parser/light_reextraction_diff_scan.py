from __future__ import annotations

"""Strategic PDF-vs-JSON leftover scan.

Single purpose: detect physical code/bank occurrences visible in the PDF that may
not have a destination in the public JSON.  It is diagnostic and does not write
public values.  The scan is occurrence-aware: a repeated code is not considered
matched merely because it exists somewhere in the JSON; page, bank, tail tokens,
description similarity and neighboring composition blocks are used to decide
whether a physical row is already represented.
"""

import re
import tempfile
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from app.config.version import CURRENT_RELEASE

_CODE_RE = re.compile(r"\b(?:\d{5,7}(?:/\d{3})?|\d{6,7}|[A-Z]{2,}[A-Z0-9. -]{1,12}\d{1,3})\b")
_BANK_RE = re.compile(r"\b(SINAPI|SICRO|PR[ÓO]PRIO|PRÓPRIO)\b", re.I)
_NATURE_RE = re.compile(r"\b(Composi[cç][aã]o(?:\s+Auxiliar)?|Insumo)\b", re.I)
_TAIL_RE = re.compile(
    r"(?P<und>[A-Za-zÀ-ÿ%²³0-9./]+)\s+"
    r"(?P<quant>-?\d{1,3}(?:\.\d{3})*,\d+|-?\d+,\d+|-?\d+)\s+"
    r"(?P<valor_unit>-?\d{1,3}(?:\.\d{3})*,\d{2,7}|-?\d+,\d{2,7}|-?\d+)\s+"
    r"(?P<total>-?\d{1,3}(?:\.\d{3})*,\d{2,7}|-?\d+,\d{2,7}|-?\d+)\s*$"
)


def _norm_code(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _norm_bank(value: Any) -> str:
    text = str(value or "").upper().replace("Ó", "O")
    if "PROPRIO" in text:
        return "PROPRIO"
    return text.strip()


def _norm_text(value: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9À-Ü ]+", " ", str(value or "").upper())).strip()


def _numeric_signature(fields: Dict[str, Any]) -> Tuple[str, str, str, str]:
    return tuple(str(fields.get(k) or "").strip() for k in ("und", "quant", "valor_unit", "total"))  # type: ignore[return-value]


def _tail_match(a: Tuple[str, str, str, str], b: Tuple[str, str, str, str]) -> bool:
    # Prefer exact full tail, but allow value-unit+total confirmation because
    # quantity/total may legitimately differ across budget vs composition.
    if all(a) and all(b) and a == b:
        return True
    # In composition rows, valor_unit is usually the most stable cross-source
    # numeric; total is useful when page/block match also exists.
    return bool(a[2] and b[2] and a[2] == b[2] and (not a[3] or not b[3] or a[3] == b[3]))


def _desc_similarity(a: Any, b: Any) -> float:
    aa = _norm_text(a)
    bb = _norm_text(b)
    if not aa or not bb:
        return 0.0
    if aa in bb or bb in aa:
        return min(len(aa), len(bb)) / max(len(aa), len(bb))
    return SequenceMatcher(None, aa, bb).ratio()


def _row_fields(obj: Dict[str, Any]) -> Dict[str, Any]:
    return {k: obj.get(k) for k in ("und", "quant", "valor_unit", "total")}


def _collect_json_occurrences(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    occs: List[Dict[str, Any]] = []

    def add(obj: Dict[str, Any], *, path: List[Any], section: str, page_hint: Any = None, comp_key: str | None = None, row_group: str | None = None, row_index: Any = None) -> None:
        code = obj.get("codigo")
        bank = obj.get("banco") or obj.get("fonte") or obj.get("banco_coluna")
        code_norm = _norm_code(code)
        if not code_norm:
            return
        pages = []
        for p in (obj.get("pagina"), obj.get("page"), page_hint):
            if isinstance(p, int):
                pages.append(p)
        occs.append({
            "code_norm": code_norm,
            "codigo": code,
            "bank": _norm_bank(bank),
            "path": path[:],
            "section": section,
            "comp_key": comp_key,
            "row_group": row_group,
            "row_index": row_index,
            "pages": sorted(set(pages)),
            "descricao": obj.get("descricao") or obj.get("especificacao"),
            "tail": _numeric_signature(_row_fields(obj)),
        })

    # Budget leaves/nodes.
    def walk_budget(obj: Any, path: List[Any]) -> None:
        if isinstance(obj, dict):
            if obj.get("codigo"):
                add(obj, path=path, section="orcamento_sintetico")
            for k, v in obj.items():
                if isinstance(v, (dict, list)):
                    walk_budget(v, path + [k])
        elif isinstance(obj, list):
            for i, x in enumerate(obj):
                walk_budget(x, path + [i])

    walk_budget(result.get("orcamento_sintetico"), ["orcamento_sintetico"])

    comps = result.get("composicoes") if isinstance(result.get("composicoes"), dict) else {}
    families: List[Tuple[str, Dict[str, Any]]] = []
    if isinstance(comps, dict):
        for fam_name in ("sinapi_like", "sicro"):
            fam = comps.get(fam_name)
            if isinstance(fam, dict):
                families.append((fam_name, fam))
        families.append(("flat", comps))
    for fam_name, fam in families:
        for collection in ("principais", "auxiliares_globais"):
            blocks = fam.get(collection)
            if not isinstance(blocks, dict):
                continue
            for comp_key, block in blocks.items():
                if not isinstance(block, dict):
                    continue
                pages = block.get("paginas") if isinstance(block.get("paginas"), list) else []
                page_hint = block.get("pagina_inicio") or (pages[0] if pages else None)
                principal = block.get("principal") if isinstance(block.get("principal"), dict) else {}
                add(principal, path=["composicoes", fam_name, collection, comp_key, "principal"], section="composicoes_analiticas", page_hint=page_hint, comp_key=str(comp_key), row_group="principal")
                for group in ("composicoes_auxiliares", "insumos"):
                    rows = block.get(group)
                    if isinstance(rows, list):
                        for idx, row in enumerate(rows):
                            if isinstance(row, dict):
                                add(row, path=["composicoes", fam_name, collection, comp_key, group, idx], section="composicoes_analiticas", page_hint=page_hint, comp_key=str(comp_key), row_group=group, row_index=idx)
    return occs


def _collect_composition_blocks(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    comps = result.get("composicoes") if isinstance(result.get("composicoes"), dict) else {}
    principals = comps.get("principais") if isinstance(comps, dict) else {}
    if not isinstance(principals, dict):
        principals = ((comps.get("sinapi_like") or {}).get("principais") or {}) if isinstance(comps, dict) else {}
    blocks: List[Dict[str, Any]] = []
    if not isinstance(principals, dict):
        return blocks
    for key, comp in principals.items():
        if not isinstance(comp, dict):
            continue
        pages = comp.get("paginas") if isinstance(comp.get("paginas"), list) else []
        start = comp.get("pagina_inicio") or (min(pages) if pages else None)
        end = comp.get("pagina_fim") or (max(pages) if pages else start)
        principal = comp.get("principal") if isinstance(comp.get("principal"), dict) else {}
        blocks.append({
            "key": str(key),
            "item": comp.get("item"),
            "codigo": principal.get("codigo"),
            "banco": principal.get("banco"),
            "page_start": start,
            "page_end": end,
        })
    return blocks


def _candidate_blocks_for_page(page: int, blocks: List[Dict[str, Any]], *, limit: int = 5) -> List[Dict[str, Any]]:
    scored: List[Tuple[int, Dict[str, Any]]] = []
    for b in blocks:
        start = b.get("page_start")
        end = b.get("page_end") or start
        if not isinstance(start, int):
            continue
        dist = 0 if start <= page <= int(end or start) else min(abs(page - int(start)), abs(page - int(end or start)))
        scored.append((dist, b))
    scored.sort(key=lambda x: (x[0], str(x[1].get("key"))))
    out: List[Dict[str, Any]] = []
    for dist, b in scored[:limit]:
        out.append({k: v for k, v in {"composition": b.get("key"), "item": b.get("item"), "codigo": b.get("codigo"), "banco": b.get("banco"), "page_start": b.get("page_start"), "page_end": b.get("page_end"), "distance_pages": dist}.items() if v not in (None, "", [], {})})
    return out


def _extract_text_by_page(file_path: str | Path):
    try:
        import fitz  # type: ignore
    except Exception:
        return []
    pages = []
    try:
        with fitz.open(str(file_path)) as doc:
            for i, page in enumerate(doc, start=1):
                pages.append((i, page.get_text("text") or ""))
    except Exception:
        return []
    return pages


def _parse_physical_line(line: str) -> Dict[str, Any]:
    clean = " ".join((line or "").split())
    nat = None
    mn = _NATURE_RE.search(clean)
    if mn:
        nat = mn.group(1)
    mb = _BANK_RE.search(clean)
    bank = mb.group(1).upper().replace("Ó", "O") if mb else ""
    code = ""
    code_match = None
    if mb:
        prefix = clean[: mb.start()]
        for m in _CODE_RE.finditer(prefix):
            code_match = m
        if code_match:
            code = code_match.group(0)
    if not code:
        for m in _CODE_RE.finditer(clean):
            if _BANK_RE.fullmatch(m.group(0) or ""):
                continue
            code = m.group(0)
            break
    tail: Dict[str, Any] = {}
    mt = _TAIL_RE.search(clean)
    desc = clean
    if mt:
        tail = mt.groupdict()
        desc = clean[: mt.start()].strip()
    if bank and bank in desc.upper().replace("Ó", "O"):
        parts = re.split(r"\b(?:SINAPI|SICRO|PR[ÓO]PRIO|PRÓPRIO)\b", desc, maxsplit=1, flags=re.I)
        if len(parts) == 2:
            desc = parts[1].strip()
    if nat:
        desc = re.sub(r"^" + re.escape(nat) + r"\s+", "", desc, flags=re.I).strip()
    if code:
        desc = re.sub(re.escape(code), "", desc, count=1).strip()
    return {
        "natureza": nat,
        "codigo": code,
        "codigo_norm": _norm_code(code),
        "banco": bank,
        "descricao_preview": desc[:220],
        "und": tail.get("und"),
        "quant": tail.get("quant"),
        "valor_unit": tail.get("valor_unit"),
        "total": tail.get("total"),
        "tail_signature": _numeric_signature(tail),
        "line_preview": clean[:260],
        "columns_detected": [k for k in ("codigo", "banco", "descricao_preview", "und", "quant", "valor_unit", "total") if (k == "descricao_preview" and desc) or (k != "descricao_preview" and (tail.get(k) or (k == "codigo" and code) or (k == "banco" and bank)))],
    }


def _compatible_bank(physical_bank: str, json_bank: str) -> bool:
    pb = _norm_bank(physical_bank)
    jb = _norm_bank(json_bank)
    if not pb or not jb:
        return True
    return pb == jb


def _match_occurrence(parsed: Dict[str, Any], page_no: int, occurrences: List[Dict[str, Any]]) -> Tuple[bool, List[Dict[str, Any]], str]:
    code = parsed.get("codigo_norm") or ""
    bank = _norm_bank(parsed.get("banco"))
    tail = parsed.get("tail_signature") or ("", "", "", "")
    same_code = [o for o in occurrences if o.get("code_norm") == code and _compatible_bank(bank, str(o.get("bank") or ""))]
    if not same_code:
        return False, [], "no_code_bank_match"
    scored: List[Tuple[float, Dict[str, Any], List[str]]] = []
    for occ in same_code:
        score = 0.0
        reasons: List[str] = []
        pages = occ.get("pages") or []
        if page_no in pages:
            score += 0.35; reasons.append("same_page")
        if bank and _norm_bank(occ.get("bank")) == bank:
            score += 0.2; reasons.append("same_bank")
        if _tail_match(tail, occ.get("tail") or ("", "", "", "")):
            score += 0.35; reasons.append("compatible_numeric_tail")
        sim = _desc_similarity(parsed.get("descricao_preview"), occ.get("descricao"))
        if sim >= 0.72:
            score += min(0.25, sim * 0.25); reasons.append(f"description_similarity:{sim:.2f}")
        # If the physical row has no numeric tail, code+bank+page or strong desc is enough.
        if not any(tail) and (page_no in pages or sim >= 0.86):
            score += 0.25; reasons.append("non_numeric_anchor_context_match")
        scored.append((score, occ, reasons))
    scored.sort(key=lambda x: x[0], reverse=True)
    best_score = scored[0][0]
    best = [{"score": round(s, 3), "path": o.get("path"), "comp_key": o.get("comp_key"), "row_group": o.get("row_group"), "row_index": o.get("row_index"), "reasons": r} for s, o, r in scored[:5]]
    return best_score >= 0.55, best, "matched_by_occurrence_context" if best_score >= 0.55 else "same_code_but_no_occurrence_context_match"


def build_light_reextraction_diff_scan_file(file_path: str, result: Dict[str, Any], options: Dict[str, Any] | None = None) -> Dict[str, Any]:
    options = dict(options or {})
    occurrences = _collect_json_occurrences(result if isinstance(result, dict) else {})
    blocks = _collect_composition_blocks(result if isinstance(result, dict) else {})
    samples: List[Dict[str, Any]] = []
    scanned_pages = 0
    physical_code_count = 0
    matched_occurrence_count = 0
    missing_occurrence_count = 0
    max_pages = int(options.get("light_diff_scan_max_pages") or 0)
    max_samples = int(options.get("light_diff_scan_max_samples") or 80)

    for page_no, text in _extract_text_by_page(file_path):
        if max_pages and scanned_pages >= max_pages:
            break
        scanned_pages += 1
        for line in (text or "").splitlines():
            if not _BANK_RE.search(line):
                continue
            parsed = _parse_physical_line(line)
            code = parsed.get("codigo_norm") or ""
            bank = _norm_bank(parsed.get("banco"))
            if not code or len(code) < 4 or code.startswith(("SINAPI", "SICRO", "PROPRIO", "PRÓPRIO")):
                continue
            physical_code_count += 1
            is_present, matched_candidates, reason = _match_occurrence(parsed, page_no, occurrences)
            if is_present:
                matched_occurrence_count += 1
                continue
            missing_occurrence_count += 1
            if len(samples) < max_samples:
                candidates = _candidate_blocks_for_page(page_no, blocks)
                samples.append({
                    "id": f"missing_pdf_occurrence::{page_no}::{code}::{bank}::{missing_occurrence_count}",
                    "tipo": "possible_line_left_behind",
                    "gravidade": "warning",
                    "page": page_no,
                    "codigo_norm": code,
                    "banco": bank,
                    "match_reason": reason,
                    "json_candidate_matches": matched_candidates,
                    "parsed_columns": {k: v for k, v in parsed.items() if k in {"natureza", "codigo", "banco", "descricao_preview", "und", "quant", "valor_unit", "total", "columns_detected"} and v not in (None, "", [], {})},
                    "line_preview": parsed.get("line_preview"),
                    "possible_destination_candidates": candidates,
                    "verification_policy": "diagnostic_only_occurrence_aware_pdf_vs_json_scan_then_review_with_bands_and_neighboring_compositions",
                    "recommended_action": "review_or_attach_to_best_neighboring_composition_if_bands_block_context_and_math_confirm",
                    "crop_hint": {"page": page_no, "ui_action": "open_page_and_focus_line", "line_preview": parsed.get("line_preview")},
                })
    status = "ok" if not samples else "needs_review"
    report = {
        "version": CURRENT_RELEASE,
        "status": status,
        "attempted": True,
        "scope": "strategic_left_behind_occurrence_scan",
        "scanned_pages": scanned_pages,
        "json_occurrence_count": len(occurrences),
        "physical_code_mentions": physical_code_count,
        "matched_occurrence_mentions": matched_occurrence_count,
        "potential_missing_occurrence_count": missing_occurrence_count,
        "potential_missing_code_count": len({(s.get('codigo_norm'), s.get('banco')) for s in samples}),
        "potential_missing_lines": samples,
        "policy": "only_detects_possible_left_behind_content_never_writes_public_fields",
    }
    ev = result.setdefault("documento_evidencias", {})
    ev["light_reextraction_diff_scan"] = report
    result.setdefault("meta", {}).setdefault("performance", {})["light_reextraction_diff_scan"] = {k: v for k, v in report.items() if k != "potential_missing_lines"}
    if samples:
        corr = result.setdefault("documento_correcao", {})
        corr.setdefault("possible_left_behind_lines", [])
        existing = {x.get("id") for x in corr["possible_left_behind_lines"] if isinstance(x, dict)}
        for sample in samples[:40]:
            if sample.get("id") not in existing:
                corr["possible_left_behind_lines"].append(sample)
    return report


def build_light_reextraction_diff_scan_bytes(pdf_bytes: bytes, result: Dict[str, Any], options: Dict[str, Any] | None = None) -> Dict[str, Any]:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes or b"")
        path = tmp.name
    try:
        return build_light_reextraction_diff_scan_file(path, result, options)
    finally:
        try:
            Path(path).unlink(missing_ok=True)
        except Exception:
            pass
