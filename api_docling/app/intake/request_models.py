from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator

from app.config.settings import CURRENT_RELEASE


class RangeModel(BaseModel):
    start: int
    end: int

    @model_validator(mode='after')
    def _validate_range(self) -> 'RangeModel':
        if self.start < 1 or self.end < 1:
            raise ValueError('start/end devem ser >= 1')
        if self.end < self.start:
            raise ValueError('end não pode ser menor que start')
        return self


class DoclingSeedPages(BaseModel):
    budget_header_page: int = 0
    composition_schema_page: int = 0

    @model_validator(mode='before')
    @classmethod
    def _accept_new_and_old_names(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        out = dict(data)
        if not out.get('budget_header_page') and out.get('budget'):
            out['budget_header_page'] = out.get('budget')
        if not out.get('composition_schema_page') and out.get('composition'):
            out['composition_schema_page'] = out.get('composition')
        return out

    @model_validator(mode='after')
    def _validate_seed_pages(self) -> 'DoclingSeedPages':
        if int(self.budget_header_page or 0) < 1:
            raise ValueError('docling_seed_pages.budget_header_page deve ser >= 1')
        if int(self.composition_schema_page or 0) < 1:
            raise ValueError('docling_seed_pages.composition_schema_page deve ser >= 1')
        return self


class HeaderFooterProfileModel(BaseModel):
    recurring_headers: List[str] = Field(default_factory=list)
    recurring_footers: List[str] = Field(default_factory=list)
    budget_headers: List[str] = Field(default_factory=list)
    budget_footers: List[str] = Field(default_factory=list)
    composition_headers: List[str] = Field(default_factory=list)
    composition_footers: List[str] = Field(default_factory=list)


class RegionHintModel(BaseModel):
    x0: float = 0.0
    y0: float = 0.0
    x1: float = 1.0
    y1: float = 1.0
    normalized: bool = True


class NonTablePanelModel(BaseModel):
    label: str
    description: str = ''
    must_contain_text: List[str] = Field(default_factory=list)
    must_not_contain_text: List[str] = Field(default_factory=list)
    max_width_ratio: float = 0.25
    page_hint: Optional[int] = None


class DoclingGuidanceModel(BaseModel):
    preferred_region: Optional[RegionHintModel] = None
    ignore_regions: List[RegionHintModel] = Field(default_factory=list)
    must_include_text: List[str] = Field(default_factory=list)
    must_exclude_text: List[str] = Field(default_factory=list)
    min_width_ratio: float = 0.5
    expected_column_count_range: List[int] = Field(default_factory=list)


class SelectionPolicyModel(BaseModel):
    reject_if_contains_text: List[str] = Field(default_factory=list)
    reject_if_missing_required_cols: List[str] = Field(default_factory=list)
    reject_if_col_count_below: Optional[int] = None
    reject_if_width_ratio_below: Optional[float] = None
    bonus_if_contains_text: List[str] = Field(default_factory=list)
    bonus_if_has_grouped_headers: bool = False


class ContinuationPolicyModel(BaseModel):
    text_columns: List[str] = Field(default_factory=list)
    numeric_columns: List[str] = Field(default_factory=list)
    money_columns: List[str] = Field(default_factory=list)
    unit_columns: List[str] = Field(default_factory=list)
    strict_columns: List[str] = Field(default_factory=list)


class AIHintsModel(BaseModel):
    document_profile: Dict[str, Any] = Field(default_factory=dict)
    noise_profile: Dict[str, Any] = Field(default_factory=dict)
    header_footer_profile: HeaderFooterProfileModel = Field(default_factory=HeaderFooterProfileModel)
    non_table_panels: List[NonTablePanelModel] = Field(default_factory=list)
    docling_guidance: Dict[str, DoclingGuidanceModel] = Field(default_factory=dict)
    selection_policy: Dict[str, SelectionPolicyModel] = Field(default_factory=dict)
    continuation_policy: Dict[str, ContinuationPolicyModel] = Field(default_factory=dict)
    section_map: Dict[str, Any] = Field(default_factory=dict)
    page_family_hints: Dict[str, Any] = Field(default_factory=dict)
    table_hints: Dict[str, Any] = Field(default_factory=dict)
    anomalies: list[dict] = Field(default_factory=list)
    extra: Dict[str, Any] = Field(default_factory=dict)


class RuntimeOptionsModel(BaseModel):
    mode: str = 'browser_only'
    strict_validation: bool = False
    profile: str = 'default'


class ParseDocumentRequestModel(BaseModel):
    @model_validator(mode='before')
    @classmethod
    def _accept_v61_0_23_light_payload(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        out = dict(data)
        ranges = out.get('ranges') if isinstance(out.get('ranges'), dict) else {}
        # Already in official shape.
        if 'budget' in ranges and 'compositions' in ranges:
            pass
        else:
            budget = ranges.get('orcamento') if isinstance(ranges.get('orcamento'), dict) else None
            comps = ranges.get('composicoes') if isinstance(ranges.get('composicoes'), dict) else None
            if budget or comps:
                out['ranges'] = {
                    'budget': {'start': (budget or {}).get('start') or (budget or {}).get('inicio'), 'end': (budget or {}).get('end') or (budget or {}).get('fim')},
                    'compositions': {'start': (comps or {}).get('start') or (comps or {}).get('inicio'), 'end': (comps or {}).get('end') or (comps or {}).get('fim')},
                }
        if not out.get('docling_seed_pages') and isinstance(out.get('seed_pages'), dict):
            seed = out.get('seed_pages') or {}
            out['docling_seed_pages'] = {
                'budget_header_page': seed.get('budget') or seed.get('budget_header_page'),
                'composition_schema_page': seed.get('composition') or seed.get('composition_schema_page'),
            }
        if isinstance(out.get('observed_tables'), dict) and not out.get('tables'):
            tables: Dict[str, Any] = {}
            for key, value in dict(out.get('observed_tables') or {}).items():
                if not isinstance(value, dict):
                    continue
                norm_key = 'composition' if 'composition' in str(key) else 'budget' if 'budget' in str(key) or 'orcamento' in str(key) else str(key)
                tables[norm_key] = {
                    'observed_headers': value.get('headers_observed') or value.get('observed_headers') or [],
                    'first_row_samples': value.get('first_row_samples') or value.get('first_content_samples') or [],
                    'source': 'observed_tables_light_payload',
                }
            out['tables'] = tables
        if isinstance(out.get('document_hints'), dict):
            hints = out.get('document_hints') or {}
            ai_hints = dict(out.get('ai_hints') or {})
            ai_hints.setdefault('page_family_hints', {})
            ai_hints['page_family_hints'].update({k: v for k, v in hints.items() if k in {'families_detected', 'custom_bank_ids'}})
            out['ai_hints'] = ai_hints
        return out

    version: str = CURRENT_RELEASE
    document: Dict[str, Any] = Field(default_factory=dict)
    ranges: Dict[str, RangeModel]
    docling_seed_pages: DoclingSeedPages
    ai_hints: AIHintsModel = Field(default_factory=AIHintsModel)
    runtime: RuntimeOptionsModel = Field(default_factory=RuntimeOptionsModel)
    base_id: str = 'misto'
    # v59.3: payload final pós-API. A IA continua entregando o contrato base,
    # e a API Docling injeta aqui a estrutura limpa com headers + geometria.
    tables: Dict[str, Any] = Field(default_factory=dict)
    fixed_contract: Dict[str, Any] = Field(default_factory=dict)
    parser_contract: Dict[str, Any] = Field(default_factory=dict)
    docling_clean_payload: Dict[str, Any] = Field(default_factory=dict)
    post_api_integration: Dict[str, Any] = Field(default_factory=dict)
    docling_seed_pdf: Dict[str, Any] = Field(default_factory=dict)
    docling_seed_pdf_policy: Dict[str, Any] = Field(default_factory=dict)
    bypass_cache: bool = False

    def normalized_table_hints(self) -> Dict[str, Any]:
        """Return table hints in the official organized v59 format.

        The new payload keeps the Docling-facing table contract at top-level
        `tables`, exactly as in v58.12. Older parser internals still expect
        the same information under `ai_hints.table_hints`. This helper bridges
        both shapes without duplicating the payload.
        """
        if self.ai_hints.table_hints:
            return dict(self.ai_hints.table_hints or {})
        return dict(self.tables or {})

    @model_validator(mode='after')
    def _validate_expected_ranges(self) -> 'ParseDocumentRequestModel':
        missing = {key for key in ('budget', 'compositions') if key not in self.ranges}
        if missing:
            raise ValueError(f'ranges incompleto: faltando {sorted(missing)}')
        return self

    def browser_options(self) -> Dict[str, Any]:
        budget = self.ranges['budget']
        compositions = self.ranges['compositions']
        return {
            'base_id': self.base_id,
            'orcamento_inicio': budget.start,
            'orcamento_fim': budget.end,
            'composicoes_inicio': compositions.start,
            'composicoes_fim': compositions.end,
            'document_profile': dict(self.ai_hints.document_profile or {}),
            'metadata_extraida_ia': {
                'section_map': dict(self.ai_hints.section_map or {}),
                'page_family_hints': dict(self.ai_hints.page_family_hints or {}),
                'table_hints': self.normalized_table_hints(),
                'noise_profile': dict(self.ai_hints.noise_profile or {}),
                'header_footer_profile': self.ai_hints.header_footer_profile.model_dump(mode='python'),
                'non_table_panels': [x.model_dump(mode='python') for x in (self.ai_hints.non_table_panels or [])],
                'docling_guidance': {k: v.model_dump(mode='python') for k, v in (self.ai_hints.docling_guidance or {}).items()},
                'selection_policy': {k: v.model_dump(mode='python') for k, v in (self.ai_hints.selection_policy or {}).items()},
                'continuation_policy': {k: v.model_dump(mode='python') for k, v in (self.ai_hints.continuation_policy or {}).items()},
                'parser_contract': dict(self.parser_contract or {}),
                'fixed_contract': dict(self.fixed_contract or {}),
                'docling_clean_payload_summary': {
                    'version': (self.docling_clean_payload or {}).get('version'),
                    'tables': sorted(list(((self.docling_clean_payload or {}).get('tables') or {}).keys())),
                },
                'post_api_integration': dict(self.post_api_integration or {}),
                'docling_seed_pdf': dict(self.docling_seed_pdf or {}),
                'docling_seed_pdf_policy': dict(self.docling_seed_pdf_policy or {}),
                'anomalies': list(self.ai_hints.anomalies or []),
                **dict(self.ai_hints.extra or {}),
            },
            'ai_hints': self.ai_hints.model_dump(mode='python'),
            'docling_seed_pages': self.docling_seed_pages.model_dump(mode='python'),
            'strict_validation': bool(self.runtime.strict_validation),
            'performance_profile': str(self.runtime.profile or 'default'),
        }

    def docling_payload(self) -> Dict[str, Any]:
        budget = self.ranges['budget']
        compositions = self.ranges['compositions']
        return {
            'version': self.version,
            'document': dict(self.document or {}),
            'ranges': {
                'budget': budget.model_dump(mode='python'),
                'compositions': compositions.model_dump(mode='python'),
            },
            'docling_seed_pages': self.docling_seed_pages.model_dump(mode='python'),
            'document_profile': dict(self.ai_hints.document_profile or {}),
            'header_footer_profile': self.ai_hints.header_footer_profile.model_dump(mode='python'),
            'non_table_panels': [x.model_dump(mode='python') for x in (self.ai_hints.non_table_panels or [])],
            'docling_guidance': {k: v.model_dump(mode='python') for k, v in (self.ai_hints.docling_guidance or {}).items()},
            'selection_policy': {k: v.model_dump(mode='python') for k, v in (self.ai_hints.selection_policy or {}).items()},
            'continuation_policy': {k: v.model_dump(mode='python') for k, v in (self.ai_hints.continuation_policy or {}).items()},
            'table_hints': self.normalized_table_hints(),
            'page_family_hints': dict(self.ai_hints.page_family_hints or {}),
            'section_map': dict(self.ai_hints.section_map or {}),
            'noise_profile': dict(self.ai_hints.noise_profile or {}),
            'tables': dict(self.tables or {}),
            'fixed_contract': dict(self.fixed_contract or {}),
            'parser_contract': dict(self.parser_contract or {}),
            'docling_clean_payload': dict(self.docling_clean_payload or {}),
            'post_api_integration': dict(self.post_api_integration or {}),
            'docling_seed_pdf': dict(self.docling_seed_pdf or {}),
            'docling_seed_pdf_policy': dict(self.docling_seed_pdf_policy or {}),
            'anomalies': list(self.ai_hints.anomalies or []),
            'extra': dict(self.ai_hints.extra or {}),
        }
