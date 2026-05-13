from __future__ import annotations

import json
import time
import uuid
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Dict, Tuple

from app.config.loader import load_parser_config, resolve_runtime_config, merge_base_config_layers, validate_user_base_config_overlay
from app.config.version import CURRENT_RELEASE
from app.core.context_markers import split_dynamic_phrases
from app.core.document_profile import merge_dynamic_phrases, normalize_document_profile, summarize_document_profile
from app.core.output_compact import compact_parse_result, prune_runtime_only_fields
from app.parser.pipeline import parse_document
from app.parser.staged import parse_budget_stage, parse_compositions_stage, merge_staged_results
from app.parser.docling_schema_normalizer import normalize_docling_payload


class BrowserParseError(RuntimeError):
    """Erro genérico para execução do parser no navegador."""

    def __init__(self, message: str, *, code: str = 'browser_parse_error', detail: Any = None):
        super().__init__(message)
        self.code = code
        self.detail = detail


class BrowserValidationError(BrowserParseError):
    """Erro de validação estrita em modo browser."""

    def __init__(self, message: str, *, detail: Any = None):
        super().__init__(message, code='validation_failed', detail=detail)


@dataclass(slots=True)
class BrowserParseOptions:
    base_id: str = 'misto'
    orcamento_inicio: int = 0
    orcamento_fim: int = 0
    composicoes_inicio: int = 0
    composicoes_fim: int = 0
    obra_nome: str | None = None
    obra_localizacao: str | None = None
    orgao_nome: str | None = None
    prefeitura_nome: str | None = None
    contratante_nome: str | None = None
    dynamic_ignore_phrases: list[str] | str | None = None
    metadata_extraida_ia: Dict[str, Any] | None = None
    document_profile: Dict[str, Any] | None = None
    header_profile_enabled: bool | None = True
    noise_cleanup_mode: str | None = 'contextual'
    table_structure_enabled: bool | None = True
    table_structure_strategy: str | None = 'hybrid'
    strict_validation: bool | None = None
    filename: str = 'upload.pdf'
    content_type: str = 'application/pdf'
    performance_profile: str = 'browser_robust'
    ai_hints: Dict[str, Any] | None = None
    docling_seed_pages: Dict[str, Any] | None = None
    structured_tables: Dict[str, Any] | None = None
    output_options: Dict[str, Any] | None = None
    parser_contract: Dict[str, Any] | None = None
    tables: Dict[str, Any] | None = None
    fixed_contract: Dict[str, Any] | None = None
    runtime: Dict[str, Any] | None = None
    docling_clean_payload: Dict[str, Any] | None = None
    normalizer_clean_payload: Dict[str, Any] | None = None
    normalizer_report: Dict[str, Any] | None = None
    normalizer_mode: str | None = 'local_pyodide'
    geometry_evidence: Dict[str, Any] | None = None
    docling_seed_pdf: Dict[str, Any] | None = None
    user_base_config: Dict[str, Any] | None = None


REQUIRED_BROWSER_OPTION_FIELDS = (
    'orcamento_inicio',
    'orcamento_fim',
    'composicoes_inicio',
    'composicoes_fim',
)



