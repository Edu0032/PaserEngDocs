from __future__ import annotations
import asyncio, hashlib, json, time
from typing import Any, Dict
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.browser.docling_seed_pdf import DoclingSeedPdfError, build_docling_seed_pdf_bytes
from app.config.loader import load_parser_config
from app.config.settings import get_settings
from app.core.payload_contract import clean_table_hints_for_docling, payload_usage_report, validate_lovable_payload_contract, split_lovable_document_and_runtime_payload
from app.core.docling_cache import stable_docling_cache_key
from app.config.version import CONTRACT_VERSION, CURRENT_RELEASE, DOCLING_CONTRACT_VERSION, PYODIDE_BUNDLE_VERSION
from app.integrations.docling_clean_adapter import build_clean_docling_payload_from_bundle
from app.integrations.docling_client import DoclingClient, build_extraction_request
from app.profile.docling_profile_calibrator import calibrate_docling_profile
from app.intake.request_models import ParseDocumentRequestModel

async def _read_upload_or_400(upload: UploadFile, *, max_upload_mb: int, allowed_content_types: list[str]) -> bytes:
    if upload.content_type and allowed_content_types and upload.content_type not in allowed_content_types:
        raise HTTPException(status_code=415, detail='Tipo de conteúdo não suportado.')
    data = await upload.read()
    if not data: raise HTTPException(status_code=400, detail='Arquivo PDF vazio.')
    if len(data) > max_upload_mb * 1024 * 1024: raise HTTPException(status_code=413, detail='Arquivo acima do limite configurado.')
    return data

def _parse_form_request(payload: str) -> ParseDocumentRequestModel:
    try: payload_dict = json.loads(payload or '{}')
    except Exception as exc: raise HTTPException(status_code=422, detail=f'payload JSON inválido: {exc}') from exc
    try: return ParseDocumentRequestModel.model_validate(payload_dict)
    except Exception as exc: raise HTTPException(status_code=422, detail=str(exc)) from exc

def _pdf_page_count(pdf_bytes: bytes) -> int:
    try:
        from pypdf import PdfReader; import io
        return len(PdfReader(io.BytesIO(pdf_bytes)).pages)
    except Exception: return 0

def _seed_pdf_local_page(request: ParseDocumentRequestModel, role: str, fallback: int) -> int:
    seed_meta = dict(getattr(request, 'docling_seed_pdf', None) or {})
    if not seed_meta.get('is_seed_pdf'): return int(fallback)
    page_map = {str(k): int(v) for k, v in dict(seed_meta.get('page_map') or {}).items() if str(v).isdigit() or isinstance(v, int)}
    roles = {str(k): str(v) for k, v in dict(seed_meta.get('roles') or {}).items()}
    for local, role_text in roles.items():
        if role in role_text:
            try: return int(local)
            except Exception: pass
    for local, original in page_map.items():
        if int(original) == int(fallback):
            try: return int(local)
            except Exception: pass
    return int(fallback)

def _pick_tables_for_docling(request: ParseDocumentRequestModel) -> Dict[str, Any]:
    # Keep the observed PDF header -> canonical association and first-row samples,
    # but do not forward parser execution rules/regexes to Docling. Those fixed
    # rules live in base_config and are merged only inside the parser runtime.
    return clean_table_hints_for_docling(request.normalized_table_hints())

def _docling_structure_payload(request: ParseDocumentRequestModel) -> Dict[str, Any]:
    tables = _pick_tables_for_docling(request)
    return {
        'version': CURRENT_RELEASE,
        'mode': 'docling_structure_seed',
        'document': {'filename': 'docling-seed-pages.pdf', **dict(request.document or {})},
        'docling_seed_pages': request.docling_seed_pages.model_dump(mode='python'),
        'docling_seed_pdf': dict(getattr(request, 'docling_seed_pdf', {}) or {}),
        'ranges': {k: v.model_dump(mode='python') for k, v in request.ranges.items()},
        'tables': tables,
        'docling_context': {
            'header_footer_profile': request.ai_hints.header_footer_profile.model_dump(mode='python'),
            'docling_guidance': {k: v.model_dump(mode='python') for k, v in (request.ai_hints.docling_guidance or {}).items()},
            'selection_policy': {k: v.model_dump(mode='python') for k, v in (request.ai_hints.selection_policy or {}).items()},
            'page_family_hints': dict(request.ai_hints.page_family_hints or {}),
            'section_map': dict(request.ai_hints.section_map or {}),
        },
        'payload_usage': payload_usage_report(request.model_dump(mode='python'), tables),
    }

