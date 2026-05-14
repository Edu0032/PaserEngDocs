from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List
import os


from app.config.version import CONTRACT_VERSION
from app.domain.structured_table_models import StructuredCell, StructuredColumn, StructuredRow, StructuredTable, StructuredTableBundle
from app.integrations.docling_adapter import adapt_docling_payload
from app.integrations.docling_models import DoclingExtractionRequest, DoclingExtractionResponse, DoclingRegionHint, DoclingSeedRequest
from app.parser.table_candidates import build_table_candidates
from app.parser.table_fusion import fuse_table_candidates

def extract_structures_with_embedded_docling(pdf_bytes: bytes, extraction_request: DoclingExtractionRequest, *, config: Any | None = None) -> StructuredTableBundle:
    from app.integrations.docling_runtime import extract_structures_with_embedded_docling as _runtime_extract
    return _runtime_extract(pdf_bytes, extraction_request, config=config)


@dataclass(slots=True)
class DoclingClientConfig:
    enabled: bool = True
    base_url: str = ''
    extract_path: str = '/extract-table-structure'
    timeout_seconds: float = 20.0
    transport_mode: str = 'auto'
    api_key: str = ''
    api_key_header_name: str = 'x-api-key'
    local_surrogate_enabled: bool = True
    embedded_docling_enabled: bool = True
    embedded_table_mode: str = 'fast'
    embedded_do_cell_matching: bool = False
    embedded_do_ocr: bool = False