def _adapt_lightweight_lovable_payload(options: Dict[str, Any]) -> Dict[str, Any]:
    """Accept the official v61.0.23 lightweight Lovable payload.

    New payloads carry document-specific facts under ranges/seed_pages and keep
    fixed execution rules in base_config.  The browser parser still consumes the
    historical flat BrowserParseOptions internally, so this adapter is the only
    compatibility layer.
    """
    data = dict(options or {})
    ranges = data.get('ranges') if isinstance(data.get('ranges'), dict) else {}
    if ranges and not all(k in data for k in REQUIRED_BROWSER_OPTION_FIELDS):
        budget = ranges.get('budget') or ranges.get('orcamento') or {}
        comps = ranges.get('compositions') or ranges.get('composicoes') or {}
        data['orcamento_inicio'] = data.get('orcamento_inicio') or budget.get('start') or budget.get('inicio')
        data['orcamento_fim'] = data.get('orcamento_fim') or budget.get('end') or budget.get('fim')
        data['composicoes_inicio'] = data.get('composicoes_inicio') or comps.get('start') or comps.get('inicio') or 0
        data['composicoes_fim'] = data.get('composicoes_fim') or comps.get('end') or comps.get('fim') or 0
    document = data.get('document') if isinstance(data.get('document'), dict) else {}
    if document:
        for src, dst in (
            ('filename', 'filename'), ('obra_nome', 'obra_nome'), ('obra_localizacao', 'obra_localizacao'),
            ('orgao_nome', 'orgao_nome'), ('contratante_nome', 'contratante_nome'), ('content_type', 'content_type'),
        ):
            if data.get(dst) in (None, '') and document.get(src) not in (None, ''):
                data[dst] = document.get(src)
    seed_pages = data.get('seed_pages') if isinstance(data.get('seed_pages'), dict) else {}
    if seed_pages and not data.get('docling_seed_pages'):
        data['docling_seed_pages'] = {
            'budget_header_page': seed_pages.get('budget') or seed_pages.get('budget_header_page'),
            'composition_schema_page': seed_pages.get('composition') or seed_pages.get('composition_schema_page'),
        }
    observed = data.get('observed_tables') if isinstance(data.get('observed_tables'), dict) else {}
    if observed and not data.get('tables'):
        tables = {}
        for key, value in observed.items():
            if not isinstance(value, dict):
                continue
            norm_key = 'composition' if 'composition' in key else 'budget' if 'budget' in key or 'orcamento' in key else key
            headers = value.get('headers_observed') or value.get('observed_headers') or []
            first_rows = value.get('first_row_samples') or value.get('first_content_samples') or []
            columns = value.get('columns') or value.get('observed_columns') or []
            table_entry = {
                'observed_headers': headers,
                'first_row_samples': first_rows,
                'source': 'observed_tables_light_payload',
            }
            if columns:
                table_entry['columns'] = columns
            tables[norm_key] = table_entry
        data['tables'] = tables
    hints = data.get('document_hints') if isinstance(data.get('document_hints'), dict) else {}
    if hints:
        ai_hints = dict(data.get('ai_hints') or {})
        ai_hints.setdefault('page_family_hints', {})
        ai_hints['page_family_hints'].update({k: v for k, v in hints.items() if k in {'families_detected', 'custom_bank_ids'}})
        data['ai_hints'] = ai_hints
    # Remove keys not declared in BrowserParseOptions to avoid dataclass errors.
    allowed = set(BrowserParseOptions.__dataclass_fields__.keys())
    return {k: v for k, v in data.items() if k in allowed}

def _validate_page_range(name: str, start: int, end: int, *, allow_zero_pair: bool = False) -> tuple[int, int]:
    if allow_zero_pair and start == 0 and end == 0:
        return start, end
    if start < 1 or end < 1:
        raise BrowserParseError(
            f'Intervalo inválido para {name}: páginas devem ser >= 1.',
            code='invalid_page_range',
            detail={'name': name, 'start': start, 'end': end},
        )
    if end < start:
        raise BrowserParseError(
            f'Intervalo inválido para {name}: página final menor que a inicial.',
            code='invalid_page_range',
            detail={'name': name, 'start': start, 'end': end},
        )
    return start, end


def _coerce_positive_int(name: str, value: Any) -> int:
    try:
        return int(value)
    except Exception as exc:
        raise BrowserParseError(
            f'Campo inválido: {name} precisa ser inteiro.',
            code='invalid_payload',
            detail={'field': name, 'value': value},
        ) from exc


