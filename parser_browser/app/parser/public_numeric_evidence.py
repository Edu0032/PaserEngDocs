from __future__ import annotations

"""Evidence-first audit for public numeric fields.

Global policy, no document-specific hardcode:
- public financial/numeric fields should be traceable to physical PDF text;
- calculations may validate/rank but do not create public values;
- when a PDF is available, this stage builds a compact field ledger and metrics
  that the real-flow quality gate can use.

This module intentionally does not touch SICRO public rows.  The native SICRO
engine owns SICRO semantics and validation; this stage covers budget and
SINAPI-like composition public fields only.
"""

import re
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

from app.config.version import CURRENT_RELEASE
from app.core.pdf_session import PdfDocumentSession

BUDGET_PUBLIC_FIELDS = (
    "quant",
    "custo_unitario_sem_bdi",
    "custo_unitario_com_bdi",
    "custo_parcial",
    "custo_total",
)
COMPOSITION_PUBLIC_FIELDS = ("quant", "valor_unit", "total")
COMPOSITION_REQUIRED_FIELDS = ("und", "quant", "valor_unit", "total")


def _clean(value: Any) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split()).strip()


def _norm(value: Any) -> str:
    import unicodedata

    text = _clean(value).upper()
    return "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))


def _norm_code(value: Any) -> str:
    return re.sub(r"[^0-9A-Z]", "", _norm(value))


def _code_regex(value: Any) -> str:
    text = _clean(value)
    if not text:
        return r"a^"
    parts: List[str] = []
    for ch in text:
        if ch.isspace():
            parts.append(r"\s*")
        elif ch in {"-", "/", "."}:
            parts.append(r"\s*" + re.escape(ch) + r"\s*")
        else:
            parts.append(re.escape(ch))
    return "".join(parts)


def _value_regex(value: Any) -> str:
    text = _clean(value)
    if not text:
        return r"a^"
    # PDF text may collapse thousands spacing but generally preserves dots and
    # commas.  Allow whitespace around punctuation so tokens split by extractor
    # still count as physical evidence.
    parts: List[str] = []
    for ch in text:
        if ch.isspace():
            parts.append(r"\s+")
        elif ch in {".", ","}:
            parts.append(r"\s*" + re.escape(ch) + r"\s*")
        else:
            parts.append(re.escape(ch))
    return "".join(parts)


def _window(text: str, center: int, left: int = 220, right: int = 520) -> str:
    start = max(0, center - left)
    end = min(len(text), center + right)
    return _clean(text[start:end])


def _iter_budget_nodes(nodes: Iterable[Any], path: str = "orcamento_sintetico.itens_raiz") -> Iterator[Tuple[str, Dict[str, Any]]]:
    if not isinstance(nodes, list):
        return
    for idx, node in enumerate(nodes):
        if not isinstance(node, dict):
            continue
        cur = f"{path}.{idx}"
        yield cur, node
        filhos = node.get("filhos")
        if isinstance(filhos, list):
            yield from _iter_budget_nodes(filhos, f"{cur}.filhos")


def _iter_composition_blocks(composicoes: Dict[str, Any]) -> Iterator[Tuple[str, str, str, Dict[str, Any]]]:
    if not isinstance(composicoes, dict):
        return
    seen: set[int] = set()
    for family in ("sinapi_like",):
        fam = composicoes.get(family)
        if isinstance(fam, dict):
            for collection in ("principais", "auxiliares_globais"):
                blocks = fam.get(collection)
                if isinstance(blocks, dict):
                    for key, block in blocks.items():
                        if isinstance(block, dict) and id(block) not in seen:
                            seen.add(id(block))
                            yield family, collection, str(key), block
    # Legacy flat model before final public split.
    for collection in ("principais", "auxiliares_globais"):
        blocks = composicoes.get(collection)
        if isinstance(blocks, dict):
            for key, block in blocks.items():
                if not isinstance(block, dict) or id(block) in seen:
                    continue
                principal = block.get("principal") if isinstance(block.get("principal"), dict) else {}
                bank = _norm(principal.get("banco") or principal.get("fonte"))
                if bank.startswith("SICRO"):
                    continue
                seen.add(id(block))
                yield "sinapi_like", collection, str(key), block


def _iter_composition_rows(block: Dict[str, Any]) -> Iterator[Tuple[str, Optional[int], Dict[str, Any]]]:
    principal = block.get("principal") if isinstance(block.get("principal"), dict) else None
    if principal is not None:
        yield "principal", None, principal
    for group in ("composicoes_auxiliares", "insumos"):
        rows = block.get(group)
        if isinstance(rows, list):
            for idx, row in enumerate(rows):
                if isinstance(row, dict):
                    yield group, idx, row


