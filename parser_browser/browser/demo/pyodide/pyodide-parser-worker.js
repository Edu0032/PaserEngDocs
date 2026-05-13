/* eslint-disable no-restricted-globals */
let pyodide = null;
let manifest = null;
let parserModule = null;
let initPromise = null;
let workerState = 'idle';
let activeParsePath = null;
let normalizerCapabilities = null;

const RELEASE_VERSION = 'v61.0.35-candidate-profile-consensus-engine';
const DEFAULT_DOCLING_TIMEOUT_MS = 120000;
const DEFAULT_NORMALIZER_TIMEOUT_MS = 90000;

function setState(state, detail = {}) {
  workerState = state;
  self.postMessage({ type: 'status', stage: state, state, ...detail });
}

function buildWorkerError(code, message, detail = null, stack = null) {
  return { code, message, detail, stack };
}

function appendQueryParam(url, key, value) {
  if (!value) return url;
  const joiner = String(url).includes('?') ? '&' : '?';
  return `${url}${joiner}${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`;
}

async function loadManifest(manifestUrl, options = {}) {
  setState('loading-manifest', { manifestUrl });
  const fetchOptions = options.debugNoCache ? { cache: 'no-store' } : {};
  const response = await fetch(manifestUrl, fetchOptions);
  if (!response.ok) {
    throw buildWorkerError('MANIFEST_LOAD_FAILED', `Falha ao carregar manifest do parser: ${response.status}`, { manifestUrl, status: response.status });
  }
  return response.json();
}

async function loadSourceArchive(sourceArchiveUrl, options = {}) {
  const url = options.debugNoCache ? sourceArchiveUrl : appendQueryParam(sourceArchiveUrl, 'sha', manifest?.sourceZipSha256 || manifest?.contractVersion || RELEASE_VERSION);
  setState('loading-parser-source', { sourceArchiveUrl: url });
  const response = await fetch(url, options.debugNoCache ? { cache: 'no-store' } : { cache: 'force-cache' });
  if (!response.ok) {
    throw buildWorkerError('PARSER_SOURCE_LOAD_FAILED', `Falha ao carregar código Python do parser: ${response.status}`, { sourceArchiveUrl: url, status: response.status });
  }
  return response.arrayBuffer();
}

function validateBaseOptions(options) {
  if (!options || typeof options !== 'object') {
    throw buildWorkerError('INVALID_OPTIONS', 'Campo options ausente ou inválido.');
  }
  for (const field of ['orcamento_inicio', 'orcamento_fim', 'composicoes_inicio', 'composicoes_fim']) {
    if (!(field in options)) {
      throw buildWorkerError('MISSING_REQUIRED_OPTIONS', 'Payload options incompleto.', { missingField: field });
    }
  }
}

function normalizeLovablePayloadToOptions(initialPayload = {}, fileMeta = {}) {
  const p = initialPayload && typeof initialPayload === 'object' ? initialPayload : {};
  const ranges = p.ranges || {};
  const budget = ranges.budget || ranges.orcamento || {};
  const comps = ranges.compositions || ranges.composicoes || ranges.composition || {};
  const seed = p.docling_seed_pages || p.seed_pages || {};
  const runtime = p.runtime || {};
  const performance = p.performance || {};
  const out = {
    base_id: p.base_id || 'misto',
    performance_profile: p.performance_profile || runtime.profile || performance.profile || 'browser_robust',
    orcamento_inicio: Number(p.orcamento_inicio || budget.start || 0),
    orcamento_fim: Number(p.orcamento_fim || budget.end || 0),
    composicoes_inicio: Number(p.composicoes_inicio || comps.start || 0),
    composicoes_fim: Number(p.composicoes_fim || comps.end || 0),
    filename: p.filename || p.document?.filename || fileMeta.filename || 'upload.pdf',
    content_type: p.content_type || fileMeta.contentType || 'application/pdf',
    obra_nome: p.obra_nome || p.document?.title || undefined,
    metadata_extraida_ia: p.metadata_extraida_ia || {},
    document_profile: p.document_profile || p.ai_hints?.document_profile || {},
    ai_hints: p.ai_hints || {},
    docling_seed_pages: {
      budget_header_page: Number(seed.budget_header_page || seed.budget || seed.orcamento || 0),
      composition_schema_page: Number(seed.composition_schema_page || seed.composition || seed.compositions || seed.composicoes || 0),
    },
    structured_tables: p.structured_tables || p.docling_clean_payload || {},
    strict_validation: !!(p.strict_validation || runtime.strict_validation),
    header_profile_enabled: p.header_profile_enabled ?? true,
    noise_cleanup_mode: p.noise_cleanup_mode || 'contextual',
    table_structure_enabled: p.table_structure_enabled ?? true,
    table_structure_strategy: p.table_structure_strategy || 'hybrid',
    output_options: p.output_options || {},
    parser_contract: p.parser_contract || {},
    tables: p.tables || {},
    fixed_contract: p.fixed_contract || {},
    runtime,
    docling_clean_payload: p.docling_clean_payload || {},
    normalizer_clean_payload: p.normalizer_clean_payload || {},
    normalizer_report: p.normalizer_report || {},
    geometry_evidence: p.geometry_evidence || {},
    docling_seed_pdf: p.docling_seed_pdf || {},
  };
  if (!out.orcamento_inicio || !out.orcamento_fim || !out.composicoes_inicio || !out.composicoes_fim) {
    throw buildWorkerError('MISSING_REQUIRED_RANGES', 'Payload inicial não contém ranges válidos para orçamento e composições.', { ranges });
  }
  return out;
}

function normalizeLegacyOrLovableOptions(options, fileMeta = {}) {
  if (options && (options.ranges || options.tables || options.ai_hints)) {
    return normalizeLovablePayloadToOptions(options, fileMeta);
  }
  return options || {};
}

function validateParsePayload(payload) {
  if (!payload || typeof payload !== 'object') {
    throw buildWorkerError('INVALID_PAYLOAD', 'Payload de parse ausente ou inválido.');
  }
  const { buffer, options } = payload;
  if (!buffer || !(buffer instanceof ArrayBuffer)) {
    throw buildWorkerError('PDF_NOT_PROVIDED', 'Nenhum PDF foi enviado ao worker.', { receivedType: buffer?.constructor?.name || typeof buffer });
  }
  const normalized = normalizeLegacyOrLovableOptions(options || {}, { filename: payload.filename || options?.filename || 'upload.pdf', contentType: payload.contentType || options?.content_type || 'application/pdf' });
  validateBaseOptions(normalized);
}

function resolveDoclingEndpoint(payload = {}, initialPayload = {}) {
  const endpoint = payload.doclingEndpoint || initialPayload.docling_api_url || initialPayload.doclingEndpoint || '';
  const production = !!(payload.production || initialPayload.production || initialPayload.runtime?.environment === 'production' || initialPayload.api_mode === 'production');
  const allowRelative = !!(payload.allowRelativeDoclingEndpoint || initialPayload.allow_relative_docling_endpoint);
  if (endpoint) {
    if (production && !/^https?:\/\//i.test(endpoint)) {
      throw buildWorkerError('DOCLING_ENDPOINT_REQUIRED', 'docling_api_url precisa ser uma URL absoluta em produção.', { endpoint });
    }
    return endpoint;
  }
  if (production || !allowRelative) {
    throw buildWorkerError('DOCLING_ENDPOINT_REQUIRED', 'docling_api_url é obrigatório para executar o fluxo com API Docling.');
  }
  return '/docling/extract-table-structure';
}

function resolveNormalizerMode(payload = {}, initialPayload = {}) {
  const raw = payload.normalizerMode || payload.normalizer_mode || initialPayload.normalizerMode || initialPayload.normalizer_mode || initialPayload.runtime?.normalizer_mode || '';
  const mode = String(raw || '').trim().toLowerCase();
  if (['disabled', 'off', 'none', 'false'].includes(mode)) return 'disabled';
  // v61.0.23: standalone Normalizer API was removed.  The only normalizer
  // execution path in the Lovable bundle is local PyMuPDF inside Pyodide.
  return 'local_pyodide';
}

function shouldUseNormalizerApi(payload = {}, initialPayload = {}) {
  return false;
}

function resolveNormalizerEndpoint(payload = {}, initialPayload = {}) {
  // v61.0.23: Normalizer API endpoints were removed from the browser bundle.
  // Refinement and recovery are local Pyodide/PyMuPDF operations.
  return '';
}


