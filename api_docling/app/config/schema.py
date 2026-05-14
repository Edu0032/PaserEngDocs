from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ProjectConfig(BaseModel):
    model_config = ConfigDict(extra='allow')
    name: str = 'Api_pdf'
    document_model: str = 'mixed_document'
    current_release: str = 'v61.0.11-sicro-section-engine-and-span-fix'
    goal: str = ''


class ApiAuthConfig(BaseModel):
    model_config = ConfigDict(extra='allow')
    enabled: bool = False
    header_name: str = 'x-api-key'
    env_var_name: str = 'API_PDF_API_KEY'


class ApiCorsConfig(BaseModel):
    model_config = ConfigDict(extra='allow')
    allow_origins: List[str] = Field(default_factory=lambda: ['*'])
    allow_methods: List[str] = Field(default_factory=lambda: ['GET', 'POST', 'OPTIONS'])
    allow_headers: List[str] = Field(default_factory=lambda: ['*'])
    allow_credentials: bool = False


class ApiUploadConfig(BaseModel):
    model_config = ConfigDict(extra='allow')
    max_file_size_mb: int = 25
    allowed_content_types: List[str] = Field(default_factory=lambda: ['application/pdf'])
    allowed_extensions: List[str] = Field(default_factory=lambda: ['.pdf'])


class ApiResponseMetaConfig(BaseModel):
    model_config = ConfigDict(extra='allow')
    include_request_id: bool = True
    include_processing_time_ms: bool = True
    include_parser_version: bool = True
    include_config_version: bool = True
    include_input_metadata: bool = True


class ApiHostingConfig(BaseModel):
    model_config = ConfigDict(extra='allow')
    bind_host: str = '0.0.0.0'
    default_port: int = 10000
    trusted_hosts: List[str] = Field(default_factory=lambda: ['*'])
    platform_target: str = 'render'


class ApiSecurityConfig(BaseModel):
    model_config = ConfigDict(extra='allow')
    enable_headers_by_default: bool = True
    headers: Dict[str, str] = Field(default_factory=lambda: {
        'X-Content-Type-Options': 'nosniff',
        'X-Frame-Options': 'DENY',
        'Referrer-Policy': 'strict-origin-when-cross-origin',
        'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
    })


class ApiConfig(BaseModel):
    model_config = ConfigDict(extra='allow')
    title: str = 'PDF Import API'
    openapi_version_label: str = '0.7.0'
    main_entrypoint: str = 'app.main:app'
    app_factory: str = 'app.api:create_app'
    docs_enabled_by_default: bool = True
    auth: ApiAuthConfig = Field(default_factory=ApiAuthConfig)
    cors: ApiCorsConfig = Field(default_factory=ApiCorsConfig)
    upload: ApiUploadConfig = Field(default_factory=ApiUploadConfig)
    response_metadata: ApiResponseMetaConfig = Field(default_factory=ApiResponseMetaConfig)
    hosting: ApiHostingConfig = Field(default_factory=ApiHostingConfig)
    security: ApiSecurityConfig = Field(default_factory=ApiSecurityConfig)




class DoclingConfig(BaseModel):
    model_config = ConfigDict(extra='allow')
    enabled: bool = True
    base_url: str = ''
    extract_path: str = '/extract-table-structure'
    timeout_seconds: float = 20.0
    transport_mode: str = 'auto'
    local_surrogate_enabled: bool = True

class ParserConfigDocument(BaseModel):
    model_config = ConfigDict(extra='allow')
    _schema_version: str = 'v61.0.11-sicro-section-engine-and-span-fix'
    parser_profile: str = 'documento_misto'
    project: ProjectConfig = Field(default_factory=ProjectConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)
    docling: DoclingConfig = Field(default_factory=DoclingConfig)
    documento_misto: Dict[str, Any] = Field(default_factory=dict)
    matching: Dict[str, Any] = Field(default_factory=dict)
    validation_defaults: Dict[str, Any] = Field(default_factory=dict)
    sicro_parser: Dict[str, Any] = Field(default_factory=dict)
    reporting: Dict[str, Any] = Field(default_factory=dict)
    package_hygiene: Dict[str, Any] = Field(default_factory=dict)
    legacy_profiles: Dict[str, Any] = Field(default_factory=dict)
    sinapi: Optional[Dict[str, Any]] = None
    sicro: Optional[Dict[str, Any]] = None
