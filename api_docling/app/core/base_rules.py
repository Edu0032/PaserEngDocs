from __future__ import annotations

import re
import unicodedata
from typing import Dict, Iterable, List, Optional

from app.core.header_resolver import resolve_header_map


def norm_text(value: str) -> str:
    s = (value or "").strip().lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^a-z0-9/%\.\s]+", " ", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s


DEFAULT_BANK_ALIASES: Dict[str, List[str]] = {
    "SINAPI": ["SINAPI", "SINAP I", "SINAP"],
    "PRÓPRIO": ["PRÓPRIO", "PROPRIO", "PRÓPRIO", "PROP", "PRÓP."],
    "ORSE": ["ORSE"],
    "SICRO": ["SICRO", "SICRO3", "SICRO 3", "SICRO-3"],
    "SEINFRA": ["SEINFRA"],
    "DNIT": ["DNIT"],
    "SEDOP": ["SEDOP"],
    "SBC": ["SBC"],
}

DEFAULT_COMPOSITION_LABELS: Dict[str, List[str]] = {
    "composicao": ["COMPOSIÇÃO", "COMPOSICAO", "COMPOS", "COMP."],
    "auxiliar": ["COMPOSIÇÃO AUXILIAR", "COMPOSICAO AUXILIAR", "AUXILIAR", "COMP. AUXILIAR"],
    "insumo": ["INSUMO", "INSUMOS"],
}


def get_bank_aliases(config: dict | None) -> Dict[str, List[str]]:
    """Return bank aliases from generic defaults plus payload/config extensions."""
    config = config or {}
    merged: Dict[str, List[str]] = {k: list(v) for k, v in DEFAULT_BANK_ALIASES.items()}

    def add_alias(canon: str, alias: str) -> None:
        canon_up = str(canon or "").strip().upper()
        alias_s = str(alias or "").strip()
        if not canon_up or not alias_s:
            return
        if canon_up == "PROPRIO":
            canon_up = "PRÓPRIO"
        merged.setdefault(canon_up, [])
        merged[canon_up].append(alias_s)

    def merge(mapping) -> None:
        if not isinstance(mapping, dict):
            return
        for key, value in mapping.items():
            if isinstance(value, (list, tuple, set)):
                for alias in value:
                    add_alias(key, alias)
            elif isinstance(value, str):
                # Supports both {"CANON": "ALIAS"} and {"ALIAS": "CANON"}.
                key_up = str(key or "").strip().upper()
                val_up = str(value or "").strip().upper()
                if key_up in DEFAULT_BANK_ALIASES or key_up in {"PROPRIO", "PRÓPRIO"}:
                    add_alias(key_up, value)
                else:
                    add_alias(val_up, key)

    merge((config.get("normalization") or {}).get("bank_aliases"))
    merge((config.get("document_profile") or {}).get("extra_bank_aliases"))
    ai_hints = config.get("ai_hints") or {}
    if isinstance(ai_hints, dict):
        merge((ai_hints.get("document_profile") or {}).get("extra_bank_aliases"))

    for canon, aliases in list(merged.items()):
        seen = set()
        clean = []
        for alias in [canon] + aliases:
            key = norm_text(alias)
            if not key or key in seen:
                continue
            seen.add(key)
            clean.append(alias)
        merged[canon] = clean
    return merged


def get_composition_label_aliases(config: dict | None) -> Dict[str, List[str]]:
    conf = ((config or {}).get("normalization") or {}).get("composition_labels") or {}
    merged: Dict[str, List[str]] = {k: list(v) for k, v in DEFAULT_COMPOSITION_LABELS.items()}
    for canon, aliases in conf.items():
        key = canon.strip().lower()
        merged.setdefault(key, [])
        merged[key].extend([str(a) for a in aliases or [] if str(a).strip()])
    for canon, aliases in list(merged.items()):
        seen = set()
        clean = []
        for alias in aliases:
            key = norm_text(alias)
            if not key or key in seen:
                continue
            seen.add(key)
            clean.append(alias)
        merged[canon] = clean
    return merged