def _as_options(options: BrowserParseOptions | Dict[str, Any]) -> BrowserParseOptions:
    if isinstance(options, BrowserParseOptions):
        return options
    if not isinstance(options, dict):
        raise BrowserParseError('Payload options inválido.', code='invalid_payload', detail={'received_type': type(options).__name__})

    data = _adapt_lightweight_lovable_payload(options)
    missing = [field for field in REQUIRED_BROWSER_OPTION_FIELDS if field not in data]
    if missing:
        raise BrowserParseError(
            'Payload options incompleto.',
            code='missing_required_options',
            detail={'missing_fields': missing},
        )
    for field in REQUIRED_BROWSER_OPTION_FIELDS:
        data[field] = _coerce_positive_int(field, data.get(field))

    profile = data.get('document_profile')
    if profile is None:
        data['document_profile'] = {}
    else:
        try:
            data['document_profile'] = normalize_document_profile(profile)
        except TypeError as exc:
            raise BrowserParseError(
                'document_profile deve ser um objeto/dicionário.',
                code='invalid_document_profile',
                detail={'received_type': type(profile).__name__},
            ) from exc

    dynamic_phrases = merge_dynamic_phrases(data.get('dynamic_ignore_phrases'), data.get('document_profile'))
    data['dynamic_ignore_phrases'] = dynamic_phrases

    metadata = data.get('metadata_extraida_ia')
    if metadata is None:
        data['metadata_extraida_ia'] = {}
    elif not isinstance(metadata, dict):
        raise BrowserParseError(
            'metadata_extraida_ia deve ser um objeto/dicionário.',
            code='invalid_metadata_extraida_ia',
            detail={'received_type': type(metadata).__name__},
        )

    base_id = str(data.get('base_id') or 'misto').strip() or 'misto'
    data['base_id'] = base_id
    data['header_profile_enabled'] = bool(data.get('header_profile_enabled', True))
    data['table_structure_enabled'] = bool(data.get('table_structure_enabled', True))
    data['noise_cleanup_mode'] = str(data.get('noise_cleanup_mode') or 'contextual').strip() or 'contextual'
    data['table_structure_strategy'] = str(data.get('table_structure_strategy') or 'hybrid').strip() or 'hybrid'
    raw_performance_profile = str(data.get('performance_profile') or 'browser_robust').strip().lower()
    allowed_performance_profiles = {'browser_fast','fast','browser','browser_robust','robust','standard','default'}
    data['performance_profile'] = raw_performance_profile if raw_performance_profile in allowed_performance_profiles else 'default'
    data['filename'] = str(data.get('filename') or 'upload.pdf').strip() or 'upload.pdf'
    data['content_type'] = str(data.get('content_type') or 'application/pdf').strip() or 'application/pdf'
    for field in ('ai_hints', 'docling_seed_pages', 'structured_tables', 'output_options', 'parser_contract', 'tables', 'fixed_contract', 'runtime', 'docling_clean_payload', 'normalizer_clean_payload', 'normalizer_report', 'geometry_evidence', 'docling_seed_pdf'):
        value = data.get(field)
        if value is None:
            data[field] = {}
        elif not isinstance(value, dict):
            raise BrowserParseError(f'{field} deve ser um objeto/dicionário.', code='invalid_payload', detail={'field': field, 'received_type': type(value).__name__})
    data['normalizer_mode'] = str(data.get('normalizer_mode') or data.get('runtime', {}).get('normalizer_mode') or 'local_pyodide').strip() or 'local_pyodide'
    return BrowserParseOptions(**data)