def _page_numbers_for_block(block: Dict[str, Any], fallback_pages: List[int]) -> List[int]:
    pages: List[int] = []
    for src in (block, block.get("detalhes") if isinstance(block.get("detalhes"), dict) else {}):
        if not isinstance(src, dict):
            continue
        raw = src.get("paginas")
        if isinstance(raw, list):
            for item in raw:
                try:
                    p = int(item)
                    if p > 0 and p not in pages:
                        pages.append(p)
                except Exception:
                    pass
        for key in ("pagina_inicio", "pagina_fim", "page", "page_hint"):
            try:
                p = int(src.get(key) or 0)
                if p > 0 and p not in pages:
                    pages.append(p)
            except Exception:
                pass
    return sorted(pages or fallback_pages)


def _range_pages(options: Dict[str, Any] | None, name: str, default: Tuple[int, int]) -> List[int]:
    options = options or {}
    ranges = options.get("ranges") if isinstance(options.get("ranges"), dict) else {}
    raw = None
    if name == "budget":
        raw = ranges.get("budget") or ranges.get("orcamento")
    else:
        raw = ranges.get("compositions") or ranges.get("composicoes")
    if isinstance(raw, dict):
        try:
            start = int(raw.get("start") or raw.get("inicio") or default[0])
            end = int(raw.get("end") or raw.get("fim") or default[1])
            if start > 0 and end >= start:
                return list(range(start, end + 1))
        except Exception:
            pass
    return list(range(default[0], default[1] + 1))


def _get_page_text(pdf_session: PdfDocumentSession, cache: Dict[int, str], page: int) -> str:
    if page not in cache:
        try:
            cache[page] = str(pdf_session.get_page_text(page, engine="auto") or "")
        except Exception:
            cache[page] = ""
    return cache[page]


def _find_budget_evidence(page_texts: List[Tuple[int, str]], node: Dict[str, Any], field: str, value: str) -> Optional[Dict[str, Any]]:
    code = node.get("codigo")
    item = node.get("item")
    anchors: List[str] = []
    if code:
        anchors.append(_code_regex(code))
    if item:
        anchors.append(r"(?<!\d)" + re.escape(_clean(item)) + r"(?!\d)")
    val_pat = _value_regex(value)
    for page, text in page_texts:
        for anchor in anchors or [r""]:
            for m in re.finditer(anchor, text, flags=re.IGNORECASE):
                win = _window(text, m.start(), 700, 900)
                if re.search(val_pat, win, flags=re.IGNORECASE):
                    return {
                        "status": "found",
                        "source": "pdf_physical_text",
                        "section": "orcamento_sintetico",
                        "page": page,
                        "anchor": "codigo" if code else "item",
                        "anchor_value": _clean(code or item),
                        "line_text": win[:700],
                        "confidence": 0.96,
                    }
        # Totals/meta rows can lack a code; allow item+description/value in same
        # local text window.  Still physical text only.
        if not code and item and re.search(val_pat, text, flags=re.IGNORECASE):
            item_pat = r"(?<!\d)" + re.escape(_clean(item)) + r"(?!\d)"
            for m in re.finditer(item_pat, text, flags=re.IGNORECASE):
                win = _window(text, m.start(), 350, 450)
                if re.search(val_pat, win, flags=re.IGNORECASE):
                    return {
                        "status": "found",
                        "source": "pdf_physical_text",
                        "section": "orcamento_sintetico",
                        "page": page,
                        "anchor": "item",
                        "anchor_value": _clean(item),
                        "line_text": win[:700],
                        "confidence": 0.93,
                    }
    return None


def _find_comp_evidence(page_texts: List[Tuple[int, str]], row: Dict[str, Any], field: str, value: str) -> Optional[Dict[str, Any]]:
    code = row.get("codigo")
    bank = row.get("banco") or row.get("fonte") or ""
    if not code:
        return None
    code_pat = _code_regex(code)
    val_pat = _value_regex(value)
    bank_norm = _norm(bank)
    for page, text in page_texts:
        for m in re.finditer(code_pat, text, flags=re.IGNORECASE):
            win = _window(text, m.start(), 120, 900)
            if bank_norm and bank_norm not in _norm(win):
                # If bank is not in the local text window, continue but keep it
                # soft because PDF extraction can split columns.  A direct code
                # + value hit still can be evidence with slightly lower confidence.
                confidence = 0.88
            else:
                confidence = 0.97
            if re.search(val_pat, win, flags=re.IGNORECASE):
                return {
                    "status": "found",
                    "source": "pdf_physical_text",
                    "section": "composicoes_analiticas",
                    "page": page,
                    "anchor": "codigo_banco",
                    "anchor_value": f"{_clean(code)}|{_clean(bank)}",
                    "line_text": win[:900],
                    "confidence": confidence,
                }
    return None