def _stable_obj_hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj or {}, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()

def _seed_text_sha256(pdf_bytes: bytes) -> str:
    try:
        import io; from pypdf import PdfReader
        text='\n'.join((p.extract_text() or '') for p in PdfReader(io.BytesIO(pdf_bytes)).pages)
        return hashlib.sha256(text.encode()).hexdigest()
    except Exception: return hashlib.sha256(pdf_bytes).hexdigest()

def _docling_cache_key(pdf_bytes: bytes, request: ParseDocumentRequestModel) -> str:
    payload=_docling_structure_payload(request); seed_meta=dict(getattr(request,'docling_seed_pdf',{}) or {})
    parser_contract = getattr(request, 'parser_contract', {}) or {}
    crop_policy = (parser_contract.get('crop_policy') if isinstance(parser_contract, dict) else {}) or (getattr(request, 'docling_seed_pdf_policy', {}) or {})
    return stable_docling_cache_key(seed_text_sha256=_seed_text_sha256(pdf_bytes), page_map=seed_meta.get('page_map') or {}, roles=seed_meta.get('roles') or {}, tables=payload.get('tables') or {}, crop_policy=crop_policy, parser_contract=parser_contract, docling_context=payload.get('docling_context') or {}, contract_version=CONTRACT_VERSION)

