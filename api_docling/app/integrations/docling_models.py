from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.config.version import CONTRACT_VERSION


class DoclingRegionHint(BaseModel):
    x0: float = 0.0
    y0: float = 0.0
    x1: float = 1.0
    y1: float = 1.0
    normalized: bool = True


class DoclingSeedRequest(BaseModel):
    page: int
    kind_hint: str
    family_hint: str = ''
    table_id: str = ''
    applies_to_range: Dict[str, int] = Field(default_factory=dict)
    preferred_region: Optional[DoclingRegionHint] = None
    ignore_regions: List[DoclingRegionHint] = Field(default_factory=list)
    must_include_text: List[str] = Field(default_factory=list)
    must_exclude_text: List[str] = Field(default_factory=list)
    min_width_ratio: float = 0.0
    expected_column_count_range: List[int] = Field(default_factory=list)
    non_table_panels: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DoclingExtractionRequest(BaseModel):
    ocr_enabled: bool = False
    fixed_contract: Dict[str, Any] = Field(default_factory=dict)
    requests: List[DoclingSeedRequest] = Field(default_factory=list)
    document: Dict[str, Any] = Field(default_factory=dict)
    document_profile: Dict[str, Any] = Field(default_factory=dict)
    header_footer_profile: Dict[str, Any] = Field(default_factory=dict)
    non_table_panels: List[Dict[str, Any]] = Field(default_factory=list)
    table_hints: Dict[str, Any] = Field(default_factory=dict)
    selection_policy: Dict[str, Any] = Field(default_factory=dict)
    continuation_policy: Dict[str, Any] = Field(default_factory=dict)
    page_family_hints: Dict[str, Any] = Field(default_factory=dict)
    section_map: Dict[str, Any] = Field(default_factory=dict)
    noise_profile: Dict[str, Any] = Field(default_factory=dict)
    anomalies: List[Dict[str, Any]] = Field(default_factory=list)
    source: str = 'parser'
    contract_version: str = CONTRACT_VERSION


class DoclingExtractionResponse(BaseModel):
    contract_version: str = CONTRACT_VERSION
    source: str = ''
    templates: List[Dict[str, Any]] = Field(default_factory=list)
    tables: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