def canonical_bank(value: str, config: dict | None = None) -> str:
    aliases = get_bank_aliases(config)
    raw = (value or "").strip()
    if not raw:
        return ""
    n = norm_text(raw)
    for canon, opts in aliases.items():
        canon_final = "PRÓPRIO" if canon in {"PROPRIO", "PRÓPRIO"} else canon
        for opt in opts:
            o = norm_text(opt)
            if not o:
                continue
            if n == o or n.replace(" ", "") == o.replace(" ", ""):
                return canon_final
    up = raw.strip().upper()
    return "PRÓPRIO" if up in {"PROPRIO", "PRÓPRIO"} else up


def bank_regex_fragment(config: dict | None = None) -> str:
    aliases = get_bank_aliases(config)
    values: List[str] = []
    for opts in aliases.values():
        values.extend(opts)
    values = sorted({v for v in values if v}, key=len, reverse=True)
    escaped = []
    for value in values:
        parts = [re.escape(p) for p in value.split() if p]
        escaped.append(r"\s*".join(parts))
    return "(?:" + "|".join(escaped) + ")"


def header_cfg(config: dict | None, key: str, default_aliases: dict | None = None, default_required: list | None = None, default_similarity: float = 0.84) -> dict:
    cfg = (config or {}).get(key) or {}
    aliases = dict(default_aliases or {})
    aliases.update(cfg.get("aliases") or {})
    return {
        "aliases": aliases,
        "required": list(cfg.get("required") or (default_required or [])),
        "min_similarity": float(cfg.get("min_similarity", default_similarity)),
    }


def resolve_header_cells(cells: Iterable[str], cfg: dict) -> dict:
    values = [str(c or "") for c in cells]
    aliases = cfg.get("aliases") or {}
    required = cfg.get("required") or []
    sim = float(cfg.get("min_similarity", 0.84))
    mapping, missing = resolve_header_map(values, aliases=aliases, required=required, min_similarity=sim)
    return {"mapping": mapping, "missing": missing, "matched": len(mapping)}


def is_header_row(cells: Iterable[str], cfg: dict, min_hits: int = 3) -> bool:
    info = resolve_header_cells(cells, cfg)
    matched = int(info["matched"])
    required = cfg.get("required") or []
    if required and not info["missing"]:
        return True
    return matched >= min_hits


def line_has_header_markers(text: str, cfg: dict, required_keys: Optional[List[str]] = None) -> bool:
    raw = str(text or "")
    if not raw.strip():
        return False
    tokens = re.split(r"\s+|\|", raw)
    info = resolve_header_cells(tokens, cfg)
    required_keys = required_keys or []
    if required_keys:
        return all(key in info["mapping"] for key in required_keys)
    required = cfg.get("required") or []
    if required and not info["missing"]:
        return True
    return int(info["matched"]) >= min(3, max(1, len(cfg.get("aliases") or {})))


def detect_composition_label(text: str, config: dict | None = None) -> str:
    labels = get_composition_label_aliases(config)
    n = norm_text(text)
    if not n:
        return ""
    n_compact = n.replace(" ", "")

    def _matches(alias: str) -> bool:
        alias_n = norm_text(alias)
        if not alias_n:
            return False
        alias_compact = alias_n.replace(" ", "")
        return n.startswith(alias_n) or n_compact.startswith(alias_compact)

    aux_aliases = labels.get("auxiliar", [])
    comp_aliases = labels.get("composicao", [])
    ins_aliases = labels.get("insumo", [])

    for alias in aux_aliases:
        if _matches(alias):
            return "AUXILIAR"
    for alias in ins_aliases:
        if _matches(alias):
            return "INSUMO"
    for alias in comp_aliases:
        if _matches(alias):
            return "COMPOSICAO"
    return ""
