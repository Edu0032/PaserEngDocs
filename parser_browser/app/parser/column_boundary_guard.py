from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()


def _norm(value: Any) -> str:
    s = _clean(value).upper()
    accents = str.maketrans({
        'Á':'A','À':'A','Â':'A','Ã':'A','É':'E','Ê':'E','Í':'I','Ó':'O','Ô':'O','Õ':'O','Ú':'U','Ç':'C'
    })
    return s.translate(accents)


def code_key(value: Any) -> str:
    return re.sub(r"[^0-9A-Z]", "", _norm(value))


def normalize_code_display(value: Any) -> str:
    """Keep user/PDF-visible code punctuation while removing structural prefixes."""
    s = _clean(value)
    if not s:
        return ""
    s = re.sub(r"(?i)^o\s+(?=(?:Composi[çc][aã]o|Auxiliar|Insumo)\b)", "", s).strip()
    s = re.sub(r"(?i)^Composi[çc][aã]o\s+Auxiliar\b", "", s).strip()
    s = re.sub(r"(?i)^Composi[çc][aã]o\b", "", s).strip()
    s = re.sub(r"(?i)^Auxiliar\b", "", s).strip()
    s = re.sub(r"(?i)^Insumo\b", "", s).strip()
    # Normalize spacing but preserve slash, dot, hyphen and meaningful spaces.
    s = re.sub(r"\s+", " ", s).strip()
    return s


_GLOBAL_BANKS = {
    'SINAPI': 'SINAPI', 'SICRO': 'SICRO', 'SICRO3': 'SICRO',
    'PROPRIO': 'PRÓPRIO', 'PRÓPRIO': 'PRÓPRIO', 'ORSE': 'ORSE',
    'SEINFRA': 'SEINFRA', 'DNIT': 'DNIT', 'SEDOP': 'SEDOP', 'ANP': 'ANP',
}


def canonical_bank(value: Any, extra_aliases: Dict[str, str] | None = None) -> str:
    raw = _clean(value)
    if not raw:
        return ""
    aliases = dict(_GLOBAL_BANKS)
    for k, v in dict(extra_aliases or {}).items():
        aliases[_norm(k)] = _clean(v).upper()
    return aliases.get(_norm(raw), raw.upper())


def looks_like_bank(value: Any, extra_aliases: Dict[str, str] | None = None) -> bool:
    raw = _clean(value)
    if not raw:
        return False
    can = canonical_bank(raw, extra_aliases)
    return _norm(can) in {_norm(v) for v in _GLOBAL_BANKS.values()} or _norm(raw) in { _norm(k) for k in dict(extra_aliases or {}).keys() }


_CODE_PATTERNS = [
    r"^[0-9]{3,}(?:/[0-9A-Z]+)?$",
    r"^[A-Z]{1,8}\.[A-Z0-9.-]+$",
    r"^[A-Z]{1,8}\s*-\s*[0-9A-Z.-]+$",
    r"^[A-Z]{1,8}\s+[0-9]{1,4}$",
    r"^[A-Z]{2,}(?:\.[A-Z0-9]+)+$",
    r"^[A-Z0-9]{2,}[-.][A-Z0-9.-]+$",
]


def looks_like_code(value: Any) -> bool:
    s = _clean(value).upper().strip()
    if not s:
        return False
    if looks_like_bank(s):
        return False
    compact = re.sub(r"\s+", " ", s)
    if any(re.fullmatch(p, compact) for p in _CODE_PATTERNS):
        return True
    # Avoid classifying long descriptions as codes.
    if len(compact) <= 18 and re.search(r"\d", compact) and re.fullmatch(r"[A-Z0-9 ._/-]+", compact):
        return True
    return False