class DoclingClient:
    def __init__(self, config: Dict[str, Any] | None = None, *, transport: Any | None = None):
        cfg = dict(config or {})
        self.config = DoclingClientConfig(
            enabled=bool(cfg.get('enabled', True)),
            base_url=str(cfg.get('base_url') or '').rstrip('/'),
            extract_path=str(cfg.get('extract_path') or '/extract-table-structure'),
            timeout_seconds=float(cfg.get('timeout_seconds') or 20.0),
            transport_mode=str(cfg.get('transport_mode') or 'auto').strip().lower() or 'auto',
            api_key=str(cfg.get('api_key') or ''),
            api_key_header_name=str(cfg.get('api_key_header_name') or 'x-api-key'),
            local_surrogate_enabled=bool(cfg.get('local_surrogate_enabled', True)),
            embedded_docling_enabled=bool(cfg.get('embedded_docling_enabled', True)),
            embedded_table_mode=str(cfg.get('embedded_table_mode') or 'fast'),
            embedded_do_cell_matching=bool(cfg.get('embedded_do_cell_matching', False)),
            embedded_do_ocr=bool(cfg.get('embedded_do_ocr', False)),
        )
        self._transport = transport

    @classmethod
    def from_project_config(cls, config_all: Dict[str, Any] | None = None, *, transport: Any | None = None) -> 'DoclingClient':
        if config_all is None:
            from app.config.loader import load_parser_config
            config_all = load_parser_config()
        cfg = dict(config_all.get('docling') or {})
        env_transport = os.getenv('API_PDF_DOCLING_MODE')
        env_base_url = os.getenv('API_PDF_DOCLING_BASE_URL')
        env_surrogate = os.getenv('API_PDF_DOCLING_SURROGATE')
        env_embedded = os.getenv('API_PDF_DOCLING_EMBEDDED')
        env_timeout = os.getenv('DOCLING_TIMEOUT_SECONDS') or os.getenv('API_PDF_DOCLING_TIMEOUT_SECONDS')
        env_ocr = os.getenv('DOCLING_OCR_ENABLED') or os.getenv('API_PDF_DOCLING_OCR_ENABLED')
        env_api_key = os.getenv('API_PDF_DOCLING_API_KEY')
        env_api_key_header = os.getenv('API_PDF_DOCLING_API_KEY_HEADER')
        if env_transport:
            cfg['transport_mode'] = env_transport
        if env_base_url is not None:
            cfg['base_url'] = env_base_url
        if env_surrogate is not None:
            cfg['local_surrogate_enabled'] = str(env_surrogate).strip().lower() in {'1', 'true', 'yes', 'on'}
        if env_embedded is not None:
            cfg['embedded_docling_enabled'] = str(env_embedded).strip().lower() in {'1', 'true', 'yes', 'on'}
        if env_timeout is not None:
            cfg['timeout_seconds'] = env_timeout
        if env_ocr is not None:
            cfg['embedded_do_ocr'] = str(env_ocr).strip().lower() in {'1', 'true', 'yes', 'on'}
        if env_api_key is not None:
            cfg['api_key'] = env_api_key
        if env_api_key_header is not None:
            cfg['api_key_header_name'] = env_api_key_header
        return cls(cfg, transport=transport)

    def extract_structures(self, pdf_bytes: bytes, extraction_request: DoclingExtractionRequest) -> StructuredTableBundle:
        mode = str(self.config.transport_mode or 'auto').strip().lower()
        trace: List[Dict[str, Any]] = []
        if mode in {'auto', 'embedded'} and self.config.embedded_docling_enabled:
            try:
                bundle = self._extract_embedded_docling(pdf_bytes, extraction_request)
                bundle.metadata = dict(bundle.metadata or {})
                bundle.metadata['docling_trace'] = {
                    'docling_attempted': True,
                    'docling_succeeded': True,
                    'docling_used_as_primary': True,
                    'runtime': 'embedded_docling',
                    'attempts': [{'runtime': 'embedded_docling', 'status': 'success'}],
                    'ocr_enabled': bool(self.config.embedded_do_ocr),
                }
                return bundle
            except Exception as exc:
                trace.append({'runtime': 'embedded_docling', 'status': 'failed', 'error': f'{type(exc).__name__}: {exc}'})
                # When Docling is required, fail loudly instead of silently using surrogate.
                if mode == 'embedded' or not self.config.local_surrogate_enabled:
                    raise RuntimeError('Docling embedded foi exigido, mas falhou. Nenhum surrogate foi usado. Erro: ' + f'{type(exc).__name__}: {exc}') from exc
        if self.config.enabled and self.config.base_url and mode in {'auto', 'remote'}:
            try:
                bundle = self._extract_remote(pdf_bytes, extraction_request)
                bundle.metadata = dict(bundle.metadata or {})
                bundle.metadata['docling_trace'] = {
                    'docling_attempted': True,
                    'docling_succeeded': True,
                    'docling_used_as_primary': True,
                    'runtime': 'remote_docling',
                    'attempts': [*trace, {'runtime': 'remote_docling', 'status': 'success'}],
                    'ocr_enabled': bool(self.config.embedded_do_ocr),
                }
                return bundle
            except Exception as exc:
                trace.append({'runtime': 'remote_docling', 'status': 'failed', 'error': f'{type(exc).__name__}: {exc}'})
                if not self.config.local_surrogate_enabled or mode == 'remote':
                    raise RuntimeError('Docling remoto foi exigido, mas falhou. Nenhum surrogate foi usado. Erro: ' + f'{type(exc).__name__}: {exc}') from exc
        bundle = self._extract_local_surrogate(pdf_bytes, extraction_request)
        bundle.metadata = dict(bundle.metadata or {})
        bundle.metadata['docling_trace'] = {
            'docling_attempted': bool(trace),
            'docling_succeeded': False,
            'docling_used_as_primary': False,
            'runtime': 'local_surrogate_pymupdf',
            'attempts': trace,
            'surrogate_used': True,
            'ocr_enabled': False,
        }
        return bundle

    def _extract_embedded_docling(self, pdf_bytes: bytes, extraction_request: DoclingExtractionRequest) -> StructuredTableBundle:
        from app.integrations.docling_runtime import EmbeddedDoclingConfig
        cfg = EmbeddedDoclingConfig(
            enabled=self.config.embedded_docling_enabled,
            do_cell_matching=self.config.embedded_do_cell_matching,
            table_mode=self.config.embedded_table_mode,
            do_ocr=bool(self.config.embedded_do_ocr),
        )
        return extract_structures_with_embedded_docling(pdf_bytes, extraction_request, config=cfg)

    def runtime_summary(self) -> Dict[str, Any]:
        try:
            from app.integrations.docling_runtime import get_embedded_docling_runtime_info
            embedded_runtime = get_embedded_docling_runtime_info()
        except Exception as exc:
            embedded_runtime = {'available': False, 'provider': 'docling_python', 'reason': f'{type(exc).__name__}: {exc}'}
        return {
            'transport_mode': self.config.transport_mode,
            'base_url': self.config.base_url,
            'local_surrogate_enabled': self.config.local_surrogate_enabled,
            'embedded_docling_enabled': self.config.embedded_docling_enabled,
            'embedded_runtime': embedded_runtime,
            'ocr_enabled': bool(self.config.embedded_do_ocr),
            'api_key_configured': bool(self.config.api_key),
        }

    def _extract_remote(self, pdf_bytes: bytes, extraction_request: DoclingExtractionRequest) -> StructuredTableBundle:
        files = {'file': ('document.pdf', pdf_bytes, 'application/pdf')}
        data = {'payload': extraction_request.model_dump_json()}
        import httpx  # lazy import; keeps Pyodide/local parser startup light
        headers = {}
        if self.config.api_key:
            headers[self.config.api_key_header_name or 'x-api-key'] = self.config.api_key
        with httpx.Client(base_url=self.config.base_url, timeout=self.config.timeout_seconds, transport=self._transport) as client:
            response = client.post(self.config.extract_path, files=files, data=data, headers=headers)
            response.raise_for_status()
            payload = response.json()
        return adapt_docling_payload(payload)

    def _extract_local_surrogate(self, pdf_bytes: bytes, extraction_request: DoclingExtractionRequest) -> StructuredTableBundle:
        from app.core.pdf_session import PdfDocumentSession
        profile = dict(extraction_request.document_profile or {})
        tables: List[StructuredTable] = []
        rejected_templates: List[Dict[str, Any]] = []
        with PdfDocumentSession(pdf_bytes) as session:
            for req in extraction_request.requests:
                page_no = int(req.page)
                family = 'budget' if req.kind_hint == 'orcamento_sintetico' else ('sicro' if req.family_hint == 'sicro' else 'composition')
                selection_policy = dict((extraction_request.selection_policy or {}).get('budget' if family == 'budget' else 'composition') or {})
                candidates = build_table_candidates(
                    session,
                    page_no,
                    family=family,
                    profile=profile,
                    bank_hint='SICRO' if req.family_hint == 'sicro' else '',
                    non_table_panels=list(extraction_request.non_table_panels or req.non_table_panels or []),
                    selection_policy=selection_policy,
                )
                if not candidates:
                    continue
                fused = fuse_table_candidates(candidates)
                best = candidates[0]
                column_map = dict(fused.get('column_map') or {})
                rows_matrix = list(fused.get('best_rows') or best.get('rows') or [])
                columns: List[StructuredColumn] = []
                width_hint = max((len(r) for r in rows_matrix), default=0)
                bbox = list(fused.get('best_bbox') or best.get('bbox') or [])
                col_geometry = _approximate_column_geometry(width_hint, bbox)
                used_indices = set()
                for canonical, detail in column_map.items():
                    idx = int(detail.get('col_index') or 0)
                    used_indices.add(idx)
                    geo = col_geometry.get(idx, {})
                    columns.append(StructuredColumn(
                        physical_index=idx,
                        canonical_name=str(canonical),
                        header_text=str(detail.get('header_text') or ''),
                        kind='mapped',
                        x0=geo.get('x0'),
                        x1=geo.get('x1'),
                        width=geo.get('width'),
                        confidence=float(detail.get('score') or fused.get('confidence') or 0.0),
                        metadata={'seeded_from': 'local_surrogate'},
                    ))
                for idx in range(width_hint):
                    if idx in used_indices:
                        continue
                    header_text = ''
                    if rows_matrix:
                        try:
                            header_text = str((rows_matrix[0] or [])[idx] or '')
                        except Exception:
                            header_text = ''
                    geo = col_geometry.get(idx, {})
                    columns.append(StructuredColumn(
                        physical_index=idx,
                        canonical_name='',
                        header_text=header_text,
                        kind='unmapped',
                        x0=geo.get('x0'),
                        x1=geo.get('x1'),
                        width=geo.get('width'),
                        confidence=max(float(fused.get('confidence') or 0.0) * 0.5, 0.1),
                        metadata={'seeded_from': 'local_surrogate'},
                    ))
                columns.sort(key=lambda col: int(col.physical_index))

                header_rows = [int(fused.get('header_index'))] if fused.get('header_index') is not None else [0]
                header_rows = [x for x in header_rows if x >= 0]
                sample_limit = max((max(header_rows, default=-1) + 1), 2)
                sample_limit = min(max(sample_limit, 1), max(len(rows_matrix), 1))
                structured_rows: List[StructuredRow] = []
                for row_idx, row in enumerate(rows_matrix[:sample_limit]):
                    cells: List[StructuredCell] = []
                    for col_idx, cell_text in enumerate(list(row or [])):
                        canonical_name = next((col.canonical_name for col in columns if int(col.physical_index) == col_idx and col.canonical_name), '')
                        geo = col_geometry.get(col_idx, {})
                        cells.append(StructuredCell(
                            row_index=row_idx,
                            col_index=col_idx,
                            text=str(cell_text or ''),
                            canonical_name=canonical_name,
                            bbox=[geo.get('x0'), 0.0, geo.get('x1'), 0.0] if geo else [],
                            confidence=float(fused.get('confidence') or 0.0),
                            page=page_no,
                            is_header=row_idx in header_rows,
                        ))
                    structured_rows.append(StructuredRow(
                        row_index=row_idx,
                        page=page_no,
                        bbox=[],
                        cells=cells,
                        kind='header' if row_idx in header_rows else 'body',
                    ))

                group_headers = list((((req.metadata or {}).get('grouped_headers')) or []))
                table_hint_key = str((req.metadata or {}).get('table_hint_key') or '')
                table_hint = dict((extraction_request.table_hints or {}).get(table_hint_key) or {}) if table_hint_key else {}
                if table_hint.get('grouped_headers') and not group_headers:
                    group_headers = list(table_hint.get('grouped_headers') or [])

                tables.append(StructuredTable(
                    table_id=req.table_id or f'p{page_no}:{req.kind_hint}',
                    kind=req.kind_hint,
                    family=req.family_hint or ('budget' if req.kind_hint == 'orcamento_sintetico' else 'sinapi_like'),
                    page_start=page_no,
                    page_end=page_no,
                    bbox=bbox,
                    header_rows=header_rows,
                    body_rows_start=(max(header_rows) + 1) if header_rows else 0,
                    column_schema=columns,
                    rows=structured_rows,
                    confidence=float(fused.get('confidence') or best.get('confidence') or 0.0),
                    source='local_surrogate_pymupdf',
                    metadata={
                        'best_strategy': fused.get('best_strategy'),
                        'candidate_count': fused.get('candidate_count'),
                        'page': page_no,
                        'sample_rows_included': sample_limit,
                        'total_rows_detected': len(rows_matrix),
                        'grouped_headers': group_headers,
                        'selection_policy': selection_policy,
                    },
                ))
        response = DoclingExtractionResponse(
            contract_version=CONTRACT_VERSION,
            source='local_surrogate_pymupdf',
            templates=[public_template_from_table(table) for table in tables],
            tables=[table.model_dump(mode='python') for table in tables],
            metadata={
                'request_count': len(extraction_request.requests),
                'matched_tables': len(tables),
                'response_mode': 'compact_template_plus_seed_rows',
                'rejected_templates': rejected_templates,
            },
        )
        return adapt_docling_payload(response.model_dump(mode='python'))