function pickTableForDocling(raw = {}) {
  const observed = Array.isArray(raw.observed_headers) ? raw.observed_headers : [];
  const columns = Array.isArray(raw.columns) ? raw.columns : [];
  const firstRows = Array.isArray(raw.first_row_samples) ? raw.first_row_samples : [];

  const sampleFor = (h, idx) => {
    const canonical = String(h.canonical || h.canonical_name || '').trim();
    const header = String(h.text || h.header_text || h.header || '').trim();
    const direct = h.sample_text || h.content_text || h.first_row_text || h.first_content_text || '';
    if (direct) return direct;
    const byIndex = firstRows[idx];
    if (typeof byIndex === 'string') return byIndex;
    if (byIndex && typeof byIndex === 'object') return byIndex.sample_text || byIndex.content_text || byIndex.first_row_text || byIndex.value || '';
    const match = firstRows.find((r) => r && typeof r === 'object' && (
      String(r.canonical || r.canonical_name || '').trim() === canonical ||
      String(r.header || r.header_text || '').trim() === header
    ));
    return match ? (match.sample_text || match.content_text || match.first_row_text || match.value || '') : '';
  };

  const toHeaderHint = (h, idx) => {
    const sample = sampleFor(h, idx);
    return {
      text: h.text || h.header_text || h.header || '',
      header_text: h.header_text || h.text || h.header || '',
      canonical: h.canonical || h.canonical_name || '',
      canonical_name: h.canonical_name || h.canonical || '',
      type: h.type || 'column',
      role: h.role || undefined,
      group: h.group || undefined,
      ignore_in_domain: !!h.ignore_in_domain,
      sample_text: sample,
      content_text: sample,
      first_row_text: sample,
    };
  };

  const observedHeaders = (observed.length ? observed : columns).map(toHeaderHint);
  return {
    header_rows_observed: raw.header_rows_observed,
    multiline_header: raw.multiline_header,
    physical_column_count_expected: raw.physical_column_count_expected,
    logical_column_count_expected: raw.logical_column_count_expected,
    domain_column_count_expected: raw.domain_column_count_expected,
    table_parent_header: raw.table_parent_header || {},
    non_column_context: raw.non_column_context || [],
    observed_headers: observedHeaders,
    columns: columns.map(toHeaderHint),
    first_row_samples: firstRows,
    header_groups: raw.header_groups || raw.grouped_headers || [],
    header_noise_terms: raw.header_noise_terms || [],
    control_column: raw.control_column || {},
  };
}

function buildDoclingPayloadForApi(initialPayload = {}, seedMeta = {}) {
  const p = initialPayload || {};
  const ranges = p.ranges || {};
  const seed = p.docling_seed_pages || p.seed_pages || {};
  const tables = p.tables || p.ai_hints?.table_hints || {};
  const out = {
    version: RELEASE_VERSION,
    mode: 'docling_structure_seed',
    base_id: p.base_id || 'misto',
    document: { ...(p.document || {}), filename: 'docling-seed-pages.pdf' },
    ranges,
    docling_seed_pages: seed,
    docling_seed_pdf: seedMeta || {},
    docling_seed_pdf_policy: {
      enabled: true,
      extract_in_pyodide: true,
      send_full_pdf_to_docling: false,
      allow_full_pdf_fallback: false,
      preserve_full_page: true,
      deduplicate_pages: true,
      ...(p.docling_seed_pdf_policy || {}),
    },
    tables: {
      budget: pickTableForDocling(tables.budget || {}),
      composition: pickTableForDocling(tables.composition || tables.compositions || {}),
    },
    // Fixed parser/runtime rules are intentionally not sent here.
    // The Docling API/base_config owns its stable execution defaults; this
    // browser payload carries only document-specific evidence and table hints.
    ai_hints: {
      header_footer_profile: p.ai_hints?.header_footer_profile || {},
      docling_guidance: p.ai_hints?.docling_guidance || {},
      selection_policy: p.ai_hints?.selection_policy || {},
      page_family_hints: p.ai_hints?.page_family_hints || {},
      section_map: p.ai_hints?.section_map || {},
    },
    parser_contract: p.docling_parser_contract || {},
    // API URL/key/timeout are transport settings handled by the worker and
    // headers.  They are intentionally not included in the JSON body sent to
    // Docling, keeping the payload focused on document evidence.
    bypass_cache: !!p.bypass_cache,
    clear_docling_cache_before_run: !!p.clear_docling_cache_before_run,
  };
  return out;
}

function mergeDoclingForParser(doclingResponse = {}, seedMeta = {}) {
  const out = (doclingResponse && typeof doclingResponse === 'object') ? { ...doclingResponse } : {};
  out.metadata = { ...(out.metadata || {}), docling_seed_pdf: seedMeta || {} };
  out.docling_seed_pdf = seedMeta || {};
  return out;
}

function buildNormalizerPayloadForApi(initialPayload = {}, seedMeta = {}, doclingResponse = {}) {
  const p = initialPayload || {};
  return {
    version: RELEASE_VERSION,
    mode: 'normalizer_refine_table_structure',
    normalizer_policy: { exclusive_refinement: true, local_seed_validator_removed: true },
    docling_seed_pdf: seedMeta || {},
    tables: p.tables || p.ai_hints?.table_hints || {},
    docling_clean_payload: doclingResponse || {},
    parser_contract: {
      effective_bounds_rule: 'x0_to_next_physical_x0',
      preserve_code_display: true,
      process_only_anomalies: true,
      lock_good_columns: true,
      ...(p.parser_contract || {}),
    },
  };
}