async def _execute_docling_structure_extraction(pdf_bytes: bytes, request: ParseDocumentRequestModel, client: DoclingClient, *, timeout_seconds: int) -> JSONResponse:
    trace_start=time.perf_counter(); seed_meta_initial=dict(getattr(request,'docling_seed_pdf',{}) or {})
    trace={'received_file_name':'docling-seed-pages.pdf' if seed_meta_initial.get('is_seed_pdf') else dict(request.document or {}).get('filename','upload.pdf'),'sent_pdf_kind':'seed_pdf' if seed_meta_initial.get('is_seed_pdf') else 'full_pdf_or_original_upload','received_size_bytes':len(pdf_bytes),'page_count_received':_pdf_page_count(pdf_bytes),'api_mode':'docling_structure_seed','cache_hit':False,'timing':{}}
    t0=time.perf_counter()
    if not seed_meta_initial.get('is_seed_pdf'):
        policy=dict(getattr(request,'docling_seed_pdf_policy',{}) or {})
        if bool(policy.get('send_full_pdf_to_docling',False)):
            raise HTTPException(status_code=422, detail={'error':'full_pdf_not_allowed_for_docling_api','message':'A API Docling v61.0.23 aceita somente mini-PDF seed.'})
        try:
            seed_result=build_docling_seed_pdf_bytes(pdf_bytes, request.model_dump(mode='python'))
            pdf_bytes=seed_result.get('pdf_bytes') or pdf_bytes; req_data=request.model_dump(mode='python'); req_data['docling_seed_pdf']=dict(seed_result.get('docling_seed_pdf') or {}); request=ParseDocumentRequestModel.model_validate(req_data)
            trace.update({'sent_pdf_kind':'seed_pdf','received_file_name':'docling-seed-pages.pdf','seed_reduction_applied_by_api':True,'seed_size_bytes':len(pdf_bytes),'page_count_received':_pdf_page_count(pdf_bytes)})
        except DoclingSeedPdfError as exc: raise HTTPException(status_code=422, detail={'error':exc.code,'message':str(exc),'detail':exc.detail}) from exc
    trace['timing']['seed_prepare_ms']=round((time.perf_counter()-t0)*1000,3)
    if trace.get('page_count_received',0)>3: raise HTTPException(status_code=422, detail={'error':'docling_requires_seed_pdf','message':'A API Docling aceita somente mini-PDF seed com até 3 páginas.','page_count_received':trace.get('page_count_received')})
    cache_key=_docling_cache_key(pdf_bytes, request); cache=getattr(client,'_api_structure_cache',None)
    if cache is None: cache={}; setattr(client,'_api_structure_cache',cache)
    bypass_cache=bool(getattr(request,'bypass_cache',False) or (getattr(request,'parser_contract',{}) or {}).get('bypass_docling_cache') or (getattr(request,'docling_seed_pdf_policy',{}) or {}).get('bypass_cache'))
    if (not bypass_cache) and cache_key in cache:
        cached=json.loads(json.dumps(cache[cache_key])); cached.setdefault('metadata',{}); cached['metadata']['cache']={'hit':True,'bypass':False,'status':'HIT','key':cache_key}; cached['metadata'].setdefault('performance_trace',{}); cached_trace=cached['metadata']['performance_trace']; hit_timing=dict(cached_trace.get('timing') or {}); hit_timing.update({'cache_lookup_ms':round((time.perf_counter()-trace_start)*1000,3),'total_ms':round((time.perf_counter()-trace_start)*1000,3)}); cached_trace.update({**trace,'cache_hit':True,'cache_status':'HIT','timing':hit_timing}); return JSONResponse(cached)
    structure_payload=_docling_structure_payload(request); effective_request=ParseDocumentRequestModel.model_validate({**request.model_dump(mode='python'),**structure_payload})
    t_build=time.perf_counter(); extraction_request=build_extraction_request(budget_header_page=_seed_pdf_local_page(effective_request,'budget_header_page',effective_request.docling_seed_pages.budget_header_page),composition_schema_page=_seed_pdf_local_page(effective_request,'composition_schema_page',effective_request.docling_seed_pages.composition_schema_page),budget_range=effective_request.ranges['budget'].model_dump(mode='python'),compositions_range=effective_request.ranges['compositions'].model_dump(mode='python'),document=dict(effective_request.document or {}),document_profile=effective_request.ai_hints.document_profile,header_footer_profile=effective_request.ai_hints.header_footer_profile.model_dump(mode='python'),table_hints=effective_request.normalized_table_hints(),page_family_hints=effective_request.ai_hints.page_family_hints,section_map=effective_request.ai_hints.section_map,noise_profile=effective_request.ai_hints.noise_profile,anomalies=effective_request.ai_hints.anomalies,non_table_panels=[p.model_dump(mode='python') for p in (effective_request.ai_hints.non_table_panels or [])],docling_guidance={k:v.model_dump(mode='python') for k,v in (effective_request.ai_hints.docling_guidance or {}).items()},selection_policy={k:v.model_dump(mode='python') for k,v in (effective_request.ai_hints.selection_policy or {}).items()},continuation_policy={k:v.model_dump(mode='python') for k,v in (effective_request.ai_hints.continuation_policy or {}).items()},fixed_contract={})
    trace['timing']['payload_build_ms']=round((time.perf_counter()-t_build)*1000,3)
    trace['payload_usage'] = payload_usage_report(effective_request.model_dump(mode='python'), structure_payload.get('tables') or {})
    try:
        t_docling=time.perf_counter(); bundle=await asyncio.wait_for(asyncio.to_thread(client.extract_structures,pdf_bytes,extraction_request), timeout=max(1,int(timeout_seconds or 30))); trace['timing']['docling_extract_ms']=round((time.perf_counter()-t_docling)*1000,3); bundle_timing=dict((bundle.metadata or {}).get('timing') or {}); convert_ms=sum(float(v or 0) for k,v in bundle_timing.items() if str(k).startswith('convert_page_')); runtime_ms=float(bundle_timing.get('runtime_init_ms') or 0.0) or (float(bundle_timing.get('runtime_import_ms') or 0.0)+float(bundle_timing.get('converter_init_ms') or 0.0)); trace['timing']['docling_runtime_init_ms']=round(runtime_ms,3); trace['timing']['docling_document_conversion_ms']=round(float(bundle_timing.get('document_conversion_ms') or 0.0) or convert_ms,3); trace['timing']['docling_table_extraction_ms']=round(float(bundle_timing.get('table_extraction_ms') or 0.0) or max(float(trace['timing'].get('docling_extract_ms') or 0.0)-runtime_ms,0.0),3); trace['timing']['docling_bundle_timing']=bundle_timing
    except TimeoutError as exc: raise HTTPException(status_code=504, detail={'error':'docling_timeout','message':f'Docling excedeu o timeout configurado de {timeout_seconds}s.','ocr_enabled':False,'performance_trace':trace,'payload_usage':payload_usage_report(effective_request.model_dump(mode='python'), structure_payload.get('tables') or {}),'quality':{'missing_columns':[],'merged_columns_suspected':[],'low_confidence_columns':[]}}) from exc
    except RuntimeError as exc: raise HTTPException(status_code=502, detail={'error':'docling_embedded_failed','message':str(exc),'ocr_enabled':False,'performance_trace':trace,'payload_usage':payload_usage_report(effective_request.model_dump(mode='python'), structure_payload.get('tables') or {}),'quality':{'missing_columns':[],'merged_columns_suspected':[],'low_confidence_columns':[]}}) from exc
    t_adapter=time.perf_counter(); clean_payload=build_clean_docling_payload_from_bundle(bundle, source_payload=effective_request.model_dump(mode='python')); trace['timing']['adapter_ms']=round((time.perf_counter()-t_adapter)*1000,3)
    t_profile=time.perf_counter()
    calibrated_profile = calibrate_docling_profile(clean_payload.get('tables') or {}, document_learning_profile=(effective_request.ai_hints.document_profile if isinstance(effective_request.ai_hints.document_profile, dict) else {}))
    trace['timing']['profile_calibration_ms']=round((time.perf_counter()-t_profile)*1000,3)
    trace['timing']['total_ms']=round((time.perf_counter()-trace_start)*1000,3)
    cache_status='BYPASS' if bypass_cache else 'MISS'
    trace['cache_status']=cache_status; trace['cache_hit']=False
    usage_report = payload_usage_report(effective_request.model_dump(mode='python'), structure_payload.get('tables') or {})
    profile_quality = {
        'missing_columns': [],
        'merged_columns_suspected': [],
        'low_confidence_columns': [c for t in (calibrated_profile.get('tables') or {}).values() for c in (t.get('low_confidence_columns') or [])],
        'calibrated_profile_ready': bool((calibrated_profile.get('summary') or {}).get('columns')),
        'pymupdf_adjusted_columns': (calibrated_profile.get('summary') or {}).get('pymupdf_adjusted_columns', 0),
    }
    clean_payload.setdefault('metadata',{}); clean_payload['metadata'].update({'client_runtime':client.runtime_summary(),'timing':dict((bundle.metadata or {}).get('timing') or {}),'docling_request':structure_payload,'docling_executed':True,'ocr_enabled':False,'parser_version':CURRENT_RELEASE,'docling_seed_pdf':dict(getattr(effective_request,'docling_seed_pdf',{}) or {}),'api_mode':'docling_structure_seed','normalization_owned_by':'browser_local_pyodide','cache':{'hit':False,'bypass':bypass_cache,'status':cache_status,'key':cache_key},'performance_trace':trace,'payload_usage':usage_report,'quality':profile_quality,'calibrated_document_profile': calibrated_profile})
    clean_payload['calibrated_document_profile'] = calibrated_profile
    if not bypass_cache: cache[cache_key]=json.loads(json.dumps(clean_payload))
    return JSONResponse(clean_payload)