def _approximate_column_geometry(width_hint: int, bbox: List[float]) -> Dict[int, Dict[str, float]]:
    if width_hint <= 0 or len(bbox) != 4:
        return {}
    x0, _, x1, _ = [float(v or 0.0) for v in bbox[:4]]
    if x1 <= x0:
        return {}
    step = (x1 - x0) / float(width_hint)
    out: Dict[int, Dict[str, float]] = {}
    for idx in range(width_hint):
        left = x0 + idx * step
        right = x0 + (idx + 1) * step
        out[idx] = {'x0': left, 'x1': right, 'width': right - left}
    return out


def public_template_from_table(table: StructuredTable) -> Dict[str, Any]:
    grouped_headers = list(((table.metadata or {}).get('grouped_headers') or []))
    return {
        'template_id': table.table_id,
        'kind': table.kind,
        'family': table.family,
        'seed_page': table.page_start,
        'header_rows': list(table.header_rows or []),
        'body_rows_start': table.body_rows_start,
        'confidence': float(table.confidence or 0.0),
        'grouped_headers': grouped_headers,
        'column_schema': [
            {
                'physical_index': int(col.physical_index),
                'canonical_name': str(col.canonical_name or ''),
                'header_text': str(col.header_text or ''),
                'kind': str(col.kind or ''),
                'x0': col.x0,
                'x1': col.x1,
                'width': col.width,
                'confidence': float(col.confidence or 0.0),
                'metadata': dict(col.metadata or {}),
            }
            for col in table.column_schema
        ],
        'metadata': dict(table.metadata or {}),
    }