def _target_blocks_from_result(result: Dict[str, Any], options: Dict[str, Any] | None = None) -> set[str]:
    targets: set[str] = set()
    options = options or {}
    for raw in (options.get("target_blocks"), options.get("target_compositions")):
        if isinstance(raw, list):
            targets.update(str(x) for x in raw if str(x or "").strip())
        elif isinstance(raw, str) and raw.strip():
            targets.add(raw.strip())
    gate = ((result.get("auditoria_final") or {}).get("quality_gate") or {}) if isinstance(result.get("auditoria_final"), dict) else {}
    for issue in list((gate or {}).get("issues") or []):
        if isinstance(issue, dict):
            block = issue.get("block") or issue.get("composition") or issue.get("chave")
            if block:
                targets.add(str(block))
    return targets

def build_public_numeric_evidence(
    result: Dict[str, Any],
    *,
    pdf_session: PdfDocumentSession,
    options: Dict[str, Any] | None = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Attach an evidence ledger and metrics for public numeric fields.

    The function mutates and returns ``result`` for browser/Pyodide efficiency.
    """
    options = options or {}
    strict = bool(options.get("strict_public_evidence_required", False))
    page_cache: Dict[int, str] = {}
    budget_pages = _range_pages(options, "budget", (1, 6))
    comp_default_pages = _range_pages(options, "compositions", (1, 12))
    target_blocks = _target_blocks_from_result(result, options)
    target_blocks = _target_blocks_from_result(result, options)
    acc = options.get("accuracy_profile") if isinstance(options.get("accuracy_profile"), dict) else {}
    full_scan = bool(strict or options.get("public_evidence_full_scan") or acc.get("public_evidence_full_scan"))

    evidence_doc = result.setdefault("documento_evidencias", {})
    if not isinstance(evidence_doc, dict):
        result["documento_evidencias"] = evidence_doc = {}
    # Avoid a heavy full-document evidence sweep in the real Lovable flow unless
    # it is explicitly requested or strict mode is enabled.  Existing evidence
    # is preserved; focused target blocks are still checked.
    if not full_scan and not target_blocks:
        previous = evidence_doc.get("public_numeric_evidence_report") if isinstance(evidence_doc.get("public_numeric_evidence_report"), dict) else {}
        report = dict(previous or {})
        report.update({
            "version": CURRENT_RELEASE,
            "attempted": True,
            "skipped_full_scan": True,
            "reason": "no_current_problem_blocks_and_full_public_evidence_not_requested",
            "evidence_gate_mode": "advisory_non_blocking",
            "scope": "preserved_previous_or_noop",
            "target_blocks": [],
            "strict_public_evidence_required": False,
        })
        evidence_doc["public_numeric_evidence_report"] = report
        result.setdefault("meta", {}).setdefault("performance", {})["public_numeric_evidence"] = report
        return result, report

    budget_texts = [(p, _get_page_text(pdf_session, page_cache, p)) for p in budget_pages]

    ledger: List[Dict[str, Any]] = []
    missing: List[Dict[str, Any]] = []
    public_numeric_total = 0

    # Budget evidence: all public numeric leaves/subtotals visible in the budget tree.
    budget = result.get("orcamento_sintetico") if isinstance(result.get("orcamento_sintetico"), dict) else {}
    for path, node in _iter_budget_nodes(budget.get("itens_raiz") or []):
        for field in BUDGET_PUBLIC_FIELDS:
            value = _clean(node.get(field))
            if not value:
                continue
            public_numeric_total += 1
            ev = _find_budget_evidence(budget_texts, node, field, value)
            entry = {
                "path": f"{path}.{field}",
                "entity": "orcamento_sintetico",
                "item": node.get("item"),
                "codigo": node.get("codigo"),
                "field": field,
                "value": value,
                "evidence": ev or {"status": "not_found", "source": "public_numeric_evidence"},
            }
            ledger.append(entry)
            if not ev:
                missing.append({"severity": "blocking" if strict else "warning", "blocks_json_ok": bool(strict), **entry})

    # Composition evidence: SINAPI-like only; SICRO native motor remains untouched.
    composicoes = result.get("composicoes") if isinstance(result.get("composicoes"), dict) else {}
    for _family, collection, key, block in _iter_composition_blocks(composicoes):
        if target_blocks and str(key) not in target_blocks:
            continue
        pages = _page_numbers_for_block(block, comp_default_pages[:4])
        page_texts = [(p, _get_page_text(pdf_session, page_cache, p)) for p in pages]
        for group, idx, row in _iter_composition_rows(block):
            row_missing = [f for f in COMPOSITION_REQUIRED_FIELDS if row.get(f) in (None, "", [], {})]
            # Numeric fields and unit; unit is needed for row ownership even if not numeric.
            for field in COMPOSITION_REQUIRED_FIELDS:
                value = _clean(row.get(field))
                if not value:
                    continue
                if field in COMPOSITION_PUBLIC_FIELDS:
                    public_numeric_total += 1
                ev = _find_comp_evidence(page_texts, row, field, value)
                entry = {
                    "path": f"composicoes.{collection}.{key}.{group}.{'' if idx is None else idx}.{field}",
                    "entity": "composicao_sinapi_like",
                    "collection": collection,
                    "block": key,
                    "row_group": group,
                    "row_index": idx,
                    "codigo": row.get("codigo"),
                    "banco": row.get("banco"),
                    "field": field,
                    "value": value,
                    "evidence": ev or {"status": "not_found", "source": "public_numeric_evidence"},
                }
                ledger.append(entry)
                if field in COMPOSITION_PUBLIC_FIELDS and not ev:
                    missing.append({"severity": "blocking" if strict else "warning", "blocks_json_ok": bool(strict), **entry})
            if row_missing:
                missing.append({
                    "severity": "blocking",
                    "blocks_json_ok": True,
                    "code": "composition_required_field_missing",
                    "collection": collection,
                    "block": key,
                    "row_group": group,
                    "row_index": idx,
                    "codigo": row.get("codigo"),
                    "banco": row.get("banco"),
                    "missing": row_missing,
                })

    # Keep the ledger compact in the public JSON.  Full evidence lines are still
    # enough to prove source for fields; limit protects browser payloads.
    numeric_missing = [m for m in missing if m.get("field") in set(BUDGET_PUBLIC_FIELDS) | set(COMPOSITION_PUBLIC_FIELDS)]
    required_missing = [m for m in missing if m.get("code") == "composition_required_field_missing"]
    blocking_missing = [m for m in missing if m.get("blocks_json_ok")]
    report = {
        "version": CURRENT_RELEASE,
        "attempted": True,
        "policy": "public_numeric_fields_must_have_pdf_physical_evidence_math_is_audit_only",
        "evidence_gate_mode": "strict_blocking" if strict else "advisory_non_blocking",
        "scope": "targeted" if target_blocks else "full_public_json",
        "budget_pages": budget_pages,
        "composition_default_pages": comp_default_pages,
        "target_blocks": sorted(target_blocks),
        "fields_checked": len(ledger),
        "public_numeric_fields_checked": public_numeric_total,
        "public_numeric_without_primary_evidence_count": len(numeric_missing),
        "public_numeric_without_any_evidence_count": len(numeric_missing),
        "public_numeric_auxiliary_only_count": 0,
        "public_numeric_evidence_not_checked_count": 0,
        # Backward-compatible alias kept for Lovable dashboards.
        "public_numeric_without_evidence_count": len(numeric_missing),
        "required_rows_missing_count": len(required_missing),
        "strict_public_evidence_required": strict,
        "missing_evidence": missing[:200],
        "blocking_missing_evidence": blocking_missing[:200],
    }
    evidence_doc["public_numeric_fields"] = ledger[:1200]
    evidence_doc["public_numeric_evidence_report"] = report
    result.setdefault("meta", {}).setdefault("performance", {})["public_numeric_evidence"] = report
    return result, report


def build_public_numeric_evidence_bytes(pdf_bytes: bytes, result: Dict[str, Any], options: Dict[str, Any] | None = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    with PdfDocumentSession(pdf_bytes) as session:
        return build_public_numeric_evidence(result, pdf_session=session, options=options or {})


def build_public_numeric_evidence_file(file_path: str | Path, result: Dict[str, Any], options: Dict[str, Any] | None = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    data = Path(file_path).read_bytes()
    return build_public_numeric_evidence_bytes(data, result, options or {})