def create_app() -> FastAPI:
    config_all = load_parser_config()
    settings = get_settings(config_all)
    api_cfg = dict(config_all.get('api') or {})
    project_cfg = dict(config_all.get('project') or {})
    current_release = str(project_cfg.get('current_release') or CURRENT_RELEASE)
    app = FastAPI(
        title=str(api_cfg.get('title') or 'PDF Docling Structure API'),
        version=current_release,
        docs_url='/docs' if settings.docs_enabled else None,
        redoc_url='/redoc' if settings.docs_enabled else None,
        openapi_url='/openapi.json' if settings.docs_enabled else None,
    )
    app.state.config_all = config_all
    app.state.settings = settings
    app.state.docling_client = DoclingClient.from_project_config(config_all)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_allow_origins),
        allow_methods=list(settings.cors_allow_methods),
        allow_headers=list(settings.cors_allow_headers),
        allow_credentials=bool(settings.cors_allow_credentials),
    )

    async def require_api_key(request: Request) -> None:
        expected = str(settings.api_key or '').strip()
        if not expected:
            return
        received = str(request.headers.get(settings.api_key_header_name, '') or '').strip()
        if received != expected:
            raise HTTPException(status_code=401, detail='API key inválida ou ausente.')

    protected = [Depends(require_api_key)]

    @app.get('/')
    def root() -> Dict[str, Any]:
        return {
            'status': 'ok',
            'service': 'api_pdf_docling',
            'version': current_release,
            'endpoint': '/docling/extract-table-structure',
            'mode': 'seed_pdf_only',
            'normalizer': 'local_pyodide_in_browser',
            'payload_contract': 'doc_variable_context_only',
        }

    @app.get('/health')
    def health() -> Dict[str, Any]:
        return {'status': 'ok', 'service': 'api_pdf_docling', 'version': current_release}

    @app.get('/version')
    def version() -> Dict[str, Any]:
        client: DoclingClient = app.state.docling_client
        return {
            'current_release': current_release,
            'contract_version': CONTRACT_VERSION,
            'pyodide_bundle_version': PYODIDE_BUNDLE_VERSION,
            'docling_contract_version': DOCLING_CONTRACT_VERSION,
            'config_schema_version': str(config_all.get('_schema_version') or current_release),
            'docling': dict(config_all.get('docling') or {}),
            'docling_runtime': client.runtime_summary(),
            'security': {
                'environment': settings.environment,
                'docs_enabled': settings.docs_enabled,
                'api_key_required': bool(settings.api_key),
                'cors_allow_origins': list(settings.cors_allow_origins),
            },
        }

    @app.get('/docling/runtime', dependencies=protected)
    def docling_runtime() -> Dict[str, Any]:
        return app.state.docling_client.runtime_summary()

    @app.get('/admin/cache/stats', dependencies=protected)
    def cache_stats() -> Dict[str, Any]:
        cache = getattr(app.state.docling_client, '_api_structure_cache', {}) or {}
        return {'status': 'ok', 'entries': len(cache), 'keys': list(cache.keys())[:20]}

    @app.post('/admin/cache/clear', dependencies=protected)
    def cache_clear() -> Dict[str, Any]:
        setattr(app.state.docling_client, '_api_structure_cache', {})
        return {'status': 'ok', 'cleared': True}

    @app.post('/docling/validate-payload', dependencies=protected)
    async def docling_validate_payload(request: Request) -> Dict[str, Any]:
        try:
            payload = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f'payload JSON inválido: {exc}') from exc
        validation = validate_lovable_payload_contract(payload if isinstance(payload, dict) else {})
        if isinstance(payload, dict):
            validation['payload_split'] = split_lovable_document_and_runtime_payload(payload)
            try:
                parsed = ParseDocumentRequestModel.model_validate(payload)
                validation['normalized_docling_payload'] = _docling_structure_payload(parsed)
            except Exception as exc:
                validation.setdefault('warnings', []).append({'code': 'pydantic_validation_warning', 'message': str(exc)})
        return {'status': 'ok' if validation.get('ok') else 'invalid', 'version': current_release, **validation}

    @app.post('/docling/extract-table-structure', dependencies=protected)
    async def docling_extract_table_structure(file: UploadFile = File(...), payload: str = Form(...)) -> JSONResponse:
        pdf_bytes = await _read_upload_or_400(file, max_upload_mb=settings.max_upload_mb, allowed_content_types=settings.trusted_pdf_content_types)
        return await _execute_docling_structure_extraction(pdf_bytes, _parse_form_request(payload), app.state.docling_client, timeout_seconds=settings.docling_timeout_seconds)

    return app