def build_public_docling_payload(bundle: StructuredTableBundle) -> Dict[str, Any]:
    return {
        'contract_version': bundle.contract_version,
        'source': bundle.source,
        'templates': [public_template_from_table(table) for table in bundle.tables],
        'tables': [table.model_dump(mode='python') for table in bundle.tables],
        'metadata': {
            **dict(bundle.metadata or {}),
            'summary': bundle.summary(),
        },
    }




def _sanitize_table_hints_for_fast_docling(table_hints: Dict[str, Any]) -> Dict[str, Any]:
    """Keep the Docling seed request lightweight and avoid treating real
    composition rows as body stop markers. This mutates a shallow copy only.
    """
    hints = dict(table_hints or {})
    real_row_markers = {
        'composicao', 'composição', 'composicao auxiliar', 'composição auxiliar', 'insumo'
    }
    for key in ('composition', 'composicoes_sinapi', 'composicoes', 'budget', 'orcamento_sintetico'):
        if key not in hints or not isinstance(hints.get(key), dict):
            continue
        item = dict(hints[key])
        if key in {'composition', 'composicoes_sinapi', 'composicoes'}:
            cleaned = []
            for marker in list(item.get('body_stop_markers') or []):
                norm = str(marker or '').strip().lower()
                if norm in real_row_markers:
                    continue
                cleaned.append(marker)
            item['body_stop_markers'] = cleaned
        hints[key] = item
    return hints


