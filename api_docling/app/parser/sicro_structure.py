from __future__ import annotations

import re
from typing import Any, Dict, List

_SECTION_RE = re.compile(r"^[A-F]$")


def classify_sicro_rows(rows: List[List[str]]) -> Dict[str, Any]:
    sections: Dict[str, int] = {}
    financial_hits: List[str] = []
    for row in rows or []:
        cells = [str(c or "").strip() for c in row]
        if not any(cells):
            continue
        first = cells[0].upper() if cells else ""
        if _SECTION_RE.fullmatch(first):
            sections[first] = sections.get(first, 0) + 1
        joined = " ".join(cells).upper()
        for label in (
            "CUSTO HORÁRIO DE EQUIPAMENTOS",
            "CUSTO HORÁRIO DA MÃO DE OBRA",
            "CUSTO HORÁRIO DE EXECUÇÃO",
            "PRODUÇÃO DE EQUIPE",
            "VALOR COM BDI",
        ):
            if label in joined and label not in financial_hits:
                financial_hits.append(label)
    return {
        "fixed_sections_detected": sorted(sections),
        "section_hits": sections,
        "financial_labels_detected": financial_hits,
        "matched": bool(sections or financial_hits),
    }
