from __future__ import annotations
from typing import Any, Dict, Iterable, List
import json
import re

from app.core.table_models import normalize_table_models, summarize_table_models
_PROFILE_LIST_FIELDS = (
    "header_phrases_recorrentes",
    "footer_phrases_recorrentes",
    "frases_institucionais_para_ignorar",
    "marcadores_de_secao_recorrentes",
    "rotulos_de_coluna_recorrentes",
    "rotulos_financeiros_recorrentes",
    "anchors_de_pagina",
)
_IGNORE_PROFILE_LIST_FIELDS = (
    "header_phrases_recorrentes",
    "footer_phrases_recorrentes",
    "frases_institucionais_para_ignorar",
    "marcadores_de_secao_recorrentes",
)
def _split_profile_phrases(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        out: List[str] = []
        for item in value:
            out.extend(_split_profile_phrases(item))
        return out
    s = str(value).strip()
    if not s:
        return []
    if s.startswith("[") and s.endswith("]"):
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return _split_profile_phrases(parsed)
        except Exception:
            pass
    return [part.strip() for part in re.split(r"[\n;]+", s) if part and part.strip()]
def normalize_document_profile(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TypeError("document_profile deve ser um objeto/dicionário.")
    profile: Dict[str, Any] = {}
    for key, raw in value.items():
        if key in _PROFILE_LIST_FIELDS:
            profile[key] = _split_profile_phrases(raw)
        elif key == 'table_models':
            profile[key] = normalize_table_models(raw)
        elif isinstance(raw, str):
            profile[key] = raw.strip()
        else:
            profile[key] = raw
    for key in _PROFILE_LIST_FIELDS:
        profile.setdefault(key, [])
    profile['table_models'] = normalize_table_models(profile.get('table_models'))
    return profile
def _collect_profile_phrases(profile: Dict[str, Any] | None, *, keys: Iterable[str]) -> List[str]:
    profile = profile or {}
    out: List[str] = []
    seen = set()
    for key in keys:
        for phrase in _split_profile_phrases(profile.get(key)):
            if phrase not in seen:
                seen.add(phrase)
                out.append(phrase)
    return out

def collect_profile_phrases(profile: Dict[str, Any] | None) -> List[str]:
    return _collect_profile_phrases(profile, keys=_PROFILE_LIST_FIELDS)

def collect_profile_ignore_phrases(profile: Dict[str, Any] | None) -> List[str]:
    return _collect_profile_phrases(profile, keys=_IGNORE_PROFILE_LIST_FIELDS)
def merge_dynamic_phrases(dynamic_ignore_phrases: Any, document_profile: Dict[str, Any] | None) -> List[str]:
    out: List[str] = []
    seen = set()
    for phrase in _split_profile_phrases(dynamic_ignore_phrases) + collect_profile_ignore_phrases(document_profile):
        if phrase not in seen:
            seen.add(phrase)
            out.append(phrase)
    return out
def profile_column_labels(profile: Dict[str, Any] | None) -> List[str]:
    profile = profile or {}
    return _split_profile_phrases(profile.get("rotulos_de_coluna_recorrentes"))
def profile_financial_labels(profile: Dict[str, Any] | None) -> List[str]:
    profile = profile or {}
    return _split_profile_phrases(profile.get("rotulos_financeiros_recorrentes"))
def summarize_document_profile(profile: Dict[str, Any] | None) -> Dict[str, Any]:
    profile = profile or {}
    summary: Dict[str, Any] = {}
    for key in _PROFILE_LIST_FIELDS:
        values = _split_profile_phrases(profile.get(key))
        if values:
            summary[key] = values
    if profile.get("nome"):
        summary["nome"] = str(profile.get("nome"))
    if profile.get("observacoes"):
        summary["observacoes"] = str(profile.get("observacoes"))
    if profile.get('table_models'):
        summary['table_models'] = summarize_table_models(profile.get('table_models'))
    return summary