def _sanitize_fixed_contract_for_fast_docling(fixed_contract: Dict[str, Any]) -> Dict[str, Any]:
    contract = dict(fixed_contract or {})
    contract['runtime_profile'] = 'default'
    contract['ocr_enabled'] = False
    crop = dict(contract.get('crop_policy') or {})
    for family in ('budget', 'composition'):
        fam = dict(crop.get(family) or {})
        fam.setdefault('mode', 'line_window')
        fam['lines_above'] = 1
        fam['lines_below'] = 1
        fam['max_extra_lines'] = 0
        crop[family] = fam
    contract['crop_policy'] = crop
    execution = dict(contract.get('docling_execution_policy') or {})
    execution['max_docling_attempts'] = 1
    execution['ocr_enabled'] = False
    # In production/Lovable the parser can still run with legacy fallback if the
    # structure API fails; do not retry Docling repeatedly for a seed-only task.
    execution.setdefault('fallback_role', 'diagnostic_only')
    contract['docling_execution_policy'] = execution
    return contract

def build_extraction_request(
    *,
    budget_header_page: int,
    composition_schema_page: int,
    budget_range: Dict[str, int] | None = None,
    compositions_range: Dict[str, int] | None = None,
    document: Dict[str, Any] | None = None,
    document_profile: Dict[str, Any] | None = None,
    header_footer_profile: Dict[str, Any] | None = None,
    table_hints: Dict[str, Any] | None = None,
    page_family_hints: Dict[str, Any] | None = None,
    section_map: Dict[str, Any] | None = None,
    noise_profile: Dict[str, Any] | None = None,
    anomalies: List[Dict[str, Any]] | None = None,
    non_table_panels: List[Dict[str, Any]] | None = None,
    docling_guidance: Dict[str, Any] | None = None,
    selection_policy: Dict[str, Any] | None = None,
    continuation_policy: Dict[str, Any] | None = None,
    fixed_contract: Dict[str, Any] | None = None,
    hints: Dict[str, Any] | None = None,
) -> DoclingExtractionRequest:
    if hints and not any([header_footer_profile, table_hints, page_family_hints, section_map, noise_profile, anomalies]):
        hints = dict(hints or {})
        header_footer_profile = dict(hints.get('header_footer_profile') or {})
        table_hints = dict(hints.get('table_hints') or {})
        page_family_hints = dict(hints.get('page_family_hints') or {})
        section_map = dict(hints.get('section_map') or {})
        noise_profile = dict(hints.get('noise_profile') or {})
        anomalies = list(hints.get('anomalies') or [])
        non_table_panels = list(hints.get('non_table_panels') or [])
        docling_guidance = dict(hints.get('docling_guidance') or {})
        selection_policy = dict(hints.get('selection_policy') or {})
        continuation_policy = dict(hints.get('continuation_policy') or {})
    table_hints = _sanitize_table_hints_for_fast_docling(dict(table_hints or {}))
    non_table_panels = list(non_table_panels or [])
    docling_guidance = dict(docling_guidance or {})
    selection_policy = dict(selection_policy or {})
    continuation_policy = dict(continuation_policy or {})
    fixed_contract = _sanitize_fixed_contract_for_fast_docling(dict(fixed_contract or {}))
    ocr_enabled = bool(fixed_contract.get("ocr_enabled", False))
    budget_hint = dict(table_hints.get('budget') or table_hints.get('orcamento_sintetico') or {})
    composition_hint = dict(table_hints.get('composition') or table_hints.get('composicoes_sinapi') or {})
    budget_guidance = dict(docling_guidance.get('budget') or docling_guidance.get('orcamento_sintetico') or {})
    composition_guidance = dict(docling_guidance.get('composition') or docling_guidance.get('composicoes') or {})
    def _derived_guidance(base: Dict[str, Any], hint: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(base or {})
        observed = [dict(x or {}) for x in list(hint.get('observed_headers') or [])]
        if not out.get('must_include_text'):
            out['must_include_text'] = [str(x.get('text') or '').strip() for x in observed if str(x.get('text') or '').strip()][:6]
        if not out.get('expected_column_count_range'):
            count = int(hint.get('physical_column_count_expected') or hint.get('logical_column_count_expected') or 0)
            if count > 0:
                out['expected_column_count_range'] = [count, count]
        if not out.get('min_width_ratio'):
            out['min_width_ratio'] = 0.70
        return out

    budget_guidance = _derived_guidance(budget_guidance, budget_hint)
    composition_guidance = _derived_guidance(composition_guidance, composition_hint)
    return DoclingExtractionRequest(
        ocr_enabled=ocr_enabled,
        fixed_contract=fixed_contract,
        requests=[
            DoclingSeedRequest(
                page=int(budget_header_page),
                kind_hint='orcamento_sintetico',
                family_hint='budget',
                table_id=f'budget:p{budget_header_page}',
                applies_to_range=dict(budget_range or {}),
                preferred_region=_region_or_none(budget_guidance.get('preferred_region')),
                ignore_regions=[_region_or_none(x) for x in list(budget_guidance.get('ignore_regions') or []) if _region_or_none(x) is not None],
                must_include_text=list(budget_guidance.get('must_include_text') or []),
                must_exclude_text=list(budget_guidance.get('must_exclude_text') or []),
                min_width_ratio=float(budget_guidance.get('min_width_ratio') or 0.0),
                expected_column_count_range=list(budget_guidance.get('expected_column_count_range') or []),
                non_table_panels=non_table_panels,
                metadata={
                    'table_hint_key': 'budget',
                    'grouped_headers': list(budget_hint.get('header_groups') or budget_hint.get('grouped_headers') or []),
                    'header_rows_expected': budget_hint.get('header_rows_expected'),
                },
            ),
            DoclingSeedRequest(
                page=int(composition_schema_page),
                kind_hint='composicao_sinapi_like',
                family_hint='sinapi_like',
                table_id=f'composition:p{composition_schema_page}',
                applies_to_range=dict(compositions_range or {}),
                preferred_region=_region_or_none(composition_guidance.get('preferred_region')),
                ignore_regions=[_region_or_none(x) for x in list(composition_guidance.get('ignore_regions') or []) if _region_or_none(x) is not None],
                must_include_text=list(composition_guidance.get('must_include_text') or []),
                must_exclude_text=list(composition_guidance.get('must_exclude_text') or []),
                min_width_ratio=float(composition_guidance.get('min_width_ratio') or 0.0),
                expected_column_count_range=list(composition_guidance.get('expected_column_count_range') or []),
                non_table_panels=non_table_panels,
                metadata={
                    'table_hint_key': 'composition',
                    'grouped_headers': list(composition_hint.get('header_groups') or composition_hint.get('grouped_headers') or []),
                    'header_rows_expected': composition_hint.get('header_rows_expected'),
                },
            ),
        ],
        document=dict(document or {}),
        document_profile=dict(document_profile or {}),
        header_footer_profile=dict(header_footer_profile or {}),
        non_table_panels=non_table_panels,
        table_hints=table_hints,
        selection_policy=selection_policy,
        continuation_policy=continuation_policy,
        page_family_hints=dict(page_family_hints or {}),
        section_map=dict(section_map or {}),
        noise_profile=dict(noise_profile or {}),
        anomalies=list(anomalies or []),
        source=CONTRACT_VERSION,
        contract_version=CONTRACT_VERSION,
    )


def _region_or_none(value: Any) -> DoclingRegionHint | None:
    if value in (None, '', {}):
        return None
    if isinstance(value, DoclingRegionHint):
        return value
    try:
        return DoclingRegionHint.model_validate(value)
    except Exception:
        return None
