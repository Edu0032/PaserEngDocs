from __future__ import annotations

import re
from typing import Any


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ").strip())


def norm_text(value: Any) -> str:
    text = clean_text(value).upper()
    repl = str.maketrans({
        "Á": "A", "À": "A", "Â": "A", "Ã": "A", "Ä": "A",
        "É": "E", "È": "E", "Ê": "E", "Ë": "E",
        "Í": "I", "Ì": "I", "Î": "I", "Ï": "I",
        "Ó": "O", "Ò": "O", "Ô": "O", "Õ": "O", "Ö": "O",
        "Ú": "U", "Ù": "U", "Û": "U", "Ü": "U",
        "Ç": "C",
        "á": "A", "à": "A", "â": "A", "ã": "A", "ä": "A",
        "é": "E", "è": "E", "ê": "E", "ë": "E",
        "í": "I", "ì": "I", "î": "I", "ï": "I",
        "ó": "O", "ò": "O", "ô": "O", "õ": "O", "ö": "O",
        "ú": "U", "ù": "U", "û": "U", "ü": "U",
        "ç": "C",
    })
    return text.translate(repl)


def looks_like_ptbr_decimal_or_money(value: Any) -> bool:
    """Return True only for clear pt-BR numeric values, not codes.

    Codes may contain dots, slashes, hyphens and letters (CADM.01, COMP.EXEMPLO.1,
    12345/001, CP - 001).  A dot alone is not enough to classify a token as a
    value.  Clear values generally contain a comma decimal separator, or are in a
    confirmed numeric column handled by the caller.
    """
    raw = clean_text(value)
    if not raw:
        return False
    compact = raw.replace(" ", "")
    if re.search(r"[A-Za-zÀ-ÿ]", compact):
        return False
    # pt-BR decimal or money, with optional thousands separators.
    if re.fullmatch(r"[+-]?\d{1,3}(?:\.\d{3})*,\d{1,8}", compact):
        return True
    if re.fullmatch(r"[+-]?\d+,\d{1,8}", compact):
        return True
    # Percentages with comma decimal are numeric values.
    if re.fullmatch(r"[+-]?\d{1,3}(?:\.\d{3})*,\d{1,8}%", compact):
        return True
    # Pure integers are ambiguous: may be code, quantity or item.  Do not mark as
    # value here without column context.
    return False


def looks_like_code(value: Any) -> bool:
    raw = clean_text(value)
    if not raw:
        return False
    compact = re.sub(r"\s+", "", raw.upper())
    if looks_like_ptbr_decimal_or_money(raw):
        return False
    # Letter-bearing identifiers are codes/banks, even when they contain dots.
    if re.search(r"[A-ZÀ-Ý]", compact) and re.search(r"[A-ZÀ-Ý0-9]", compact):
        return bool(re.fullmatch(r"[A-ZÀ-Ý0-9._/\-]+", compact))
    # Slash and hyphen are common code separators.
    if re.fullmatch(r"\d+[/-]\d+(?:[/-]\d+)?", compact):
        return True
    # Numeric codes without comma are possible, but a single digit is more likely
    # to be quantity/item marker.  Accept 4+ digits as code-like.
    if re.fullmatch(r"\d{4,}", compact):
        return True
    return False


def classify_token(value: Any, *, column_context: str = "") -> str:
    ctx = norm_text(column_context)
    if ctx in {"VALOR", "VALOR_UNIT", "TOTAL", "QUANT", "QUANTIDADE", "CUSTO", "PRECO", "PREÇO"} and looks_like_ptbr_decimal_or_money(value):
        return "number"
    if looks_like_code(value):
        return "code"
    if looks_like_ptbr_decimal_or_money(value):
        return "number"
    return "text"