def _build_context(opts: BrowserParseOptions) -> dict:
    # v60.5.2: normalize Docling structure using IA-provided canonical tables and sample_text.
    normalizer_clean_payload = normalize_docling_payload(opts.normalizer_clean_payload or {}, opts.tables or {}) if opts.normalizer_clean_payload else {}
    structured_tables_raw = opts.structured_tables or normalizer_clean_payload or opts.docling_clean_payload or {}
    structured_tables = normalize_docling_payload(structured_tables_raw, opts.tables or {}) if structured_tables_raw else {}
    docling_clean_payload = normalize_docling_payload(opts.docling_clean_payload or {}, opts.tables or {}) if opts.docling_clean_payload else {}
    # v61: parser consumes Normalizer output first when present; Docling remains fallback.
    if normalizer_clean_payload:
        structured_tables = normalizer_clean_payload
    return {
        'obra_nome': opts.obra_nome,
        'obra_localizacao': opts.obra_localizacao,
        'orgao_nome': opts.orgao_nome,
        'prefeitura_nome': opts.prefeitura_nome,
        'contratante_nome': opts.contratante_nome,
        'dynamic_ignore_phrases': opts.dynamic_ignore_phrases,
        'metadata_extraida_ia': opts.metadata_extraida_ia or {},
        'document_profile': opts.document_profile or {},
        'header_profile_enabled': bool(opts.header_profile_enabled),
        'noise_cleanup_mode': opts.noise_cleanup_mode,
        'ai_hints': opts.ai_hints or {},
        'docling_seed_pages': opts.docling_seed_pages or {},
        'structured_tables': structured_tables,
        'output_options': opts.output_options or {},
        'parser_contract': opts.parser_contract or {},
        'tables': opts.tables or {},
        'fixed_contract': opts.fixed_contract or {},
        'runtime': opts.runtime or {},
        'docling_clean_payload': docling_clean_payload,
        'normalizer_clean_payload': normalizer_clean_payload,
        'normalizer_report': opts.normalizer_report or (normalizer_clean_payload.get('metadata', {}) if isinstance(normalizer_clean_payload, dict) else {}).get('normalizer_report', {}),
        'normalizer_mode': opts.normalizer_mode or 'local_pyodide',
        'geometry_evidence': opts.geometry_evidence or {},
        'docling_seed_pdf': opts.docling_seed_pdf or {},
    }



def _build_ranges(opts: BrowserParseOptions) -> Dict[str, Tuple[int, int]]:
    return {
        'orcamento': _validate_page_range('orçamento sintético', opts.orcamento_inicio, opts.orcamento_fim),
        'composicoes': _validate_page_range('composições', opts.composicoes_inicio, opts.composicoes_fim, allow_zero_pair=True),
    }



def _runtime_for_browser(config_all: dict, opts: BrowserParseOptions) -> dict:
    runtime_cfg = deepcopy(resolve_runtime_config(config_all))
    runtime_cfg.setdefault('performance', {})
    profile = str(opts.performance_profile or 'default') or 'default'
    runtime_cfg['performance']['profile'] = profile
    runtime_cfg['performance']['compact_validation'] = True
    runtime_cfg['performance']['correction_report_enabled'] = True
    runtime_cfg['performance']['composition_math_validation_enabled'] = True
    runtime_cfg['performance']['table_structure_enabled'] = bool(opts.table_structure_enabled)
    runtime_cfg['performance']['table_structure_strategy'] = str(opts.table_structure_strategy or 'hybrid')
    runtime_cfg['performance']['noise_cleanup_mode'] = str(opts.noise_cleanup_mode or 'contextual')
    runtime_cfg['performance']['header_profile_enabled'] = bool(opts.header_profile_enabled)
    runtime_cfg['performance'].setdefault('budget_text_engine', 'pypdf')
    runtime_perf = dict(((opts.runtime or {}).get('performance') or {}) if isinstance(opts.runtime, dict) else {})
    runtime_cfg['performance']['composition_text_fallback_mode'] = str(
        ((opts.runtime or {}).get('composition_text_fallback_mode') if isinstance(opts.runtime, dict) else '')
        or runtime_perf.get('composition_text_fallback_mode')
        or 'smart'
    )
    runtime_cfg['performance']['composition_table_extraction_strategy'] = 'adaptive'
    runtime_cfg['performance']['composition_table_probe_limit'] = max(int(runtime_cfg['performance'].get('composition_table_probe_limit') or 8), 8)
    runtime_cfg['performance']['composition_finalize_text_only'] = False
    runtime_cfg['performance']['composition_interval_processing_mode'] = 'layered'
    runtime_cfg['performance']['composition_tipo_recovery_mode'] = 'disabled'
    runtime_cfg['performance']['composition_compact_debug'] = False
    runtime_cfg['performance']['composition_preclassification_neighbor_buffer'] = max(int(runtime_cfg['performance'].get('composition_preclassification_neighbor_buffer') or 1), 1)
    runtime_cfg['performance']['composition_layout_template_strategy'] = 'standard_first'
    runtime_cfg['performance']['composition_sicro_template_mode'] = 'per_section'
    runtime_cfg['performance']['composition_generic_text_include_pure_sicro_pages'] = True
    runtime_cfg['performance']['composition_text_candidate_min_score'] = 4
    runtime_cfg['performance']['composition_text_candidate_neighbor_buffer'] = 1
    runtime_cfg.setdefault('output_options', {})
    runtime_cfg['output_options'].setdefault('include_tipo_in_final_json', False)
    runtime_cfg['output_options'].update(dict(opts.output_options or {}))
    return runtime_cfg



