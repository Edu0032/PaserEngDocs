from __future__ import annotations

"""Raw occurrence context parser (v61.0.43).

When a codigo+banco occurrence appears outside a known table interval we do not
force table bands.  We keep the raw line/block and extract weak but useful
candidate fields from local text.  These candidates have lower confidence and
must be confirmed by the puzzle/closure layers before public writes.
"""

import re
from typing import Any, Dict, List

VERSION = "v61.0.75-correction-output-contract-and-review-index"

_NUM_RE = re.compile(r"(?<![A-Za-z0-9])(?:\d{1,3}(?:\.\d{3})+|\d+),\d{1,7}(?![A-Za-z0-9])")
_UNIT_RE = re.compile(r"\b(m²|m2|m³|m3|m|cm|mm|km|un|und|h|kg|t|t\.km|m³\.km|m3\.km|mês|mes|vb|cj)\b", re.I)
_UNIT_TOKENS = {"M", "M2", "M²", "M3", "M³", "CM", "MM", "KM", "UN", "UND", "H", "KG", "T", "T.KM", "M³.KM", "M3.KM", "MÊS", "MES", "VB", "CJ"}


def _clean(value: Any) -> str:
    return " ".join(str(value or "").replace("\u00a0", " ").split())



def _safe_unit_from_text(raw: str) -> str:
    # Avoid false positives inside service descriptions such as "CM-30" or
    # "DN 25 MM X 3/4" when a standalone unit appears later in the row.  Prefer
    # exact standalone tokens and scan from right to left because quantity/unit
    # columns usually appear after the description.
    tokens = re.findall(r"[A-Za-zÀ-ÿ0-9²³.]+", raw or "")
    for token in reversed(tokens):
        norm = token.upper().replace("M2", "M²").replace("M3", "M³")
        if norm in _UNIT_TOKENS:
            return norm.lower().replace("m2", "m²").replace("m3", "m³")
    match = _UNIT_RE.search(raw or "")
    if not match:
        return ""
    # reject unit-like substring in hyphenated/digit code context (CM-30)
    start, end = match.span()
    before = raw[start - 1] if start > 0 else " "
    after = raw[end] if end < len(raw) else " "
    if before in "-/" or after in "-/0123456789":
        return ""
    unit = match.group(1)
    return unit.lower().replace("m2", "m²").replace("m3", "m³")

def parse_raw_occurrence_context(text: str, codigo: str = "", banco: str = "") -> Dict[str, Any]:
    raw = _clean(text)
    nums: List[str] = _NUM_RE.findall(raw)
    unit = _safe_unit_from_text(raw)
    # Description is intentionally approximate for raw contexts: remove the id,
    # common bank token, units and numeric tail, but preserve public punctuation.
    desc = raw
    for token in [codigo, banco, "SINAPI", "SICRO", "PRÓPRIO", "PROPRIO", "CPU"]:
        if token:
            desc = re.sub(re.escape(str(token)), " ", desc, flags=re.I)
    desc = _NUM_RE.sub(" ", desc)
    if unit:
        desc = re.sub(r"\b" + re.escape(unit) + r"\b", " ", desc, flags=re.I)
    desc = _clean(desc.strip("-:;,. "))
    fields: Dict[str, str] = {}
    if len(desc) >= 3:
        fields["descricao"] = desc
        fields["especificacao"] = desc
    if unit:
        fields["und"] = unit.lower()
    if nums:
        # Raw occurrence numbers are weak: keep all tokens and assign common hints.
        # Label words such as Valor/Total make the hints stronger even when the
        # occurrence is not in a table and has only two numeric tokens.
        fields["numeric_candidates"] = nums  # type: ignore[assignment]
        lower = raw.lower()
        if len(nums) >= 1:
            fields["quant"] = nums[0]
        if len(nums) >= 2:
            fields["valor_unit"] = nums[-2] if len(nums) >= 3 else nums[1]
            fields["custo_unitario_com_bdi"] = fields["valor_unit"]
        if len(nums) >= 3 or "total" in lower or "custo parcial" in lower:
            fields["total"] = nums[-1]
            fields["custo_parcial"] = nums[-1]
        if "valor" in lower and len(nums) >= 1:
            # Prefer the number following a Valor label when no table band exists.
            fields["valor_unit"] = nums[-2] if len(nums) >= 2 and ("total" in lower or "custo parcial" in lower) else nums[-1]
            fields["custo_unitario_com_bdi"] = fields["valor_unit"]
    return {"version": VERSION, "raw_text": raw, "fields": fields, "confidence": 0.70 if fields else 0.55}