async function callNormalizerApiFromWorker(buffer, initialPayload, endpoint, fileMeta = {}) {
  setState('normalizer-api-disabled', { endpoint, sizeBytes: buffer?.byteLength || 0, sentPdfKind: 'seed_pdf', filename: fileMeta.filename || 'docling-seed-pages.pdf' });
  const fd = new FormData();
  const blob = new Blob([buffer], { type: 'application/pdf' });
  fd.append('file', blob, fileMeta.filename || 'docling-seed-pages.pdf');
  fd.append('payload', JSON.stringify(initialPayload || {}));
  const headers = {};
  const apiKey = fileMeta.normalizerApiKey || initialPayload?.normalizer_api_key || '';
  const apiKeyHeader = fileMeta.normalizerApiKeyHeader || initialPayload?.normalizer_api_key_header || 'x-api-key';
  if (apiKey) headers[apiKeyHeader] = apiKey;
  const controller = new AbortController();
  const timeoutMs = Number(fileMeta.normalizerTimeoutMs || initialPayload?.normalizer_timeout_ms || DEFAULT_NORMALIZER_TIMEOUT_MS);
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const started = Date.now();
  try {
    const response = await fetch(endpoint, { method: 'POST', body: fd, headers, signal: controller.signal });
    const text = await response.text();
    let data = null;
    try { data = JSON.parse(text); } catch (_e) { data = { raw: text }; }
    if (!response.ok) {
      throw buildWorkerError('NORMALIZER_API_HTTP_ERROR', `API Normalizer retornou HTTP ${response.status}.`, { endpoint, status: response.status, response: data });
    }
    const report = data?.metadata?.normalizer_report || {};
    setState('normalizer-response-received', {
      elapsedMs: Date.now() - started,
      tableCount: Object.keys(data?.tables || {}).length,
      refinedColumns: Object.values(report.tables || {}).flatMap((t) => t.refined_columns || []),
      unresolvedColumns: Object.values(report.tables || {}).flatMap((t) => t.unresolved_columns || []),
    });
    return data;
  } catch (error) {
    if (error?.name === 'AbortError') {
      throw buildWorkerError('NORMALIZER_API_TIMEOUT', `API Normalizer excedeu ${timeoutMs}ms.`, { endpoint, timeoutMs });
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

async function callNormalizerLocalRefinePyodide(seedPath, normalizerPayload, fileMeta = {}) {
  setState('normalizer-local-refine-started', { filename: fileMeta.filename || 'docling-seed-pages.pdf', path: seedPath });
  const started = Date.now();
  const jsonString = await callParserFunction('refine_table_structure_local_file_json', seedPath, JSON.stringify(normalizerPayload || {}));
  const data = JSON.parse(jsonString || '{}');
  if (data && (data.status === 'error' || data.ok === false)) {
    const err = data.error || {};
    throw buildWorkerError(err.code || 'NORMALIZER_LOCAL_REFINE_FAILED', err.message || 'Normalizer local falhou.', err.detail || data);
  }
  const report = data?.metadata?.normalizer_report || {};
  setState('normalizer-local-refine-finished', {
    elapsedMs: Date.now() - started,
    tableCount: Object.keys(data?.tables || {}).length,
    refinedColumns: Object.values(report.tables || {}).flatMap((t) => t.refined_columns || []),
    unresolvedColumns: Object.values(report.tables || {}).flatMap((t) => t.unresolved_columns || []),
    mode: data?.metadata?.normalizer_mode || 'local_pymupdf_pyodide',
  });
  return data;
}

async function refineWithNormalizerOrFallback(seedBuffer, seedPath, seedMeta, initialPayload, doclingForParser, endpoint, fileMeta = {}, payload = {}) {
  const enabled = initialPayload?.fixed_contract?.geometry_normalizer?.enabled !== false && initialPayload?.normalizer_enabled !== false;
  if (!enabled) return { payload: doclingForParser, used: false, error: null, mode: 'disabled' };
  const normalizerPayload = buildNormalizerPayloadForApi(initialPayload, seedMeta, doclingForParser);
  const mode = resolveNormalizerMode(payload, initialPayload);
  if (mode === 'disabled') return { payload: doclingForParser, used: false, error: null, mode };

  if (mode !== 'api') {
    try {
      const normalized = await callNormalizerLocalRefinePyodide(seedPath, normalizerPayload, { ...fileMeta, filename: 'docling-seed-pages.pdf' });
      return { payload: mergeDoclingForParser(normalized, seedMeta), used: true, error: null, mode: 'local_pyodide' };
    } catch (error) {
      setState('normalizer-local-fallback-to-docling', { code: error?.code || 'normalizer_local_failed', message: error?.message || String(error) });
      return { payload: doclingForParser, used: false, error, mode: 'local_pyodide' };
    }
  }

  setState('normalizer-api-removed', { reason: 'v61.0.23_local_pyodide_only' });
  return { payload: doclingForParser, used: false, error: null, mode: 'api_removed' };
}


function resolveNormalizerRecoveryEndpoint(payload = {}, initialPayload = {}) {
  // v61.0.23: no external recovery endpoint.
  return '';
}



function isSicroBank(value = '') {
  const v = String(value || '').trim().toUpperCase().replace(/\s+/g, '');
  return v === 'SICRO' || v === 'SICRO2' || v === 'SICRO3';
}

function isPossiblyTruncatedDescription(value = '') {
  const text = String(value || '').trim();
  if (!text) return false;
  const normalized = text.toUpperCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
  const tokens = normalized.split(/\s+/).filter(Boolean);
  const last = tokens[tokens.length - 1] || '';
  return ['DE','DA','DO','DAS','DOS','PARA','COM','E','EM','A','O'].includes(last);
}

function isProfileRecoveryCandidate(value = '') {
  const text = String(value || '').trim();
  if (!text) return true;
  if (isPossiblyTruncatedDescription(text)) return true;
  if (text.length < 42 && !/\bAF_\d{2}\/\d{4}\b/i.test(text)) return true;
  // Do not hardcode profession/service words here. Fragment detection is driven
  // by learned profile + current length/truncation + evidence graph.
  return false;
}

function normalizeCodeBank(codigo = '', banco = '') {
  const c = String(codigo || '').trim().toUpperCase().replace(/\s+/g, '');
  let b = String(banco || '').trim().toUpperCase().replace(/\s+/g, '');
  if (['SICRO','SICRO2','SICRO3','DNIT'].includes(b)) b = 'SICRO';
  if (['CAIXA'].includes(b)) b = 'SINAPI';
  if (['PROPRIO'].includes(b)) b = 'PRÓPRIO';
  return c && b ? `${c}|${b}` : '';
}

function addDescriptionRegistryEntry(registry, codigo, banco, descricao, source = '') {
  const key = normalizeCodeBank(codigo, banco);
  const desc = String(descricao || '').trim().replace(/\s+/g, ' ');
  if (!key || !desc || desc.length < 3) return;
  if (/Custo Total das Atividades|Valor com BDI|Valor do BDI|=>/i.test(desc)) return;
  const current = registry[key];
  const score = Math.min(desc.length / 140, 1) + Math.min(desc.split(/\s+/).length / 20, 1);
  if (!current || score > Number(current.score || 0) || desc.length > String(current.descricao || '').length) {
    registry[key] = { descricao: desc, score, source, confirmed: score >= 1.1 };
  }
}

function buildDescriptionRegistryFromFinal(finalResult = {}) {
  const registry = {};
  const graphEntries = finalResult?.meta?.performance?.evidence_graph?.entries || {};
  for (const [key, ent] of Object.entries(graphEntries || {})) {
    const desc = String(ent?.best_description || '').trim();
    if (desc && ent?.confirmed) {
      registry[key] = { descricao: desc, score: Number(ent.best_score || 2), source: 'evidence_graph', confirmed: true, locked_negative_evidence: !!ent.locked_negative_evidence };
    }
  }
  const visitRow = (row, source) => {
    if (!row || typeof row !== 'object') return;
    addDescriptionRegistryEntry(registry, row.codigo, row.banco || row.fonte || row.banco_coluna, row.descricao || row.especificacao, source);
  };
  const visitBlocks = (blocks, sourcePrefix) => {
    for (const [key, block] of Object.entries(blocks || {})) {
      if (!block || typeof block !== 'object') continue;
      visitRow(block.principal, `${sourcePrefix}.${key}.principal`);
      for (const group of ['composicoes_auxiliares', 'insumos', 'materiais', 'mao_obra', 'equipamentos', 'auxiliares']) {
        (Array.isArray(block[group]) ? block[group] : []).forEach((row, idx) => visitRow(row, `${sourcePrefix}.${key}.${group}.${idx}`));
      }
    }
  };
  const comp = finalResult?.composicoes || {};
  visitBlocks(comp.principais || {}, 'composicoes.principais');
  visitBlocks(comp.auxiliares_globais || {}, 'composicoes.auxiliares_globais');
  visitBlocks(comp?.sinapi_like?.principais || {}, 'composicoes.sinapi_like.principais');
  visitBlocks(comp?.sinapi_like?.auxiliares_globais || {}, 'composicoes.sinapi_like.auxiliares_globais');
  const walkBudget = (nodes = []) => {
    for (const node of nodes || []) {
      if (String(node?.tipo || '').toLowerCase() === 'item') addDescriptionRegistryEntry(registry, node.codigo, node.fonte, node.especificacao, `orcamento.${node.item || ''}`);
      if (Array.isArray(node?.filhos)) walkBudget(node.filhos);
    }
  };
  walkBudget(finalResult?.orcamento_sintetico?.itens_raiz || []);
  return registry;
}

function makeRecoveryTarget(base, path, row, issue, page, extra = {}) {
  const codigo = String(row?.codigo || '').trim();
  if (!codigo) return null;
  const field = String(extra.field || extra.description_field || 'descricao').trim() || 'descricao';
  return {
    target_id: `${path.join('.')}::${field}`,
    path: [...path, field],
    field,
    issue,
    current_value: String(row?.[field] || row?.descricao || row?.especificacao || ''),
    codigo,
    banco: String(row?.banco || row?.fonte || row?.banco_coluna || base?.principal?.banco || '').trim(),
    page: Number(page || base?.pagina_inicio || 0),
    ...extra,
  };
}

function addTargetsFromSelectiveReparsePlan(targets, finalResult = {}) {
  const plan = finalResult?.meta?.performance?.document_learning_profile?.selective_reparse_plan || {};
  const add = (t, family) => {
    if (!t || typeof t !== 'object') return;
    const path = Array.isArray(t.path) ? t.path : [];
    const codigo = String(t.codigo || t.code || '').trim();
    if (!codigo || !path.length) return;
    const field = family === 'budget' ? 'especificacao' : 'descricao';
    targets.push({
      target_id: `${path.join('.')}::${field}`,
      path: [...path, field],
      field,
      issue: t.issue || t.reason || (family === 'budget' ? 'selective_reparse_budget_profile_target' : 'selective_reparse_composition_profile_target'),
      current_value: String(t.current_value || t.descricao || t.especificacao || ''),
      codigo,
      banco: String(t.banco || t.fonte || '').trim(),
      page: Number(t.page || t.pagina || t.pagina_inicio || 0),
      family: family === 'budget' ? 'budget' : 'sinapi_like',
      table_family: family === 'budget' ? 'budget' : 'composition',
      row_group: family === 'budget' ? 'budget_item' : (t.row_group || 'principal'),
      collection: family === 'budget' ? 'orcamento_sintetico' : (t.collection || 'principais'),
      profile_target: true,
    });
  };
  for (const t of (plan.budget_targets || [])) add(t, 'budget');
  for (const t of (plan.composition_targets || [])) add(t, 'composition');

}

function addTargetsFromSelectiveFieldExecutor(targets, finalResult = {}) {
  const report = finalResult?.meta?.performance?.selective_field_reparse_executor || {};
  const executorTargets = Array.isArray(report.targets) ? report.targets : [];
  for (const t of executorTargets) {
    if (!t || typeof t !== 'object') continue;
    const path = Array.isArray(t.path) ? t.path : [];
    const codigo = String(t.codigo || '').trim();
    if (!codigo || !path.length) continue;
    const family = String(t.family || '').toLowerCase() === 'budget' ? 'budget' : 'sinapi_like';
    const field = String(t.field || (family === 'budget' ? 'especificacao' : 'descricao')).trim();
    const rowPath = path[path.length - 1] === field ? path.slice(0, -1) : path;
    targets.push({
      target_id: `${rowPath.join('.')}::${field}`,
      path: [...rowPath, field],
      field,
      issue: t.issue || t.reason || 'selective_field_reparse_executor_target',
      current_value: String(t.current_value || ''),
      codigo,
      banco: String(t.banco || t.fonte || '').trim(),
      page: Number(t.page || t.pagina || t.pagina_inicio || 0),
      family,
      table_family: family === 'budget' ? 'budget' : 'composition',
      item: t.item || '',
      row_group: family === 'budget' ? 'budget_item' : (t.row_group || 'principal'),
      collection: family === 'budget' ? 'orcamento_sintetico' : (t.collection || 'principais'),
      neighbor_context: t.neighbor_context || (family === 'budget' ? (buildBudgetNeighborContextIndex(finalResult)[rowPath.join('.')] || {}) : {}),
      selective_field_executor_target: true,
    });
  }
}


function flattenBudgetRowsForOwnership(finalResult = {}) {
  const registry = buildDescriptionRegistryFromFinal(finalResult || {});
  const rows = [];
  const addConfirmed = (row) => {
    const key = normalizeCodeBank(row?.codigo, row?.fonte || row?.banco);
    const reg = key ? registry[key] : null;
    return {
      codigo: String(row?.codigo || '').trim(),
      banco: String(row?.fonte || row?.banco || '').trim(),
      item: String(row?.item || '').trim(),
      descricao: String(row?.especificacao || row?.descricao || '').trim().replace(/\s+/g, ' '),
      confirmed_description: String(reg?.descricao || '').trim().replace(/\s+/g, ' '),
    };
  };
  const walk = (nodes = [], pathPrefix = ['orcamento_sintetico', 'itens_raiz']) => {
    (nodes || []).forEach((node, idx) => {
      if (!node || typeof node !== 'object') return;
      const path = [...pathPrefix, idx];
      if (String(node?.tipo || '').toLowerCase() === 'item' || node?.codigo) {
        rows.push({ path, pathKey: path.join('.'), row: node, info: addConfirmed(node) });
      }
      if (Array.isArray(node?.filhos)) walk(node.filhos, [...path, 'filhos']);
    });
  };
  walk(finalResult?.orcamento_sintetico?.itens_raiz || []);
  return rows;
}

function buildBudgetNeighborContextIndex(finalResult = {}) {
  const rows = flattenBudgetRowsForOwnership(finalResult || {});
  const index = {};
  rows.forEach((entry, idx) => {
    const ctx = {};
    if (idx > 0) ctx.prev = rows[idx - 1].info;
    if (idx + 1 < rows.length) ctx.next = rows[idx + 1].info;
    index[entry.pathKey] = ctx;
  });
  return index;
}

function collectTargetedRecoveryTargets(finalResult = {}) {
  const comp = finalResult?.composicoes || {};
  const targets = [];
  const budgetNeighborContextIndex = buildBudgetNeighborContextIndex(finalResult);
  const rowGroups = ['composicoes_auxiliares', 'insumos', 'materiais', 'mao_obra', 'equipamentos', 'auxiliares'];
  const problems = Array.isArray(finalResult?.documento_correcao?.composicoes_com_problema)
    ? finalResult.documento_correcao.composicoes_com_problema
    : [];
  const problemKeys = new Set(problems.map((p) => `${p.colecao || ''}::${p.chave || ''}`));

  const blockSources = [];
  for (const collection of ['principais', 'auxiliares_globais']) {
    if (comp?.[collection] && typeof comp[collection] === 'object') blockSources.push({ pathPrefix: ['composicoes', collection], collection, blocks: comp[collection] });
    if (comp?.sinapi_like?.[collection] && typeof comp.sinapi_like[collection] === 'object') blockSources.push({ pathPrefix: ['composicoes', 'sinapi_like', collection], collection, family: 'sinapi_like', blocks: comp.sinapi_like[collection] });
  }

  for (const source of blockSources) {
    const { pathPrefix, collection, blocks } = source;
    for (const [key, block] of Object.entries(blocks || {})) {
      const principalBank = block?.principal?.banco || block?.principal?.fonte || block?.banco || key.split('|')[1] || '';
      // SICRO has its own validator and text repair engine. Targeted recovery is for SINAPI-like/PRÓPRIO leftovers.
      if (isSicroBank(principalBank) || key.toUpperCase().includes('|SICRO')) continue;
      if (problemKeys.size && !problemKeys.has(`${collection}::${key}`) && !problemKeys.has(`sinapi_like.${collection}::${key}`)) continue;
      const page = Number(block?.pagina_inicio || (Array.isArray(block?.paginas) ? block.paginas[0] : 0) || 0);

      if (block?.principal) {
        const desc = String(block.principal.descricao || block.principal.especificacao || '').trim();
        let issue = '';
        if (!desc) issue = 'missing_description';
        else if (isPossiblyTruncatedDescription(desc)) issue = 'possible_truncated_description';
        else if (isProfileRecoveryCandidate(desc)) issue = 'possible_broken_line_description';
        if (issue) {
          const t = makeRecoveryTarget(block, [...pathPrefix, key, 'principal'], block.principal, issue, page, { collection, family: source.family || '', comp_key: key, row_group: 'principal' });
          if (t) targets.push(t);
        }
      }

      for (const group of rowGroups) {
        const rows = Array.isArray(block?.[group]) ? block[group] : [];
        rows.forEach((row, idx) => {
          if (!row || typeof row !== 'object') return;
          const bank = row?.banco || row?.fonte || row?.banco_coluna || '';
          if (isSicroBank(bank)) return;
          const desc = String(row.descricao || row.especificacao || '').trim();
          let issue = '';
          if (!desc) issue = 'missing_description';
          else if (isPossiblyTruncatedDescription(desc)) issue = 'possible_truncated_description';
          else if (isProfileRecoveryCandidate(desc)) issue = 'possible_broken_line_description';
          if (!issue) return;
          const t = makeRecoveryTarget(block, [...pathPrefix, key, group, idx], row, issue, page, { collection, family: source.family || '', comp_key: key, row_group: group, row_index: idx });
          if (t) targets.push(t);
        });
      }
    }
  }

  const budgetRange = finalResult?.meta?.input_metadata?.ranges?.orcamento || finalResult?.meta?.input_metadata?.ranges?.budget || [];
  const budgetStartPage = Number(Array.isArray(budgetRange) ? budgetRange[0] : (budgetRange?.[0] || budgetRange?.start || budgetRange?.inicio || 0));
  const walkBudgetTargets = (nodes = [], pathPrefix = ['orcamento_sintetico', 'itens_raiz']) => {
    (nodes || []).forEach((node, idx) => {
      if (!node || typeof node !== 'object') return;
      const path = [...pathPrefix, idx];
      if (String(node?.tipo || '').toLowerCase() === 'item') {
        const desc = String(node.especificacao || node.descricao || '').trim();
        let issue = '';
        if (!desc) issue = 'missing_budget_description';
        else if (isPossiblyTruncatedDescription(desc)) issue = 'possible_truncated_budget_description';
        else if (isProfileRecoveryCandidate(desc)) issue = 'possible_broken_line_budget_description';
        if (issue) {
          const page = Number(node?.pagina || node?.page_hint || node?.pagina_inicio || budgetStartPage || 0);
          const t = makeRecoveryTarget({}, path, node, issue, page, {
            family: 'budget',
            table_family: 'budget',
            field: 'especificacao',
            item: node.item || '',
            row_group: 'budget_item',
            collection: 'orcamento_sintetico',
            neighbor_context: budgetNeighborContextIndex[path.join('.')] || {},
          });
          if (t) targets.push(t);
        }
      }
      if (Array.isArray(node?.filhos)) walkBudgetTargets(node.filhos, [...path, 'filhos']);
    });
  };
  walkBudgetTargets(finalResult?.orcamento_sintetico?.itens_raiz || []);

  addTargetsFromSelectiveReparsePlan(targets, finalResult);
  addTargetsFromSelectiveFieldExecutor(targets, finalResult);

  const seen = new Set();
  return targets.filter((t) => {
    const k = `${t.target_id}|${t.page}|${t.codigo}|${t.banco}`;
    if (seen.has(k)) return false;
    seen.add(k);
    return Number(t.page || 0) > 0;
  });
}


async function callNormalizerRecoveryApiFromWorker(buffer, recoveryPayload, endpoint, fileMeta = {}) {
  setState('normalizer-targeted-recovery-upload-started', { endpoint, sizeBytes: buffer?.byteLength || 0, filename: fileMeta.filename || 'normalizer-targeted-recovery.pdf', targets: (recoveryPayload.targets || []).length, pages: Object.values(recoveryPayload.page_map || {}) });
  const fd = new FormData();
  fd.append('file', new Blob([buffer], { type: 'application/pdf' }), fileMeta.filename || 'normalizer-targeted-recovery.pdf');
  fd.append('payload', JSON.stringify(recoveryPayload || {}));
  const headers = {};
  const apiKey = fileMeta.normalizerApiKey || recoveryPayload?.normalizer_api_key || '';
  const apiKeyHeader = fileMeta.normalizerApiKeyHeader || recoveryPayload?.normalizer_api_key_header || 'x-api-key';
  if (apiKey) headers[apiKeyHeader] = apiKey;
  const controller = new AbortController();
  const timeoutMs = Number(fileMeta.normalizerTimeoutMs || recoveryPayload?.normalizer_timeout_ms || DEFAULT_NORMALIZER_TIMEOUT_MS);
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const started = Date.now();
  try {
    const response = await fetch(endpoint, { method: 'POST', body: fd, headers, signal: controller.signal });
    const text = await response.text();
    let data = null;
    try { data = JSON.parse(text); } catch (_e) { data = { raw: text }; }
    if (!response.ok) throw buildWorkerError('NORMALIZER_RECOVERY_HTTP_ERROR', `API Normalizer Recovery retornou HTTP ${response.status}.`, { endpoint, status: response.status, response: data });
    setState('normalizer-targeted-recovery-received', { elapsedMs: Date.now() - started, patches: (data.patches || []).length, unresolved: (data.unresolved || []).length, summary: data.summary || {} });
    return data;
  } catch (error) {
    if (error?.name === 'AbortError') throw buildWorkerError('NORMALIZER_RECOVERY_TIMEOUT', `API Normalizer Recovery excedeu ${timeoutMs}ms.`, { endpoint, timeoutMs });
    throw error;
  } finally {
    clearTimeout(timer);
  }
}


async function callNormalizerRecoveryLocalPyodide(targetPath, recoveryPayload, fileMeta = {}) {
  setState('normalizer-local-recovery-started', { path: targetPath, filename: fileMeta.filename || 'normalizer-targeted-recovery.pdf', targets: (recoveryPayload.targets || []).length, pages: Object.values(recoveryPayload.page_map || {}) });
  const started = Date.now();
  try {
    const jsonString = await callParserFunction('recover_fields_local_file_json', targetPath, JSON.stringify(recoveryPayload || {}));
    const data = JSON.parse(jsonString || '{}');
    if (data && (data.status === 'error' || data.ok === false)) {
      const err = data.error || {};
      setState('normalizer-local-recovery-failed-nonfatal', { code: err.code || 'normalizer_local_recovery_failed', message: err.message || 'Falha não fatal no targeted recovery local.' });
      return { status: 'error_nonfatal', patches: [], unresolved: data.unresolved || [], summary: data.summary || {}, error: err };
    }
    setState('normalizer-local-recovery-finished', { elapsedMs: Date.now() - started, patches: (data.patches || []).length, unresolved: (data.unresolved || []).length, summary: data.summary || {} });
    return data;
  } catch (error) {
    setState('normalizer-local-recovery-failed-nonfatal', { code: error?.code || 'normalizer_local_recovery_failed', message: error?.message || String(error) });
    return { status: 'error_nonfatal', patches: [], unresolved: [], summary: {}, error: { code: error?.code || 'normalizer_local_recovery_failed', message: error?.message || String(error) } };
  }
}


async function buildSelectedPagesPdfBufferFromPath(pdfPath, pages) {
  const uniquePages = [...new Set((pages || []).map((p) => Number(p)).filter((p) => Number.isFinite(p) && p > 0))].sort((a, b) => a - b);
  if (!uniquePages.length) {
    throw buildWorkerError('TARGETED_RECOVERY_NO_PAGES', 'Nenhuma página válida para mini-PDF direcionado.', { pages });
  }
  setState('targeted-recovery-pdf-building', { pages: uniquePages, note: 'Gerando mini-PDF direcionado localmente no Pyodide.' });
  const payload = { pages: uniquePages, max_pages: 12, purpose: 'normalizer_targeted_recovery' };
  const selectedString = await callParserFunction('build_selected_pages_pdf_file_json', pdfPath, JSON.stringify(payload));
  const selectedInfo = JSON.parse(selectedString || '{}');
  if (selectedInfo && selectedInfo.status === 'error') {
    throw buildWorkerError(
      selectedInfo.error?.code || 'TARGETED_RECOVERY_PDF_BUILD_FAILED',
      selectedInfo.error?.message || 'Falha ao gerar mini-PDF direcionado.',
      selectedInfo.error?.detail || { pages: uniquePages }
    );
  }
  const targetPath = selectedInfo.targeted_pdf_path;
  if (!targetPath) {
    throw buildWorkerError('TARGETED_RECOVERY_PDF_PATH_MISSING', 'O mini-PDF direcionado foi gerado sem caminho de saída.', { pages: uniquePages, selectedInfo });
  }
  const targetBytes = pyodide.FS.readFile(targetPath);
  const targetBuffer = targetBytes.buffer.slice(targetBytes.byteOffset, targetBytes.byteOffset + targetBytes.byteLength);
  const targetMeta = selectedInfo.targeted_recovery_pdf || {};
  setState('targeted-recovery-pdf-ready', {
    pages: uniquePages,
    sizeBytes: targetBuffer.byteLength,
    pageMap: targetMeta.page_map || {},
    localPageCount: targetMeta.local_page_count || uniquePages.length,
  });
  return { targetBuffer, targetPath, targetMeta };
}

async function runTargetedRecoveryIfNeeded(pdfPath, finalPreliminary, compositionsStage, doclingForParser, payload, initialPayload, fileMeta) {
  const targets = collectTargetedRecoveryTargets(finalPreliminary);
  if (!targets.length || initialPayload?.normalizer_targeted_recovery_enabled === false) {
    return { final: finalPreliminary, compositions: compositionsStage, recovery: { attempted: false, reason: 'no_targets', targets: 0 } };
  }
  const pages = [...new Set(targets.map((t) => Number(t.page)).filter((p) => p > 0))].sort((a, b) => a - b);
  if (!pages.length) return { final: finalPreliminary, compositions: compositionsStage, recovery: { attempted: false, reason: 'no_target_pages', targets: targets.length } };
  let targetPath = null;
  try {
    const { targetBuffer, targetPath: generatedPath, targetMeta } = await buildSelectedPagesPdfBufferFromPath(pdfPath, pages);
    targetPath = generatedPath;
    const recoveryPayload = {
      version: RELEASE_VERSION,
      mode: 'targeted_recovery',
      page_map: targetMeta.page_map || {},
      targeted_recovery_pdf: targetMeta,
      targets,
      column_maps: doclingForParser?.tables || {},
      structured_tables: doclingForParser || {},
      document_learning_profile: finalPreliminary?.meta?.performance?.document_learning_profile || {},
      description_registry: buildDescriptionRegistryFromFinal(finalPreliminary),
      apply_confidence_min: 0.90,
      parser_contract: { ...(initialPayload?.parser_contract || {}), targeted_recovery: true, respect_document_column_order: true, profile_aware_broken_line_recovery: true },
    };
    const mode = resolveNormalizerMode(payload, initialPayload);
    if (mode !== 'api') {
      const recovery = await callNormalizerRecoveryLocalPyodide(targetPath, recoveryPayload, { ...fileMeta, filename: 'normalizer-targeted-recovery.pdf' });
      return { final: finalPreliminary, compositions: compositionsStage, recovery: { attempted: true, mode: 'local_pyodide', ...recovery, target_pages: pages, target_count: targets.length } };
    }
    const endpoint = resolveNormalizerRecoveryEndpoint(payload, initialPayload);
    if (!endpoint) {
      return { final: finalPreliminary, compositions: compositionsStage, recovery: { attempted: true, mode: 'api', status: 'skipped', reason: 'normalizer_api_endpoint_missing', patches: [], unresolved: [], target_pages: pages, target_count: targets.length } };
    }
    try {
      const recovery = await callNormalizerRecoveryApiFromWorker(targetBuffer, recoveryPayload, endpoint, { ...fileMeta, filename: 'normalizer-targeted-recovery.pdf' });
      return { final: finalPreliminary, compositions: compositionsStage, recovery: { attempted: true, mode: 'api', ...recovery, target_pages: pages, target_count: targets.length } };
    } catch (error) {
      setState('normalizer-api-disabled-nonfatal', { code: error?.code || 'normalizer_recovery_api_failed', message: error?.message || String(error) });
      return { final: finalPreliminary, compositions: compositionsStage, recovery: { attempted: true, mode: 'api', status: 'error_nonfatal', error: { code: error?.code || 'normalizer_recovery_api_failed', message: error?.message || String(error) }, patches: [], unresolved: [], target_pages: pages, target_count: targets.length } };
    }
  } finally {
    try { if (targetPath) pyodide.FS.unlink(targetPath); } catch (_e) {}
  }
}

async function callDoclingApiFromWorker(buffer, initialPayload, endpoint, fileMeta = {}) {
  setState('docling-api-upload-started', { endpoint, sizeBytes: buffer?.byteLength || 0, sentPdfKind: fileMeta.sentPdfKind || 'seed_pdf', filename: fileMeta.filename || initialPayload?.filename || 'docling-seed-pages.pdf' });
  const fd = new FormData();
  const blob = new Blob([buffer], { type: fileMeta.contentType || 'application/pdf' });
  fd.append('file', blob, fileMeta.filename || initialPayload?.filename || 'docling-seed-pages.pdf');
  fd.append('payload', JSON.stringify(initialPayload || {}));
  const started = Date.now();
  const headers = {};
  const apiKey = fileMeta.doclingApiKey || initialPayload?.docling_api_key || initialPayload?.doclingApiKey || '';
  const apiKeyHeader = fileMeta.doclingApiKeyHeader || initialPayload?.docling_api_key_header || initialPayload?.doclingApiKeyHeader || 'x-api-key';
  if (apiKey) headers[apiKeyHeader] = apiKey;
  const timeoutMs = Number(fileMeta.doclingTimeoutMs || initialPayload?.docling_timeout_ms || initialPayload?.doclingTimeoutMs || DEFAULT_DOCLING_TIMEOUT_MS);
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), Math.max(1000, timeoutMs));
  let response;
  try {
    response = await fetch(endpoint, { method: 'POST', body: fd, headers, signal: controller.signal });
  } catch (error) {
    if (error?.name === 'AbortError') {
      throw buildWorkerError('DOCLING_API_TIMEOUT', `API Docling excedeu o timeout de ${timeoutMs}ms.`, { endpoint, timeoutMs });
    }
    throw buildWorkerError('DOCLING_API_NETWORK_ERROR', error?.message || String(error), { endpoint });
  } finally {
    clearTimeout(timeoutId);
  }
  const text = await response.text();
  let data = text;
  try { data = JSON.parse(text); } catch (_e) {}
  if (!response.ok) {
    throw buildWorkerError('DOCLING_API_FAILED', `API Docling falhou: ${response.status}`, { status: response.status, response: data });
  }
  const tableObj = data?.tables || data?.structured_tables?.tables || {};
  const perf = data?.metadata?.performance_trace || {};
  const cache = data?.metadata?.cache || {};
  const schema = data?.metadata?.docling_schema_normalization || {};
  setState('docling-response-received', {
    elapsedMs: Date.now() - started,
    sentPdfKind: fileMeta.sentPdfKind || 'seed_pdf',
    tableCount: Array.isArray(tableObj) ? tableObj.length : Object.keys(tableObj || {}).length,
    cacheHit: !!cache.hit,
    cacheStatus: cache.status || (cache.bypass ? 'BYPASS' : (cache.hit ? 'HIT' : 'MISS')),
    apiMode: data?.metadata?.api_mode || '',
    performanceTrace: perf,
    missingColumns: schema.missing_columns || [],
    syntheticColumns: schema.synthetic_columns || [],
  });
  return data;
}

function shouldRetryDocling(error) {
  const code = error?.code || '';
  const status = Number(error?.detail?.status || 0);
  if (code === 'DOCLING_API_TIMEOUT') return false;
  if (code === 'DOCLING_API_NETWORK_ERROR') return true;
  return [502, 503, 504].includes(status);
}

async function clearDoclingCacheIfRequested(endpoint, fileMeta = {}) {
  if (!fileMeta.clearDoclingCacheBeforeRun) return;
  const adminEndpoint = endpoint.replace(/\/docling\/extract-table-structure$/i, '/admin/cache/clear').replace(/\/extract-table-structure$/i, '/admin/cache/clear');
  try {
    setState('docling-cache-clear-started', { endpoint: adminEndpoint });
    const headers = {};
    const apiKey = fileMeta.doclingApiKey || '';
    const apiKeyHeader = fileMeta.doclingApiKeyHeader || 'x-api-key';
    if (apiKey) headers[apiKeyHeader] = apiKey;
    const response = await fetch(adminEndpoint, { method: 'POST', headers });
    setState('docling-cache-clear-finished', { endpoint: adminEndpoint, status: response.status, ok: response.ok });
  } catch (error) {
    setState('docling-cache-clear-failed', { message: error?.message || String(error) });
  }
}

async function callDoclingApiWithRetry(buffer, initialPayload, endpoint, fileMeta = {}) {
  await clearDoclingCacheIfRequested(endpoint, fileMeta);
  if (fileMeta.bypassDoclingCache) initialPayload = { ...(initialPayload || {}), bypass_cache: true, docling_seed_pdf_policy: { ...(initialPayload?.docling_seed_pdf_policy || {}), bypass_cache: true }, parser_contract: { ...(initialPayload?.parser_contract || {}), bypass_docling_cache: true } };
  const totalBudgetMs = Number(fileMeta.doclingTimeoutMs || initialPayload?.docling_timeout_ms || DEFAULT_DOCLING_TIMEOUT_MS);
  const maxAttempts = Number(initialPayload?.fixed_contract?.docling_execution_policy?.max_docling_attempts || initialPayload?.docling_max_attempts || 2);
  const started = Date.now();
  let lastError = null;
  for (let attempt = 1; attempt <= Math.max(1, Math.min(maxAttempts, 3)); attempt++) {
    const remaining = totalBudgetMs - (Date.now() - started);
    if (remaining <= 1000) break;
    try {
      setState(`docling-api-attempt-${attempt}`, { attempt, remainingMs: remaining });
      return await callDoclingApiFromWorker(buffer, initialPayload, endpoint, { ...fileMeta, doclingTimeoutMs: Math.max(1000, remaining) });
    } catch (error) {
      lastError = error;
      if (!shouldRetryDocling(error) || attempt >= maxAttempts) throw error;
      setState('docling-api-retry', { attempt, code: error?.code || 'unknown' });
      await new Promise((resolve) => setTimeout(resolve, Math.min(1500 * attempt, 3000)));
    }
  }
  throw lastError || buildWorkerError('DOCLING_API_FAILED', 'API Docling falhou antes de concluir as tentativas.');
}

async function initPyodideRuntime(options = {}) {
  if (pyodide) return;
  manifest = manifest || await loadManifest(options.manifestUrl || './manifest.json', options);
  const pyodideBaseUrl = options.pyodideBaseUrl || manifest.pyodideBaseUrl;
  setState('loading-runtime', { pyodideBaseUrl });
  importScripts(`${pyodideBaseUrl}pyodide.js`);
  pyodide = await loadPyodide({ indexURL: pyodideBaseUrl });

  const builtinPackages = manifest.builtinPackages || [];
  if (builtinPackages.length) {
    setState('loading-builtins', { packages: builtinPackages });
    await pyodide.loadPackage(builtinPackages);
  }

  setState('loading-micropip');
  await pyodide.loadPackage('micropip');
  const micropip = pyodide.pyimport('micropip');

  const packages = manifest.packages || [];
  if (packages.length) {
    setState('installing-python-packages', { packages });
    await micropip.install(packages);
  }
  if (typeof micropip.destroy === 'function') micropip.destroy();

  const sourceArchiveUrl = options.sourceArchiveUrl || manifest.sourceArchive;
  const archiveBuffer = await loadSourceArchive(sourceArchiveUrl, options);
  pyodide.unpackArchive(archiveBuffer, 'zip');
  pyodide.runPython(`import sys\nif '.' not in sys.path:\n    sys.path.insert(0, '.')\n`);

  setState('importing-parser-entry', { entryModule: manifest.entryModule });
  parserModule = pyodide.pyimport(manifest.entryModule);
  try {
    if (parserModule?.normalizer_exports_json) {
      normalizerCapabilities = JSON.parse(await parserModule.normalizer_exports_json());
      setState('normalizer-local-exports', { exports: normalizerCapabilities.exports || {}, version: normalizerCapabilities.version || null });
    } else {
      normalizerCapabilities = { status: 'missing', exports: {} };
      setState('normalizer-local-exports-missing', { message: 'normalizer_exports_json indisponível; fallback Docling será usado.' });
    }
  } catch (error) {
    normalizerCapabilities = { status: 'error', exports: {}, error: error?.message || String(error) };
    setState('normalizer-local-exports-error', { message: error?.message || String(error) });
  }
  setState('ready');
}

async function ensureInitialized(options = {}) {
  if (!initPromise) {
    initPromise = initPyodideRuntime(options).catch((error) => {
      initPromise = null;
      pyodide = null;
      parserModule = null;
      manifest = null;
      throw error;
    });
  }
  return initPromise;
}

function createTempPdfPath(prefix = 'upload') {
  return `/tmp/${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}.pdf`;
}

function toErrorPayload(error) {
  if (error && typeof error === 'object' && error.code && error.message) return error;
  return buildWorkerError('WORKER_RUNTIME_ERROR', error?.message || String(error), null, error?.stack || null);
}

async function callParserFunction(name, ...args) {
  const fn = parserModule?.[name];
  if (!fn) {
    throw buildWorkerError('PARSER_FUNCTION_NOT_FOUND', `Função Python não encontrada: ${name}`);
  }
  return await fn(...args);
}

async function runFileTask(payload, functionName, statusName) {
  validateParsePayload(payload);
  const { buffer } = payload;
  const fileMeta = { filename: payload.filename || payload.options?.filename || 'upload.pdf', contentType: payload.contentType || payload.options?.content_type || 'application/pdf' };
  const options = normalizeLegacyOrLovableOptions(payload.options || {}, fileMeta);
  validateBaseOptions(options);
  setState(statusName);
  const pdfPath = createTempPdfPath();
  activeParsePath = pdfPath;
  try {
    setState('writing-pdf-bytes', { sizeBytes: buffer.byteLength });
    pyodide.FS.writeFile(pdfPath, new Uint8Array(buffer));
    setState('running-parser', { task: functionName, pdfPath });
    const jsonString = await callParserFunction(functionName, pdfPath, JSON.stringify(options || {}));
    const result = JSON.parse(jsonString);
    if (result && result.status === 'error' && result.error) {
      throw buildWorkerError(result.error.code || 'PARSER_RUNTIME_ERROR', result.error.message || 'Falha ao processar o PDF.', result.error.detail || null);
    }
    setState('done', { task: functionName });
    return result;
  } finally {
    try { pyodide.FS.unlink(pdfPath); } catch (_e) {}
    activeParsePath = null;
  }
}

async function runMergeTask(payload) {
  if (!payload || typeof payload !== 'object') throw buildWorkerError('INVALID_PAYLOAD', 'Payload de merge ausente ou inválido.');
  validateBaseOptions(payload.options || {});
  setState('merging');
  const jsonString = await callParserFunction('merge_stages_json', JSON.stringify(payload.budget || {}), JSON.stringify(payload.compositions || {}), JSON.stringify(payload.options || {}));
  const result = JSON.parse(jsonString);
  if (result && result.status === 'error' && result.error) {
    throw buildWorkerError(result.error.code || 'PARSER_RUNTIME_ERROR', result.error.message || 'Falha ao consolidar resultados.', result.error.detail || null);
  }
  setState('done', { task: 'merge' });
  return result;
}

async function buildSeedPdfBufferFromPath(pdfPath, initialPayload) {
  setState('seed-pdf-building', { note: 'Extraindo páginas seed no Pyodide; PDF completo permanece local.' });
  const seedString = await callParserFunction('build_docling_seed_pdf_file_json', pdfPath, JSON.stringify(initialPayload || {}));
  const seedInfo = JSON.parse(seedString);
  if (seedInfo && seedInfo.status === 'error') {
    throw buildWorkerError(seedInfo.error?.code || 'DOCLING_SEED_EXTRACTION_FAILED', seedInfo.error?.message || 'Falha ao gerar mini-PDF seed.', seedInfo.error?.detail || null);
  }
  const seedPath = seedInfo.seed_pdf_path;
  const seedBytes = pyodide.FS.readFile(seedPath);
  const seedBuffer = seedBytes.buffer.slice(seedBytes.byteOffset, seedBytes.byteOffset + seedBytes.byteLength);
  return { seedBuffer, seedPath, seedMeta: seedInfo.docling_seed_pdf || {} };
}

async function runDoclingOnlyTask(payload) {
  validateParsePayload({ buffer: payload.buffer, options: normalizeLovablePayloadToOptions(payload.payload || {}, { filename: payload.filename || 'upload.pdf', contentType: payload.contentType || 'application/pdf' }) });
  const { buffer } = payload;
  const initialPayload = payload.payload || {};
  const fileMeta = {
    filename: payload.filename || initialPayload.filename || initialPayload.document?.filename || 'upload.pdf',
    contentType: payload.contentType || initialPayload.content_type || 'application/pdf',
    doclingApiKey: payload.doclingApiKey || initialPayload.docling_api_key || '',
    doclingApiKeyHeader: payload.doclingApiKeyHeader || initialPayload.docling_api_key_header || 'x-api-key',
    doclingTimeoutMs: payload.doclingTimeoutMs || initialPayload.docling_timeout_ms || DEFAULT_DOCLING_TIMEOUT_MS,
    normalizerApiKey: payload.normalizerApiKey || initialPayload.normalizer_api_key || '',
    normalizerApiKeyHeader: payload.normalizerApiKeyHeader || initialPayload.normalizer_api_key_header || 'x-api-key',
    normalizerTimeoutMs: payload.normalizerTimeoutMs || initialPayload.normalizer_timeout_ms || DEFAULT_NORMALIZER_TIMEOUT_MS,
    bypassDoclingCache: !!(payload.bypassDoclingCache || initialPayload.bypass_cache),
    clearDoclingCacheBeforeRun: !!(payload.clearDoclingCacheBeforeRun || initialPayload.clear_docling_cache_before_run),
  };
  const endpoint = resolveDoclingEndpoint(payload, initialPayload);
  const pdfPath = createTempPdfPath('docling-only');
  activeParsePath = pdfPath;
  let seedPath = null;
  try {
    setState('writing-pdf-bytes', { sizeBytes: buffer.byteLength, mode: 'docling-only', note: 'PDF completo fica apenas no FS Pyodide temporário.' });
    pyodide.FS.writeFile(pdfPath, new Uint8Array(buffer));
    const { seedBuffer, seedPath: generatedSeedPath, seedMeta } = await buildSeedPdfBufferFromPath(pdfPath, initialPayload);
    seedPath = generatedSeedPath;
    setState('seed-pdf-ready', { originalSizeBytes: buffer.byteLength, seedSizeBytes: seedBuffer.byteLength, pageMap: seedMeta.page_map || {}, roles: seedMeta.roles || {}, sentPdfKind: 'seed_pdf' });
    const doclingPayload = buildDoclingPayloadForApi(initialPayload, seedMeta);
    const docling = await callDoclingApiWithRetry(seedBuffer, doclingPayload, endpoint, { ...fileMeta, filename: 'docling-seed-pages.pdf', sentPdfKind: 'seed_pdf' });
    const doclingRaw = mergeDoclingForParser(docling, seedMeta);
    const normalizerEndpoint = resolveNormalizerEndpoint(payload, initialPayload);
    const refined = await refineWithNormalizerOrFallback(seedBuffer, seedPath, seedMeta, initialPayload, doclingRaw, normalizerEndpoint, fileMeta, payload);
    return { status: 'ok', sent_pdf_kind: 'seed_pdf', docling_seed_pdf: seedMeta, docling_response: refined.payload, normalizer_used: refined.used };
  } finally {
    try { if (seedPath) pyodide.FS.unlink(seedPath); } catch (_e) {}
    try { pyodide.FS.unlink(pdfPath); } catch (_e) {}
    activeParsePath = null;
  }
}


async function runLovableFlowTask(payload) {
  if (!payload || typeof payload !== 'object') throw buildWorkerError('INVALID_PAYLOAD', 'Payload Lovable ausente ou inválido.');
  const { buffer } = payload;
  if (!buffer || !(buffer instanceof ArrayBuffer)) {
    throw buildWorkerError('PDF_NOT_PROVIDED', 'Nenhum PDF foi enviado ao fluxo Lovable.', { receivedType: buffer?.constructor?.name || typeof buffer });
  }
  const initialPayload = payload.payload || payload.options || {};
  const fileMeta = {
    filename: payload.filename || initialPayload.filename || initialPayload.document?.filename || 'upload.pdf',
    contentType: payload.contentType || initialPayload.content_type || 'application/pdf',
    doclingApiKey: payload.doclingApiKey || initialPayload.docling_api_key || initialPayload.doclingApiKey || '',
    doclingApiKeyHeader: payload.doclingApiKeyHeader || initialPayload.docling_api_key_header || initialPayload.doclingApiKeyHeader || 'x-api-key',
    doclingTimeoutMs: payload.doclingTimeoutMs || initialPayload.docling_timeout_ms || initialPayload.doclingTimeoutMs || DEFAULT_DOCLING_TIMEOUT_MS,
    normalizerApiKey: payload.normalizerApiKey || initialPayload.normalizer_api_key || initialPayload.normalizerApiKey || '',
    normalizerApiKeyHeader: payload.normalizerApiKeyHeader || initialPayload.normalizer_api_key_header || initialPayload.normalizerApiKeyHeader || 'x-api-key',
    normalizerTimeoutMs: payload.normalizerTimeoutMs || initialPayload.normalizer_timeout_ms || initialPayload.normalizerTimeoutMs || DEFAULT_NORMALIZER_TIMEOUT_MS,
    bypassDoclingCache: !!(payload.bypassDoclingCache || initialPayload.bypass_cache),
    clearDoclingCacheBeforeRun: !!(payload.clearDoclingCacheBeforeRun || initialPayload.clear_docling_cache_before_run),
  };
  const endpoint = resolveDoclingEndpoint(payload, initialPayload);

  const pdfPath = createTempPdfPath('upload');
  let seedPath = null;
  activeParsePath = pdfPath;
  try {
    setState('writing-pdf-bytes-once', { sizeBytes: buffer.byteLength });
    pyodide.FS.writeFile(pdfPath, new Uint8Array(buffer));

    const { seedBuffer, seedPath: generatedSeedPath, seedMeta } = await buildSeedPdfBufferFromPath(pdfPath, initialPayload);
    seedPath = generatedSeedPath;
    setState('seed-pdf-ready', { originalSizeBytes: buffer.byteLength, seedSizeBytes: seedBuffer.byteLength, pageMap: seedMeta.page_map || {}, roles: seedMeta.roles || {}, sentPdfKind: 'seed_pdf' });

    const doclingPayload = buildDoclingPayloadForApi(initialPayload, seedMeta);
    const docling = await callDoclingApiWithRetry(seedBuffer, doclingPayload, endpoint, { ...fileMeta, filename: 'docling-seed-pages.pdf', sentPdfKind: 'seed_pdf' });
    const doclingRaw = mergeDoclingForParser(docling, seedMeta);
    const normalizerEndpoint = resolveNormalizerEndpoint(payload, initialPayload);
    const refined = await refineWithNormalizerOrFallback(seedBuffer, seedPath, seedMeta, initialPayload, doclingRaw, normalizerEndpoint, fileMeta, payload);
    const doclingForParser = refined.payload;
    const options = normalizeLovablePayloadToOptions({ ...initialPayload, structured_tables: doclingForParser, docling_clean_payload: doclingForParser, normalizer_clean_payload: doclingForParser, normalizer_report: doclingForParser?.metadata?.normalizer_report || {}, docling_seed_pdf: seedMeta }, fileMeta);
    validateBaseOptions(options);

    setState('running-budget-preview');
    const budgetString = await callParserFunction('parse_budget_file_json', pdfPath, JSON.stringify(options || {}));
    const budget = JSON.parse(budgetString);
    if (budget && budget.status === 'error' && budget.error) {
      throw buildWorkerError(budget.error.code || 'PARSER_RUNTIME_ERROR', budget.error.message || 'Falha ao processar orçamento.', budget.error.detail || null);
    }
    const preview = {
      status: 'partial',
      preview: true,
      preview_kind: 'orcamento_sintetico',
      orcamento_sintetico: budget.orcamento_sintetico || {},
      stage_meta: budget._stage_meta || {},
      docling_summary: doclingForParser?.metadata?.summary || null,
      docling_seed_pdf: seedMeta,
    };
    self.postMessage({ type: 'preview', payload: preview });

    setState('running-compositions-stage');
    const compositionsString = await callParserFunction('parse_compositions_file_json', pdfPath, JSON.stringify(options || {}));
    const compositions = JSON.parse(compositionsString);
    if (compositions && compositions.status === 'error' && compositions.error) {
      throw buildWorkerError(compositions.error.code || 'PARSER_RUNTIME_ERROR', compositions.error.message || 'Falha ao processar composições.', compositions.error.detail || null);
    }

    setState('merging-stages');
    const finalString = await callParserFunction('merge_stages_json', JSON.stringify(budget || {}), JSON.stringify(compositions || {}), JSON.stringify(options || {}));
    let final = JSON.parse(finalString);
    if (final && final.status === 'error' && final.error) {
      throw buildWorkerError(final.error.code || 'PARSER_RUNTIME_ERROR', final.error.message || 'Falha ao consolidar resultados.', final.error.detail || null);
    }

    const preliminaryCorrection = final.documento_correcao || null;
    const recoveryResult = await runTargetedRecoveryIfNeeded(pdfPath, final, compositions, doclingForParser, payload, initialPayload, fileMeta);
    let finalCompositionsStage = compositions;
    if (recoveryResult?.recovery?.attempted && Number((recoveryResult?.recovery?.patches || []).length || 0) > 0) {
      setState('targeted-recovery-commit-started', { received: (recoveryResult.recovery.patches || []).length });
      const committedString = await callParserFunction('apply_targeted_recovery_json', JSON.stringify(final || {}), JSON.stringify(recoveryResult.recovery || {}), JSON.stringify(options || {}));
      final = JSON.parse(committedString);
      if (final && final.status === 'error' && final.error) {
        throw buildWorkerError(final.error.code || 'TARGETED_RECOVERY_COMMIT_FAILED', final.error.message || 'Falha ao aplicar patches do targeted recovery.', final.error.detail || null);
      }
      const tr = final?.meta?.targeted_recovery || {};
      setState('targeted-recovery-patches-committed', { received: tr.received || 0, committed: tr.committed || 0, verified: tr.verified || 0, failed: tr.failed || 0 });
    } else {
      final.meta = { ...(final.meta || {}), targeted_recovery: recoveryResult?.recovery || { attempted: false } };
      if (final.documento_correcao) {
        final.documento_correcao.targeted_recovery = recoveryResult?.recovery || { attempted: false };
        final.documento_correcao.correction_preliminary_resumo = preliminaryCorrection?.resumo || null;
      }
    }
    let accuracyReport = null;
    const expectedResult = initialPayload.expected_final_result || initialPayload.expectedFinalResult || initialPayload.golden_expected_result || null;
    if (expectedResult && typeof expectedResult === 'object') {
      try {
        setState('accuracy-benchmark-started', { source: 'payload_expected_final_result' });
        accuracyReport = JSON.parse(await callParserFunction('generate_accuracy_report_json', JSON.stringify(final || {}), JSON.stringify(expectedResult || {}), RELEASE_VERSION));
        final.meta = { ...(final.meta || {}), accuracy_report: accuracyReport };
        setState('accuracy-benchmark-finished', { overall: accuracyReport?.overall_field_accuracy, cases: accuracyReport?.case_count || 0 });
      } catch (e) {
        setState('accuracy-benchmark-failed-nonfatal', { message: String(e && e.message || e) });
      }
    }
    try {
      const overlay = JSON.parse(await callParserFunction('build_debug_overlay_json', JSON.stringify(final || {}), JSON.stringify(doclingForParser || {}), JSON.stringify(recoveryResult?.recovery || {}), JSON.stringify(accuracyReport || {})));
      final.meta = { ...(final.meta || {}), debug_overlay: overlay };
      if (final.documento_correcao) final.documento_correcao.debug_overlay_summary = overlay.summary || null;
      setState('debug-overlay-ready', overlay.summary || {});
    } catch (e) {
      setState('debug-overlay-failed-nonfatal', { message: String(e && e.message || e) });
    }

    // v61.0.23: expose the clean, post-merge composition contract to Lovable.
    // The raw composition stage is intentionally not returned as the main
    // artifact because it contains legacy intermediate SICRO shapes.
    finalCompositionsStage = {
      status: 'ok',
      source: 'final_result_clean_compositions',
      contract_version: 'v61.0.35-candidate-profile-consensus-engine',
      composicoes: final?.composicoes || {},
      sicro_native: final?.documento_correcao?.sicro_native || null,
    };
    setState('done', { task: 'lovable-flow' });
    return { status: 'ok', docling_response: doclingForParser, normalizer_used: refined.used, normalizer_report: doclingForParser?.metadata?.normalizer_report || null, docling_seed_pdf: seedMeta, budget_preview: preview, budget_stage: budget, compositions_stage: finalCompositionsStage, final_result: final, correction_document: final.documento_correcao || null, correction_preliminary: preliminaryCorrection };
  } finally {
    try { if (seedPath) pyodide.FS.unlink(seedPath); } catch (_e) {}
    try { pyodide.FS.unlink(pdfPath); } catch (_e) {}
    activeParsePath = null;
  }
}

self.onmessage = async (event) => {
  const { type, payload } = event.data || {};
  try {
    if (type === 'init') {
      await ensureInitialized(payload || {});
      self.postMessage({ type: 'ready' });
      return;
    }
    if (type === 'parse' || type === 'parse-base') {
      await ensureInitialized(payload || {});
      const result = await runFileTask(payload || {}, 'parse_base_file_json', 'processing');
      self.postMessage({ type: 'result', payload: result });
      return;
    }
    if (type === 'parse-budget') {
      await ensureInitialized(payload || {});
      const result = await runFileTask(payload || {}, 'parse_budget_file_json', 'processing-budget');
      self.postMessage({ type: 'result', payload: result });
      return;
    }
    if (type === 'parse-compositions') {
      await ensureInitialized(payload || {});
      const result = await runFileTask(payload || {}, 'parse_compositions_file_json', 'processing-compositions');
      self.postMessage({ type: 'result', payload: result });
      return;
    }
    if (type === 'docling-only') {
      await ensureInitialized(payload || {});
      const result = await runDoclingOnlyTask(payload || {});
      self.postMessage({ type: 'result', payload: result });
      return;
    }
    if (type === 'lovable-flow') {
      await ensureInitialized(payload || {});
      const result = await runLovableFlowTask(payload || {});
      self.postMessage({ type: 'result', payload: result });
      return;
    }
    if (type === 'merge') {
      await ensureInitialized(payload || {});
      const result = await runMergeTask(payload || {});
      self.postMessage({ type: 'result', payload: result });
      return;
    }
    if (type === 'get-state') {
      self.postMessage({ type: 'state', payload: { state: workerState, activeParsePath } });
      return;
    }
    throw buildWorkerError('UNKNOWN_WORKER_MESSAGE', `Mensagem de worker desconhecida: ${type}`);
  } catch (error) {
    const payload = toErrorPayload(error);
    setState('error', { error: payload });
    self.postMessage({ type: 'error', payload });
  }
};