def split_leading_code_bank_from_description(text: str, *, code: str = "", bank: str = "", extra_bank_aliases: Dict[str, str] | None = None) -> Dict[str, Any]:
    """Fallback textual splitter for rows where codigo/banco were fused into descricao."""
    original = _clean(text)
    result = {'codigo': normalize_code_display(code), 'banco': canonical_bank(bank, extra_bank_aliases) if bank else '', 'descricao': original, 'changed': False, 'tokens_removed': []}
    if not original:
        return result
    tokens = original.split()
    if not tokens:
        return result

    # Candidate windows before the description content. Supports: CADM.01 Próprio ..., 12345/001 SINAPI ..., CP - 001 Próprio ..., ABC 01 Próprio ...
    max_code_tokens = min(4, len(tokens))
    for code_len in range(max_code_tokens, 0, -1):
        code_candidate = " ".join(tokens[:code_len])
        if not looks_like_code(code_candidate):
            continue
        if code_len >= len(tokens):
            continue
        bank_candidate = tokens[code_len]
        # Some banks can be split, but the usual ones are single-token; keep simple and general.
        if looks_like_bank(bank_candidate, extra_bank_aliases):
            desc = " ".join(tokens[code_len + 1:]).strip()
            if desc:
                result.update({
                    'codigo': normalize_code_display(code_candidate),
                    'banco': canonical_bank(bank_candidate, extra_bank_aliases),
                    'descricao': desc,
                    'changed': True,
                    'tokens_removed': [code_candidate, bank_candidate],
                    'method': 'leading_code_bank_textual_split',
                })
                return result
    # If caller already knows code/bank, strip those prefixes faithfully.
    desc = original
    removed: List[str] = []
    known_code = normalize_code_display(code)
    if known_code and code_key(desc.split()[0] if desc.split() else '') == code_key(known_code):
        desc = re.sub(rf"^\s*{re.escape(desc.split()[0])}\s+", "", desc).strip()
        removed.append(known_code)
    known_bank = canonical_bank(bank, extra_bank_aliases) if bank else ''
    if known_bank and desc:
        first = desc.split()[0]
        if canonical_bank(first, extra_bank_aliases) == known_bank:
            desc = re.sub(rf"^\s*{re.escape(first)}\s+", "", desc).strip()
            removed.append(known_bank)
    if removed and desc:
        result.update({'descricao': desc, 'changed': True, 'tokens_removed': removed, 'method': 'known_code_bank_prefix_strip'})
    return result


def _find_col(schema: List[Dict[str, Any]], canonical: str) -> Dict[str, Any] | None:
    for col in schema:
        c = str(col.get('canonical') or col.get('canonical_name') or '').strip()
        if c == canonical:
            return col
    return None


def description_boundary_from_schema(table_schema: Dict[str, Any]) -> Dict[str, Any]:
    cols = list(table_schema.get('column_schema') or table_schema.get('columns') or [])
    desc = _find_col(cols, 'descricao')
    if not desc:
        return {}
    try:
        x0 = float(desc.get('x0') if desc.get('x0') is not None else desc.get('effective_x0'))
    except Exception:
        return {}
    return {'descricao_x0': x0, 'source': desc.get('geometry_source') or (desc.get('metadata') or {}).get('geometry_source') or 'schema'}


def clean_description_prefix(text: str, *, code: str = '', bank: str = '', table_schema: Dict[str, Any] | None = None, extra_bank_aliases: Dict[str, str] | None = None) -> Dict[str, Any]:
    """Final safety guard: if codigo/banco leaked into descricao, split them out.

    Geometry-aware guard metadata is recorded when schema exposes descricao.x0. The function does not
    invent coordinates; it uses the known descricao boundary as evidence that leading code/bank text is unsafe.
    """
    table_schema = table_schema or {}
    boundary = description_boundary_from_schema(table_schema)
    split = split_leading_code_bank_from_description(text, code=code, bank=bank, extra_bank_aliases=extra_bank_aliases)
    if boundary and split.get('changed'):
        split.setdefault('guards_applied', []).append({
            'type': 'description_left_boundary',
            'descricao_x0': boundary.get('descricao_x0'),
            'tokens_removed_from_description': list(split.get('tokens_removed') or []),
            'note': 'descricao_x0_known; prefix before description boundary treated as non-description text',
        })
    return split
