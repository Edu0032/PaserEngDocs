from __future__ import annotations

import re
from typing import Any, Dict, List


def get_knowledge_base(config: Dict[str, Any] | None) -> Dict[str, Any]:
    data = dict(config or {})
    kb = data.get("knowledge_base")
    if isinstance(kb, dict):
        return kb
    return {}


def list_bank_aliases(config: Dict[str, Any] | None) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for bank in list(get_knowledge_base(config).get("banks") or []):
        if not isinstance(bank, dict):
            continue
        canonical = str(bank.get("canonical") or "").strip()
        for alias in list(bank.get("aliases") or []):
            if canonical and alias:
                out[str(alias).strip().upper()] = canonical
    return out


def list_units(config: Dict[str, Any] | None, *, family: str | None = None) -> List[Dict[str, Any]]:
    units = []
    fam = str(family or "").strip().lower()
    for item in list(get_knowledge_base(config).get("units") or []):
        if not isinstance(item, dict):
            continue
        families = [str(x).lower() for x in list(item.get("families") or [])]
        if fam and "all" not in families and fam not in families:
            continue
        units.append(item)
    return units


def match_code_pattern(config: Dict[str, Any] | None, code: str, *, family: str | None = None) -> List[str]:
    code = str(code or "").strip()
    matched: List[str] = []
    fam = str(family or "").strip().lower()
    for pat in list(get_knowledge_base(config).get("code_patterns") or []):
        if not isinstance(pat, dict):
            continue
        if fam and str(pat.get("family") or "").lower() != fam:
            continue
        rx = str(pat.get("regex") or "")
        if not rx:
            continue
        try:
            if re.fullmatch(rx, code):
                matched.append(str(pat.get("id") or rx))
        except re.error:
            continue
    return matched


def validate_knowledge_base(config: Dict[str, Any] | None) -> Dict[str, Any]:
    kb = get_knowledge_base(config)
    errors: List[Dict[str, Any]] = []
    checked_regex = 0
    for section in ("banks", "units", "code_patterns"):
        for idx, item in enumerate(list(kb.get(section) or [])):
            if not isinstance(item, dict):
                continue
            rx = item.get("regex")
            if not rx:
                continue
            checked_regex += 1
            try:
                re.compile(str(rx))
            except re.error as exc:
                errors.append({"section": section, "index": idx, "regex": rx, "error": str(exc)})
    return {"ok": not errors, "checked_regex": checked_regex, "errors": errors, "editable_via_lovable": bool(kb.get("editable_via_lovable"))}
