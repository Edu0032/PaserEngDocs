from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable

from app.config.schema import ParserConfigDocument


def _candidate_db_dirs() -> list[Path]:
    """Return possible base_config locations for local Python and Pyodide.

    In the browser bundle, the source archive is unpacked at Pyodide's current
    working directory, so the packaged config must be available as
    ``./db/base_config.json``.  In the monorepo, the same files live under
    ``parser_browser/db``.  Keeping this search centralized prevents a missing
    packaged config from becoming an opaque runtime crash.
    """
    here = Path(__file__).resolve()
    cwd = Path.cwd()
    candidates = [
        here.parents[2] / 'db',        # parser_browser/db in the monorepo
        cwd / 'db',                    # Pyodide/source archive root
        cwd / 'parser_browser' / 'db',  # tests or scripts executed from repo root
        Path('/home/pyodide/db'),      # explicit Pyodide runtime path shown in logs
    ]
    unique: list[Path] = []
    seen: set[str] = set()
    for c in candidates:
        s = str(c)
        if s not in seen:
            unique.append(c)
            seen.add(s)
    return unique


def _project_db_dir() -> Path:
    for candidate in _candidate_db_dirs():
        if (candidate / 'base_config.json').exists():
            return candidate
    # Preserve deterministic error path while allowing the caller to list all
    # attempted locations.
    return _candidate_db_dirs()[0]

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


def _iter_fragment_paths(base_dir: Path | None = None) -> Iterable[Path]:
    fragments_dir = (base_dir or _project_db_dir()) / 'base_config.d'
    if not fragments_dir.exists():
        return []
    return sorted([p for p in fragments_dir.glob('*.json') if p.is_file()], key=lambda p: p.name)


def load_raw_config_with_fragments() -> dict:
    config_path = _project_db_dir() / 'base_config.json'
    fragments_dir = config_path.parent / 'base_config.d'
    if not config_path.exists():
        attempted = [str(p / 'base_config.json') for p in _candidate_db_dirs()]
        raise FileNotFoundError('Nenhum arquivo de configuração encontrado. Tentativas: ' + ', '.join(attempted))
    raw = _load_json(config_path)
    fragments_loaded: list[str] = []
    for path in _iter_fragment_paths(config_path.parent):
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


def merge_base_config_layers(admin_config: Dict[str, Any] | None, user_config: Dict[str, Any] | None = None, embedded_config: Dict[str, Any] | None = None) -> dict:
    """Build the effective base_config used for one parse run.

    The browser zip contains a read-only default base_config.  Lovable should
    persist administrator and user/project customizations outside the zip and
    pass them as overlays at runtime.  Merge order is intentionally simple:

    1. embedded/default config from the zip;
    2. admin overlay or full admin copy overrides the default;
    3. user/project overlay overrides only its allowed custom sections.

    A full admin copy works because deep-merge of equal keys is idempotent and
    additions/overrides are applied in memory.  The zip is never mutated.
    """
    base = copy.deepcopy(embedded_config or {})
    admin_merged = False
    user_merged = False
    if isinstance(admin_config, dict) and admin_config:
        base = _deep_merge(base, admin_config)
        admin_merged = True
    if isinstance(user_config, dict) and user_config:
        base = _deep_merge(base, user_config)
        user_merged = True
    base.setdefault("metadata", {})
    base["metadata"]["base_config_layering"] = {
        "merge_order": ["embedded_zip_default", "admin_overlay_or_full_copy", "user_project_overlay"],
        "admin_base_config_merged": admin_merged,
        "user_base_config_merged": user_merged,
        "zip_mutated": False,
        "policy": "overlays são aplicados em memória a cada extração; o Lovable persiste admin/user fora do zip",
    }
    # Backward-compatible flags consumed by older tests/UI.
    base["metadata"]["user_base_config_merged"] = user_merged
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
