from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re
from typing import Any, Dict

PTBR_NUM_RE = re.compile(r"^-?\d{1,3}(?:\.\d{3})*(?:,\d+)?$|^-?\d+(?:,\d+)?$")


def clean_numeric_text(value: Any) -> str:
    text = str(value or "").replace("\xa0", " ").strip()
    text = re.sub(r"\s+", " ", text)
    return text


def is_ptbr_number_text(value: Any) -> bool:
    text = clean_numeric_text(value).replace("R$", "").strip()
    return bool(text and PTBR_NUM_RE.fullmatch(text))


def ptbr_to_decimal(value: Any) -> Decimal | None:
    text = clean_numeric_text(value).replace("R$", "").replace(" ", "").strip()
    if not text:
        return None
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def decimal_scale(value: Any) -> int:
    text = clean_numeric_text(value).replace("R$", "").strip()
    if "," not in text:
        return 0
    return len(text.rsplit(",", 1)[1])


def numeric_source(value: Any) -> Dict[str, Any]:
    text = clean_numeric_text(value)
    dec = ptbr_to_decimal(text)
    return {
        "source_text": text,
        "decimal": format(dec, "f") if dec is not None else None,
        "scale": decimal_scale(text),
    }


def apply_numeric_sources_to_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Preserve the exact numeric text observed in the PDF when available.

    The parser may keep Decimal/float-like values internally for validation, but the final
    JSON must never collapse values such as ``600,2000`` into ``600``. SICRO rows store the
    original PDF tokens in ``detalhes.numeric_source``; this function writes those tokens back
    to the public fields before export.
    """
    if not isinstance(row, dict):
        return row
    detalhes = row.get("detalhes") if isinstance(row.get("detalhes"), dict) else {}
    src = detalhes.get("numeric_source") if isinstance(detalhes, dict) else None
    if isinstance(src, dict):
        for field, meta in list(src.items()):
            if not isinstance(meta, dict):
                continue
            source_text = clean_numeric_text(meta.get("source_text"))
            if source_text and field in row:
                row[field] = source_text
    return row


def audit_decimal_loss(row: Dict[str, Any]) -> list[Dict[str, Any]]:
    issues: list[Dict[str, Any]] = []
    if not isinstance(row, dict):
        return issues
    detalhes = row.get("detalhes") if isinstance(row.get("detalhes"), dict) else {}
    src = detalhes.get("numeric_source") if isinstance(detalhes, dict) else None
    if not isinstance(src, dict):
        return issues
    for field, meta in src.items():
        if not isinstance(meta, dict):
            continue
        source = clean_numeric_text(meta.get("source_text"))
        exported = clean_numeric_text(row.get(field))
        if source and exported and source != exported and decimal_scale(source) > decimal_scale(exported):
            issues.append({"field": field, "source_text": source, "exported": exported, "code": "decimal_scale_loss"})
    return issues
