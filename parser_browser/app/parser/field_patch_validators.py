from __future__ import annotations

"""Generic field patch validators for v61.0.39.

These validators are intentionally evidence-oriented: they do not decide where a
value came from, they only decide whether a candidate value has the shape and
semantics required for a field.  They are shared by extracted-evidence cross
resolution, local Deep Area Sweep recovery and the commit layer.
"""

from typing import Any, Dict, Iterable, Set
import re

from app.parser.broken_line_recovery import pollution_reason
from app.parser.code_value_classifier import clean_text, norm_text
from app.parser.numeric_constraint_solver import parse_ptbr_number

VERSION = "v61.0.75-correction-output-contract-and-review-index"

DESCRIPTION_FIELDS = {"descricao", "especificacao"}
UNIT_FIELDS = {"und", "unidade"}
QUANTITY_FIELDS = {"quant", "quantidade"}
MONEY_FIELDS = {
    "valor_unit",
    "total",
    "custo_unitario_sem_bdi",
    "custo_unitario_com_bdi",
    "custo_parcial",
    "custo_total",
    "preco_unitario",
    "custo_horario",
}

DEFAULT_UNITS = {
    "M", "M2", "M²", "M3", "M³", "UN", "UND", "UNID", "H", "KG", "T", "KM", "MES", "MÊS",
    "DIA", "VB", "CJ", "PAR", "L", "LITRO", "T.KM", "TXKM", "M³XKM", "M3XKM", "HA", "PÇ", "PC",
}

_CODE_LIKE_RE = re.compile(r"[A-Za-zÁ-ÿ]+\s*-?\s*\d|\d+\s*/\s*\d+|^[A-Z]{2,}\.?\d", re.I)
_PTBR_NUMERIC_TOKEN_RE = re.compile(r"^-?\d{1,3}(?:\.\d{3})*(?:,\d+)?$|^-?\d+(?:,\d+)?$")


def _observed_units(context: Dict[str, Any] | None = None) -> Set[str]:
    context = context if isinstance(context, dict) else {}
    values: Set[str] = set(DEFAULT_UNITS)
    for key in ("units", "unidades", "observed_units", "document_units"):
        raw = context.get(key)
        if isinstance(raw, dict):
            raw = list(raw.keys())
        if isinstance(raw, (list, tuple, set)):
            for u in raw:
                text = clean_text(u).upper()
                if text:
                    values.add(text)
                    values.add(norm_text(text))
    base = context.get("base_config") or context.get("config") or {}
    if isinstance(base, dict):
        for key in ("units", "unidades", "measurement_units", "unidades_medida"):
            raw = base.get(key)
            if isinstance(raw, dict):
                raw = list(raw.keys()) + [v for v in raw.values() if isinstance(v, str)]
            if isinstance(raw, (list, tuple, set)):
                for u in raw:
                    text = clean_text(u).upper()
                    if text:
                        values.add(text)
                        values.add(norm_text(text))
    return values


def normalize_field_name(field: Any) -> str:
    f = str(field or "").strip()
    aliases = {
        "descricao_servico": "descricao",
        "especificacoes": "especificacao",
        "especificações": "especificacao",
        "unidade": "und",
        "quantidade": "quant",
        "valor_unitario": "valor_unit",
        "valor_unitário": "valor_unit",
        "preco_unitario": "valor_unit",
        "preço_unitário": "valor_unit",
        "preço_unitario": "valor_unit",
        "custo_unitario": "custo_unitario_com_bdi",
    }
    return aliases.get(f, f)


def candidate_kind(field: Any) -> str:
    f = normalize_field_name(field)
    if f in DESCRIPTION_FIELDS:
        return "description"
    if f in UNIT_FIELDS:
        return "unit"
    if f in QUANTITY_FIELDS:
        return "quantity"
    if f in MONEY_FIELDS:
        return "money"
    if f in {"codigo", "banco", "fonte", "item"}:
        return "identity"
    return "text"


def looks_like_code(value: Any) -> bool:
    text = clean_text(value).upper().replace(" ", "")
    if not text:
        return False
    if "/" in text or re.match(r"^[A-Z]{1,6}[.-]?\d", text):
        return True
    return bool(_CODE_LIKE_RE.search(clean_text(value).upper()))


def validate_description_candidate(value: Any, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
    text = clean_text(value)
    if not text or len(text) < 3:
        return {"ok": False, "reason": "empty_description"}
    if pollution_reason(text):
        return {"ok": False, "reason": "description_pollution", "detail": pollution_reason(text)}
    if re.fullmatch(r"[\d\s.,%/\-]+", text):
        return {"ok": False, "reason": "numeric_only_description"}
    return {"ok": True, "normalized": text, "kind": "description"}


def validate_unit_candidate(value: Any, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
    text = clean_text(value)
    if not text:
        return {"ok": False, "reason": "empty_unit"}
    compact = text.upper().replace(" ", "")
    norm = norm_text(text).upper().replace(" ", "")
    if len(compact) > 12:
        return {"ok": False, "reason": "unit_too_long"}
    if re.search(r"\d{2,}", compact):
        return {"ok": False, "reason": "unit_contains_long_number"}
    if looks_like_code(text):
        return {"ok": False, "reason": "unit_looks_like_code"}
    units = _observed_units(context)
    if compact in units or norm in units:
        return {"ok": True, "normalized": text, "kind": "unit"}
    # Accept compact alphabetic unit symbols not in config only when they are short
    # and isolated.  This lets user/base_config enrichment later add them.
    if re.fullmatch(r"[A-ZÁ-ÿ.²³]+", compact, flags=re.I) and 1 <= len(compact) <= 5:
        return {"ok": True, "normalized": text, "kind": "unit", "new_unit_candidate": True}
    return {"ok": False, "reason": "unknown_unit"}


def validate_quantity_candidate(value: Any, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
    text = clean_text(value).replace(" ", "")
    if not text:
        return {"ok": False, "reason": "empty_quantity"}
    if looks_like_code(text) or "/" in text:
        return {"ok": False, "reason": "quantity_looks_like_code"}
    if not _PTBR_NUMERIC_TOKEN_RE.match(text):
        return {"ok": False, "reason": "invalid_quantity_format"}
    parsed = parse_ptbr_number(text)
    if parsed is None:
        return {"ok": False, "reason": "quantity_parse_failed"}
    return {"ok": True, "normalized": text, "kind": "quantity", "numeric": parsed}


def validate_money_candidate(value: Any, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
    text = clean_text(value).replace(" ", "")
    if not text:
        return {"ok": False, "reason": "empty_money"}
    if looks_like_code(text) or "/" in text:
        return {"ok": False, "reason": "money_looks_like_code"}
    if not _PTBR_NUMERIC_TOKEN_RE.match(text):
        return {"ok": False, "reason": "invalid_money_format"}
    parsed = parse_ptbr_number(text)
    if parsed is None:
        return {"ok": False, "reason": "money_parse_failed"}
    return {"ok": True, "normalized": text, "kind": "money", "numeric": parsed}


def validate_patch_candidate(field: Any, value: Any, row: Dict[str, Any] | None = None, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
    f = normalize_field_name(field)
    kind = candidate_kind(f)
    if kind == "description":
        return validate_description_candidate(value, context)
    if kind == "unit":
        return validate_unit_candidate(value, context)
    if kind == "quantity":
        return validate_quantity_candidate(value, context)
    if kind == "money":
        return validate_money_candidate(value, context)
    text = clean_text(value)
    if not text:
        return {"ok": False, "reason": "empty_text"}
    return {"ok": True, "normalized": text, "kind": kind}