def _finalize_result(result: dict, *, config_all: dict, runtime_cfg: dict, opts: BrowserParseOptions, elapsed_ms: float, mode: str = 'browser') -> dict:
    result = compact_parse_result(result)
    result = prune_runtime_only_fields(result)
    strict = bool((runtime_cfg.get('validation') or {}).get('strict', False)) if opts.strict_validation is None else bool(opts.strict_validation)
    parser_perf = dict(((result.get('meta') or {}).get('performance') or {}))
    if parser_perf:
        parser_perf['wall_clock_ms'] = elapsed_ms
        parser_perf.setdefault('mode', mode)
    qgate = ((result.get('auditoria_final') or {}).get('quality_gate') or {}) if isinstance(result.get('auditoria_final'), dict) else {}
    corr_resumo = ((result.get('documento_correcao') or {}).get('resumo') or {}) if isinstance(result.get('documento_correcao'), dict) else {}
    if isinstance(qgate, dict) and qgate and not qgate.get('ok', True):
        result['status'] = 'quality_gate_failed'
    elif int(corr_resumo.get('total_registros_com_erro') or 0) > 0:
        result['status'] = 'ok_with_warnings'
    else:
        result['status'] = 'ok'
    result['meta'] = {
        'request_id': uuid.uuid4().hex,
        'parser_version': str(((config_all or {}).get('project') or {}).get('current_release') or CURRENT_RELEASE),
        'config_schema_version': str(runtime_cfg.get('config_schema_version', 'unknown')),
        'processing_time_ms': elapsed_ms,
        'environment': mode,
        'input_metadata': {
            'filename': opts.filename,
            'content_type': opts.content_type,
            'size_bytes': 0,
            'ranges': _build_ranges(opts),
            'strict_validation': strict,
            'base_id': opts.base_id,
            'performance_profile': opts.performance_profile,
            'metadata_extraida_ia': opts.metadata_extraida_ia or {},
            'document_profile': summarize_document_profile(opts.document_profile or {}),
            'header_profile_enabled': bool(opts.header_profile_enabled),
            'noise_cleanup_mode': opts.noise_cleanup_mode,
            'table_structure_enabled': bool(opts.table_structure_enabled),
            'table_structure_strategy': opts.table_structure_strategy,
            'ai_hints': opts.ai_hints or {},
            'docling_seed_pages': opts.docling_seed_pages or {},
            'structured_tables': {
                'source': (opts.structured_tables or {}).get('source'),
                'table_count': len(((opts.structured_tables or {}).get('tables') or [])),
            },
            'tables_contract_present': bool(opts.tables),
            'docling_seed_pdf': opts.docling_seed_pdf or {},
        },
        'performance': parser_perf,
    }
    total_erros = int(((result.get('validacao') or {}).get('resumo') or {}).get('total_erros') or 0)
    if strict and total_erros:
        raise BrowserValidationError(
            'Falha de validação.',
            detail={'total_erros': total_erros, 'ocorrencias': (result.get('validacao') or {}).get('ocorrencias', [])[:20]},
        )
    return result



