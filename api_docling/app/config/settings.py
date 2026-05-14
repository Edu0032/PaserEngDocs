from __future__ import annotations

import os
from typing import List
from pydantic import BaseModel, Field
from app.config.version import CURRENT_RELEASE, CONTRACT_VERSION, PYODIDE_BUNDLE_VERSION, DOCLING_CONTRACT_VERSION, SOURCE_BUNDLE_NAME

_PRODUCTION_ENVS = {"production", "prod", "render"}


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {'1', 'true', 'yes', 'on'}


def _first_env(names: list[str], default: str | None = None) -> str | None:
    for name in names:
        raw = os.getenv(name)
        if raw is not None and str(raw).strip() != '':
            return str(raw).strip()
    return default


def _list_env(name: str, default: List[str]) -> List[str]:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == '':
        return list(default)
    if str(raw).strip() in {'*', 'all', 'ALL'}:
        return ['*']
    return [part.strip() for part in raw.split(',') if part.strip()]


def _int_env(names: str | list[str], default: int) -> int:
    if isinstance(names, str):
        names = [names]
    raw = _first_env(list(names))
    if raw is None or not str(raw).strip():
        return int(default)
    try:
        return int(str(raw).strip())
    except Exception:
        return int(default)


class AppSettings(BaseModel):
    environment: str = Field(default='development')
    docs_enabled: bool = True
    api_key: str = ''
    api_key_header_name: str = 'x-api-key'
    cors_allow_origins: List[str] = Field(default_factory=lambda: ['*'])
    cors_allow_methods: List[str] = Field(default_factory=lambda: ['GET', 'POST', 'OPTIONS'])
    cors_allow_headers: List[str] = Field(default_factory=lambda: ['*'])
    cors_allow_credentials: bool = False
    max_upload_mb: int = 25
    trusted_pdf_content_types: List[str] = Field(default_factory=lambda: ['application/pdf'])
    trusted_hosts: List[str] = Field(default_factory=lambda: ['*'])
    security_headers_enabled: bool = True
    request_timeout_seconds: int = 600
    docling_timeout_seconds: int = 120
    docling_cache_max_entries: int = 32

    @property
    def is_production(self) -> bool:
        return str(self.environment or '').strip().lower() in _PRODUCTION_ENVS


def get_settings(defaults: dict | None = None) -> AppSettings:
    defaults = defaults or {}
    api_defaults = defaults.get('api') or {}
    upload_defaults = (api_defaults.get('upload') or {})
    auth_defaults = (api_defaults.get('auth') or {})
    cors_defaults = (api_defaults.get('cors') or {})
    hosting_defaults = (api_defaults.get('hosting') or {})
    security_defaults = (api_defaults.get('security') or {})
    timeout_defaults = (api_defaults.get('timeouts') or {})

    environment = os.getenv('API_PDF_ENV', str(api_defaults.get('environment') or 'development'))
    is_prod = str(environment or '').strip().lower() in _PRODUCTION_ENVS

    # Keep docs disabled by default in production, but allow Render/Lovable testing with API_PDF_DOCS_ENABLED=true.
    docs_default = bool(api_defaults.get('docs_enabled_by_default', True))
    if is_prod:
        docs_default = False

    # v61.0.36: do not silently clear '*' in production. Browser/Lovable calls need a valid CORS response.
    # To restrict later, set API_PDF_CORS_ALLOW_ORIGINS=https://your-lovable-domain,...
    origins = _list_env('API_PDF_CORS_ALLOW_ORIGINS', cors_defaults.get('allow_origins') or ['*'])

    api_key_env_name = auth_defaults.get('env_var_name', 'API_PDF_API_KEY')
    return AppSettings(
        environment=environment,
        docs_enabled=_bool_env('API_PDF_DOCS_ENABLED', docs_default),
        api_key=os.getenv(api_key_env_name, ''),
        api_key_header_name=os.getenv('API_PDF_API_KEY_HEADER', auth_defaults.get('header_name', 'x-api-key')),
        cors_allow_origins=origins,
        cors_allow_methods=_list_env('API_PDF_CORS_ALLOW_METHODS', cors_defaults.get('allow_methods') or ['GET', 'POST', 'OPTIONS']),
        cors_allow_headers=_list_env('API_PDF_CORS_ALLOW_HEADERS', cors_defaults.get('allow_headers') or ['*']),
        cors_allow_credentials=_bool_env('API_PDF_CORS_ALLOW_CREDENTIALS', bool(cors_defaults.get('allow_credentials', False))),
        max_upload_mb=_int_env('API_PDF_MAX_UPLOAD_MB', int(upload_defaults.get('max_file_size_mb', 25))),
        trusted_pdf_content_types=list(upload_defaults.get('allowed_content_types') or ['application/pdf']),
        trusted_hosts=_list_env('API_PDF_TRUSTED_HOSTS', hosting_defaults.get('trusted_hosts') or ['*']),
        security_headers_enabled=_bool_env('API_PDF_SECURITY_HEADERS_ENABLED', bool(security_defaults.get('enable_headers_by_default', True))),
        request_timeout_seconds=_int_env('API_PDF_REQUEST_TIMEOUT_SECONDS', int(timeout_defaults.get('request_timeout_seconds', 600))),
        # Accept both names because the Render form in the project used DOCLING_TIMEOUT_SECONDS.
        docling_timeout_seconds=_int_env(['DOCLING_TIMEOUT_SECONDS', 'API_PDF_DOCLING_TIMEOUT_SECONDS'], int(timeout_defaults.get('docling_timeout_seconds', 120))),
        docling_cache_max_entries=_int_env('API_PDF_DOCLING_CACHE_MAX_ENTRIES', 32),
    )


def refresh_app_settings_cache() -> None:
    return None
