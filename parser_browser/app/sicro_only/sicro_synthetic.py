from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .sicro_engine import BANK_RE, NUM_RE, SicroEngine, clean, normalize_code, parse_decimal
from .sicro_geometry import extract_pymupdf_lines


class SicroSyntheticReferenceExtractor:
    """Optional reference extractor for SICRO rows present in orçamento sintético.

    It is opportunistic: auxiliary SICRO compositions often do not appear in the
    synthetic budget, so absence of a reference is never an error.
    """

    def __init__(self, engine: SicroEngine | None = None):
        self.engine = engine or SicroEngine()

    def extract_refs(self, pdf_path: str | Path, start_page: int = 1, end_page: int = 6) -> Dict[str, Dict[str, Any]]:
        refs: Dict[str, Dict[str, Any]] = {}
        lines = extract_pymupdf_lines(pdf_path, start_page, end_page)
        i = 0
        while i < len(lines):
            line = lines[i]
            text = line.text
            if "SICRO" not in text.upper():
                i += 1
                continue
            m = re.search(rf"(?P<item>\d+(?:\.\d+)*)\s+(?P<code>\d{{7}})\s+(?P<bank>{BANK_RE})\s+(?P<body>.+)$", text, flags=re.I)
            if not m:
                i += 1
                continue
            body = clean(m.group("body"))
            tail = None
            consumed = 1
            # Tail from orçamento sintético: und quant custo_sem_bdi custo_com_bdi custo_parcial.
            for extra in range(0, 4):
                candidate = body if extra == 0 else clean(body + " " + " ".join(lines[i + j].text for j in range(1, extra + 1) if i + j < len(lines) and lines[i + j].page == line.page))
                tail = re.search(rf"\s(?P<unit>\S{{1,8}})\s+(?P<quant>{NUM_RE})\s+(?P<sem>{NUM_RE})\s+(?P<com>{NUM_RE})\s+(?P<parcial>{NUM_RE})\s*$", candidate)
                if tail:
                    body = candidate
                    consumed = extra + 1
                    break
            if not tail and i > 0 and lines[i - 1].page == line.page:
                # Some synthetic rows have right-side numeric columns slightly above
                # the left-side description; PyMuPDF emits the numeric tail first.
                prev = lines[i - 1].text
                if re.fullmatch(rf"(?:{NUM_RE}\s+){{3,}}{NUM_RE}", prev):
                    candidate = clean(body + " " + prev)
                    tail = re.search(rf"\s(?P<unit>\S{{1,8}})\s+(?P<quant>{NUM_RE})\s+(?P<sem>{NUM_RE})\s+(?P<com>{NUM_RE})\s+(?P<parcial>{NUM_RE})\s*$", candidate)
                    if tail:
                        body = candidate
            if not tail:
                i += 1
                continue
            unit = tail.group("unit")
            if not self.engine.is_unit(unit, "principal"):
                continue
            desc = clean(body[:tail.start()])
            code = normalize_code(m.group("code"))
            refs[code] = {
                "item": m.group("item"),
                "codigo": code,
                "banco": self.engine.normalize_bank(m.group("bank")),
                "descricao": desc,
                "unidade": unit,
                "quantidade_orcamento": tail.group("quant"),
                "custo_unitario_sem_bdi": tail.group("sem"),
                "custo_unitario_com_bdi": tail.group("com"),
                "custo_parcial": tail.group("parcial"),
                "_evidence": line.evidence(),
            }
            i += consumed
        return refs


def compare_compositions_with_synthetic(result: Dict[str, Any], refs_by_code: Dict[str, Dict[str, Any]], tolerance_abs: Decimal = Decimal("0.08")) -> Dict[str, Any]:
    comparisons: Dict[str, Any] = {}
    issues: List[Dict[str, Any]] = []
    for comp_key, comp in (result.get("composicoes") or {}).items():
        principal = comp.get("principal") or {}
        code = str(principal.get("codigo") or "")
        ref = refs_by_code.get(code)
        if not ref:
            comparisons[comp_key] = {"status": "sem_referencia_no_sintetico", "note": "normal para composições auxiliares"}
            continue
        unit_cost = parse_decimal(principal.get("custo_unitario"))
        sem_bdi = parse_decimal(ref.get("custo_unitario_sem_bdi"))
        quant = parse_decimal(ref.get("quantidade_orcamento"))
        com_bdi = parse_decimal(ref.get("custo_unitario_com_bdi"))
        parcial = parse_decimal(ref.get("custo_parcial"))
        status = "ok"
        details: Dict[str, Any] = {"referencia": ref}
        if unit_cost is not None and sem_bdi is not None:
            delta = abs(unit_cost - sem_bdi)
            details["preco_unitario_vs_sintetico_sem_bdi"] = {"delta": str(delta), "ok": delta <= tolerance_abs}
            if delta > tolerance_abs:
                status = "divergente"
        if quant is not None and com_bdi is not None and parcial is not None:
            calc = quant * com_bdi
            delta = abs(calc - parcial)
            details["quantidade_x_com_bdi_vs_parcial"] = {"calculado": str(calc), "delta": str(delta), "ok": delta <= Decimal("0.15")}
            if delta > Decimal("0.15"):
                status = "divergente"
        comparisons[comp_key] = {"status": status, **details}
        if status != "ok":
            issues.append({"composicao": comp_key, "tipo": "sintetico_divergente", "details": details})
    return {"ok": not issues, "comparisons": comparisons, "issues": issues, "reference_count": len(refs_by_code)}