def _resolve_config_all(config_all: dict | None, opts: BrowserParseOptions) -> dict:
    admin_config = config_all or load_parser_config()
    user_overlay = opts.user_base_config if isinstance(opts.user_base_config, dict) else None
    if user_overlay:
        validation = validate_user_base_config_overlay(user_overlay)
        merged = merge_base_config_layers(admin_config, user_overlay)
        merged.setdefault('metadata', {})['user_base_config_validation'] = validation
        return merged
    return admin_config

def parse_document_browser(
    pdf_bytes: bytes,
    options: BrowserParseOptions | Dict[str, Any],
    *,
    config_all: dict | None = None,
) -> dict:
    """Executa o parser completo em modo browser/Pyodide."""
    if not pdf_bytes:
        raise BrowserParseError('O arquivo PDF está vazio.', code='empty_file')

    opts = _as_options(options)
    config_all = _resolve_config_all(config_all, opts)
    runtime_cfg = _runtime_for_browser(config_all, opts)
    context = _build_context(opts)
    ranges = _build_ranges(opts)

    started = time.perf_counter()
    result = parse_document(pdf_bytes=pdf_bytes, ranges=ranges, config=runtime_cfg, context=context)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    result = _finalize_result(result, config_all=config_all, runtime_cfg=runtime_cfg, opts=opts, elapsed_ms=elapsed_ms, mode='browser')
    result['meta']['input_metadata']['size_bytes'] = len(pdf_bytes)
    return result


def parse_document_browser_json(
    pdf_bytes: bytes,
    options: BrowserParseOptions | Dict[str, Any],
    *,
    ensure_ascii: bool = False,
    config_all: dict | None = None,
) -> str:
    result = parse_document_browser(pdf_bytes, options, config_all=config_all)
    return json.dumps(result, ensure_ascii=ensure_ascii)


# --- novas funções para pipeline em etapas (browser paralelo) ---
def parse_budget_stage_browser(pdf_bytes: bytes, options: BrowserParseOptions | Dict[str, Any], *, config_all: dict | None = None) -> dict:
    if not pdf_bytes:
        raise BrowserParseError('O arquivo PDF está vazio.', code='empty_file')
    opts = _as_options(options)
    config_all = _resolve_config_all(config_all, opts)
    runtime_cfg = _runtime_for_browser(config_all, opts)
    context = _build_context(opts)
    ranges = _build_ranges(opts)
    started = time.perf_counter()
    stage_result = parse_budget_stage(pdf_bytes=pdf_bytes, ranges=ranges, config=runtime_cfg, context=context)
    budget_elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    stage_result['_stage_meta'] = {
        'stage': 'budget',
        'duration_ms': budget_elapsed_ms,
        'performance': {
            'pages': max(0, opts.orcamento_fim - opts.orcamento_inicio + 1),
            'range': {'inicio': opts.orcamento_inicio, 'fim': opts.orcamento_fim},
            'preview_time_ms': budget_elapsed_ms,
            'item_refs': len(stage_result.get('item_refs') or []),
            'warnings': len(stage_result.get('avisos') or []),
            'errors': len(stage_result.get('erros') or []),
            'table_structure_changes': len(((stage_result.get('table_structure') or {}).get('applied_changes') or [])),
        },
    }
    return stage_result



