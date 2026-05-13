from __future__ import annotations

import hashlib
import json
from typing import Any, Dict

VERSION = "v61.0.35-candidate-profile-consensus-engine"


def stable_obj_hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj or {}, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def stable_docling_cache_key(*, seed_text_sha256: str, page_map: Dict[str, Any] | None = None, roles: Dict[str, Any] | None = None, tables: Dict[str, Any] | None = None, crop_policy: Dict[str, Any] | None = None, parser_contract: Dict[str, Any] | None = None, docling_context: Dict[str, Any] | None = None, contract_version: str = "") -> str:
    """Stable key based on semantic seed text + mapping/config, not bytes noise."""
    return stable_obj_hash({
        "seed_text_sha256": seed_text_sha256,
        "page_map": page_map or {},
        "roles": roles or {},
        "tables_hash": stable_obj_hash(tables or {}),
        "crop_policy_hash": stable_obj_hash(crop_policy or {}),
        "parser_contract_hash": stable_obj_hash(parser_contract or {}),
        "docling_context_hash": stable_obj_hash(docling_context or {}),
        "contract_version": contract_version,
    })
