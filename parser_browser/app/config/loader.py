from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable

from app.config.schema import ParserConfigDocument


def _project_db_dir() -> Path:
    # app/config/loader.py -> parser_browser/app/config -> parser_browser/db
    return Path(__file__).resolve().parents[2] / 'db'

CONFIG_PATH = _project_db_dir() / 'base_config.json'
CONFIG_FRAGMENTS_DIR = _project_db_dir() / 'base_config.d'


def _deep_merge(base: Any, overlay: Any) -> Any:
    if not isinstance(base, dict) or not isinstance(overlay, dict):
        return copy.deepcopy(overlay)
    merged = copy.deepcopy(base)
    for key, value in overlay.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def _iter_fragment_paths() -> Iterable[Path]:
    if not CONFIG_FRAGMENTS_DIR.exists():
        return []
    return sorted([p for p in CONFIG_FRAGMENTS_DIR.glob('*.json') if p.is_file()], key=lambda p: p.name)


def load_raw_config_with_fragments() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f'Nenhum arquivo de configuração encontrado em {CONFIG_PATH}')
    raw = _load_json(CONFIG_PATH)
    fragments_loaded: list[str] = []
    for path in _iter_fragment_paths():
        frag = _load_json(path)
        raw = _deep_merge(raw, frag)
        fragments_loaded.append(path.name)
    raw.setdefault('metadata', {})
    raw['metadata']['base_config_fragments_loaded'] = fragments_loaded
    raw['_schema_version'] = str(raw.get('_schema_version') or 'legacy')
    return raw


@lru_cache(maxsize=1)
def load_parser_config() -> dict:
    raw = load_raw_config_with_fragments()
    # The schema is permissive (extra allowed) and protects the historical contract.
    validated = ParserConfigDocument.model_validate(raw)
    return validated.model_dump(mode='python')


def refresh_parser_config_cache() -> None:
    load_parser_config.cache_clear()


load_base_config = load_parser_config


def merge_base_config_layers(admin_config: Dict[str, Any] | None, user_config: Dict[str, Any] | None = None) -> dict:
    """Merge administrator/global config with a user-editable config overlay.

    Admin config owns universal parser rules (regex, schemas, quality gates,
    Docling/cache policy).  User config is an overlay for custom bank/table
    profiles created by the Lovable UI.  The merge is deep and non-mutating, so
    new keys can be added without breaking older payloads.
    """
    base = copy.deepcopy(admin_config or {})
    if isinstance(user_config, dict) and user_config:
        base = _deep_merge(base, user_config)
        base.setdefault("metadata", {})
        base["metadata"]["user_base_config_merged"] = True
    else:
        base.setdefault("metadata", {})
        base["metadata"].setdefault("user_base_config_merged", False)
    return base


def validate_user_base_config_overlay(user_config: Dict[str, Any] | None) -> Dict[str, Any]:
    """Lightweight validation for UI-authored user base_config fragments."""
    if not user_config:
        return {"ok": True, "warnings": [], "errors": []}
    errors: list[dict] = []
    warnings: list[dict] = []
    profiles = (((user_config.get("custom_bank_profiles") or {}).get("profiles") or {}) if isinstance(user_config, dict) else {})
    if profiles and not isinstance(profiles, dict):
        errors.append({"path": "custom_bank_profiles.profiles", "message": "profiles deve ser objeto por id"})
    for profile_id, profile in (profiles or {}).items():
        if not isinstance(profile, dict):
            errors.append({"path": f"custom_bank_profiles.profiles.{profile_id}", "message": "perfil deve ser objeto"})
            continue
        templates = profile.get("templates") or []
        sections = profile.get("sections") or {}
        if not templates and not sections:
            warnings.append({"path": f"custom_bank_profiles.profiles.{profile_id}", "message": "perfil sem templates/sections"})
        for tidx, template in enumerate(templates if isinstance(templates, list) else []):
            cols = template.get("columns") or [] if isinstance(template, dict) else []
            if not cols:
                warnings.append({"path": f"custom_bank_profiles.profiles.{profile_id}.templates.{tidx}", "message": "template sem columns"})
            for cidx, col in enumerate(cols if isinstance(cols, list) else []):
                if isinstance(col, dict) and not col.get("canonical"):
                    errors.append({"path": f"custom_bank_profiles.profiles.{profile_id}.templates.{tidx}.columns.{cidx}", "message": "coluna sem canonical"})
    return {"ok": not errors, "warnings": warnings, "errors": errors}

def _iter_legacy_profiles(config_all: Dict[str, Any]) -> Iterable[dict]:
    legacy_profiles = config_all.get('legacy_profiles') or {}
    if isinstance(legacy_profiles, dict):
        preferred = legacy_profiles.get('default_profile')
        if preferred and isinstance(legacy_profiles.get(preferred), dict):
            yield legacy_profiles[preferred]
        for key, value in legacy_profiles.items():
            if key == 'default_profile':
                continue
            if isinstance(value, dict):
                yield value
    for key in ('sinapi', 'sicro'):
        value = config_all.get(key)
        if isinstance(value, dict):
            yield value


def resolve_runtime_config(config_all: Dict[str, Any], *, profile: str | None = None) -> dict:
    runtime: Dict[str, Any] = {}

    documento_misto = config_all.get('documento_misto') or {}

    legacy_profiles = config_all.get('legacy_profiles') or {}
    if profile and isinstance(legacy_profiles.get(profile), dict):
        runtime = _deep_merge(runtime, legacy_profiles.get(profile) or {})
    else:
        for legacy in _iter_legacy_profiles(config_all):
            if legacy.get('validation') or legacy.get('normalization') or legacy.get('synthetic'):
                runtime = _deep_merge(runtime, legacy)
                break

    if isinstance(documento_misto, dict):
        runtime = _deep_merge(runtime, documento_misto.get('shared_overrides') or {})

    for top_key, runtime_key in (
        ('validation_defaults', 'validation'),
        ('matching', 'matching'),
        ('sicro_parser', 'sicro_parser'),
        ('reporting', 'reporting'),
        ('output_options', 'output_options'),
        ('parser_options', 'parser_options'),
        ('recheck_rules', 'recheck_rules'),
        ('quality_gate', 'quality_gate'),
        ('custom_bank_profiles', 'custom_bank_profiles'),
    ):
        if isinstance(config_all.get(top_key), dict):
            runtime[runtime_key] = _deep_merge(runtime.get(runtime_key) or {}, config_all.get(top_key) or {})

    runtime.setdefault('document_model', 'mixed_document')
    runtime.setdefault('config_schema_version', str(config_all.get('_schema_version') or 'legacy'))
    runtime.setdefault('config_source', str(documento_misto.get('nome') or 'documento_misto'))
    runtime.setdefault('parser_profile', str(config_all.get('parser_profile') or 'documento_misto'))
    runtime.setdefault('metadata', {})
    runtime['metadata']['base_config_fragments_loaded'] = list(((config_all.get('metadata') or {}).get('base_config_fragments_loaded') or []))
    return runtime