def parse_compositions_stage_browser(pdf_bytes: bytes, options: BrowserParseOptions | Dict[str, Any], *, config_all: dict | None = None) -> dict:
    if not pdf_bytes:
        raise BrowserParseError('O arquivo PDF está vazio.', code='empty_file')
    opts = _as_options(options)
    config_all = _resolve_config_all(config_all, opts)
    runtime_cfg = _runtime_for_browser(config_all, opts)
    context = _build_context(opts)
    ranges = _build_ranges(opts)
    started = time.perf_counter()
    stage_result = parse_compositions_stage(pdf_bytes=pdf_bytes, ranges=ranges, config=runtime_cfg, context=context)
    compositions_elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    comp_payload = stage_result.get('composicoes') or {}
    principals = len((comp_payload.get('principais') or {})) if isinstance(comp_payload, dict) else 0
    auxiliares = len((comp_payload.get('auxiliares_globais') or {})) if isinstance(comp_payload, dict) else 0
    semantics = dict(stage_result.get('table_semantics') or {})
    multi_validator = dict(stage_result.get('multi_validator') or {})
    mv_stats = dict(multi_validator.get('stats') or {})
    docling_repair = dict(stage_result.get('docling_assistive_repair') or {})
    debug_signals = {
        'warnings': len(stage_result.get('avisos') or []),
        'errors': len(stage_result.get('erros') or []),
        'principais': principals,
        'auxiliares_globais': auxiliares,
        'semantic_tables': int(semantics.get('matched_tables') or 0),
        'multi_validator_pages': int(mv_stats.get('pages_with_candidates') or 0),
        'multi_validator_lines_refined': int(mv_stats.get('lines_refined') or 0),
        'docling_repair_candidates': int(docling_repair.get('repair_candidates') or 0),
        'docling_repairs_attempted': int(docling_repair.get('repairs_attempted') or 0),
        'docling_repairs_accepted': int(docling_repair.get('repairs_accepted') or 0),
    }
    stage_result['_stage_meta'] = {
        'stage': 'compositions',
        'duration_ms': compositions_elapsed_ms,
        'performance': {
            'pages': max(0, opts.composicoes_fim - opts.composicoes_inicio + 1) if opts.composicoes_inicio and opts.composicoes_fim else 0,
            'range': {'inicio': opts.composicoes_inicio, 'fim': opts.composicoes_fim},
            'warnings': debug_signals['warnings'],
            'errors': debug_signals['errors'],
            'principais': principals,
            'auxiliares_globais': auxiliares,
            'semantic_tables': debug_signals['semantic_tables'],
            'multi_validator_pages': debug_signals['multi_validator_pages'],
            'multi_validator_lines_refined': debug_signals['multi_validator_lines_refined'],
            'docling_repair_candidates': debug_signals['docling_repair_candidates'],
            'docling_repairs_attempted': debug_signals['docling_repairs_attempted'],
            'docling_repairs_accepted': debug_signals['docling_repairs_accepted'],
        },
    }
    return stage_result



def merge_stages_browser(
    budget_stage_payload: Dict[str, Any],
    compositions_stage_payload: Dict[str, Any],
    options: BrowserParseOptions | Dict[str, Any],
    *,
    config_all: dict | None = None,
) -> dict:
    opts = _as_options(options)
    config_all = _resolve_config_all(config_all, opts)
    runtime_cfg = _runtime_for_browser(config_all, opts)
    context = _build_context(opts)
    started = time.perf_counter()
    result = merge_staged_results(budget_stage_payload, compositions_stage_payload, config=runtime_cfg, context=context)
    merge_elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    parser_perf = dict(((result.get('meta') or {}).get('performance') or {}))
    budget_meta = dict((budget_stage_payload or {}).get('_stage_meta') or {})
    comp_meta = dict((compositions_stage_payload or {}).get('_stage_meta') or {})
    total_elapsed_ms = round(float(budget_meta.get('duration_ms', 0.0)) + float(comp_meta.get('duration_ms', 0.0)) + merge_elapsed_ms, 3)
    result.setdefault('meta', {})
    result['meta']['performance'] = {
        **parser_perf,
        'total_parser_ms': total_elapsed_ms,
        'preview_time_ms': float(budget_meta.get('duration_ms', 0.0) or 0.0),
        'final_time_ms': total_elapsed_ms,
        'stages_ms': {
            'budget_stage_ms': budget_meta.get('duration_ms', 0.0),
            'compositions_stage_ms': comp_meta.get('duration_ms', 0.0),
            'merge_stage_ms': merge_elapsed_ms,
        },
        'metrics': {
            'budget': budget_meta.get('performance') or {},
            'compositions': comp_meta.get('performance') or {},
        },
    }
    result = _finalize_result(result, config_all=config_all, runtime_cfg=runtime_cfg, opts=opts, elapsed_ms=total_elapsed_ms, mode='browser')
    return result
