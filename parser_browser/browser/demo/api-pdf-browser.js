const RELEASE_VERSION = 'v61.0.74-release-integrity-and-diff-scan-hardening';

export function createDownload(filename, data) {
  const blob = new Blob([data], { type: 'application/json;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => {
    URL.revokeObjectURL(url);
    a.remove();
  }, 500);
}

function appendQueryParam(url, key, value) {
  if (!value) return url;
  const joiner = url.includes('?') ? '&' : '?';
  return `${url}${joiner}${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`;
}

function validateOptions(options) {
  const required = ['orcamento_inicio', 'orcamento_fim', 'composicoes_inicio', 'composicoes_fim'];
  for (const field of required) {
    const value = options[field];
    if (!Number.isInteger(value)) {
      throw new Error(`Campo inválido: ${field} precisa ser inteiro.`);
    }
  }
}

function optionsToLovablePayload(file, options) {
  if (options && options.ranges) {
    return {
      version: options.version || RELEASE_VERSION,
      filename: file.name,
      content_type: file.type || 'application/pdf',
      ...options,
    };
  }
  validateOptions(options);
  const budgetStart = Number(options.orcamento_inicio);
  const compStart = Number(options.composicoes_inicio);
  return {
    version: RELEASE_VERSION,
    filename: file.name,
    content_type: file.type || 'application/pdf',
    document: { filename: file.name, title: options.obra_nome || '' },
    ranges: {
      budget: { start: budgetStart, end: Number(options.orcamento_fim) },
      compositions: { start: compStart, end: Number(options.composicoes_fim) },
    },
    docling_seed_pages: {
      budget: options.docling_seed_pages?.budget || options.docling_seed_pages?.budget_header_page || budgetStart,
      composition: options.docling_seed_pages?.composition || options.docling_seed_pages?.composition_schema_page || compStart,
    },
    metadata_extraida_ia: options.metadata_extraida_ia || {},
    ai_hints: options.ai_hints || {},
    tables: options.tables || {},
  };
}

function workerRequest(worker, type, payload, transfer = [], onStatus, onPreview) {
  return new Promise((resolve, reject) => {
    const onMessage = async (event) => {
      const { type: msgType, stage, payload: msgPayload, ...rest } = event.data || {};
      if (msgType === 'status') {
        onStatus?.(stage, { stage, worker: 'parser', ...(rest || {}) });
        return;
      }
      if (msgType === 'preview') {
        onStatus?.('preview-ready', { stage: 'preview-ready', worker: 'parser', preview: msgPayload });
        try {
          await onPreview?.(msgPayload);
        } catch (error) {
          worker.removeEventListener('message', onMessage);
          reject(new Error(`Falha no handler de preview: ${error?.message || String(error)}`));
        }
        return;
      }
      if (msgType === 'result' || msgType === 'ready') {
        worker.removeEventListener('message', onMessage);
        resolve(msgType === 'ready' ? undefined : msgPayload);
        return;
      }
      if (msgType === 'state') {
        onStatus?.('state', { stage: 'state', worker: 'parser', statePayload: msgPayload });
        return;
      }
      if (msgType === 'error') {
        worker.removeEventListener('message', onMessage);
        const err = new Error(msgPayload?.message || 'Falha no worker do parser.');
        err.code = msgPayload?.code;
        err.detail = msgPayload?.detail;
        reject(err);
      }
    };
    worker.addEventListener('message', onMessage);
    worker.postMessage({ type, payload }, transfer);
  });
}

export class ApiPdfBrowserClient {
  constructor(options = {}, onStatus) {
    this.initOptions = options;
    this.statusHandler = onStatus;
    this.createWorker();
  }

  createOneWorker() {
    let workerUrl = this.initOptions.workerUrl || '../pyodide/pyodide-parser-worker.js';
    workerUrl = appendQueryParam(workerUrl, 'v', this.initOptions.versionTag || RELEASE_VERSION);
    workerUrl = appendQueryParam(workerUrl, 'cb', this.initOptions.cacheBust || '');
    return new Worker(workerUrl, { type: 'classic' });
  }

  createWorker() {
    this.worker = this.createOneWorker();
    this.readyPromise = workerRequest(this.worker, 'init', this.initOptions, [], this.statusHandler).then(() => undefined);
  }

  async ready() {
    return this.readyPromise;
  }

  async runFileTask(file, options, type) {
    validateOptions(options);
    await this.ready();
    const buffer = await file.arrayBuffer();
    const payloadOptions = {
      ...options,
      filename: file.name,
      content_type: file.type || 'application/pdf',
    };
    return workerRequest(this.worker, type, { buffer, options: payloadOptions }, [buffer], this.statusHandler);
  }

  async parse(file, options) {
    return this.parseBase(file, options);
  }

  async parseBase(file, options) {
    return this.runFileTask(file, options, 'parse-base');
  }

  async parseBudgetStage(file, options) {
    return this.runFileTask(file, options, 'parse-budget');
  }

  async parseCompositionsStage(file, options) {
    return this.runFileTask(file, options, 'parse-compositions');
  }

  async runDoclingOnly(file, initialPayload) {
    await this.ready();
    const buffer = await file.arrayBuffer();
    const payload = {
      buffer,
      payload: { version: initialPayload.version || RELEASE_VERSION, ...initialPayload },
      filename: file.name,
      contentType: file.type || 'application/pdf',
      doclingEndpoint: this.initOptions.doclingEndpoint,
      doclingApiKey: this.initOptions.doclingApiKey || '',
      doclingApiKeyHeader: this.initOptions.doclingApiKeyHeader || 'x-api-key',
      doclingTimeoutMs: this.initOptions.doclingTimeoutMs || 120000,
      targetedRecoveryMaxPagesPerBatch: this.initOptions.targetedRecoveryMaxPagesPerBatch || 12,
      bypassDoclingCache: !!this.initOptions.bypassDoclingCache,
      clearDoclingCacheBeforeRun: !!this.initOptions.clearDoclingCacheBeforeRun,
      normalizerApiKey: this.initOptions.normalizerApiKey || '',
      normalizerApiKeyHeader: this.initOptions.normalizerApiKeyHeader || 'x-api-key',
      normalizerTimeoutMs: this.initOptions.normalizerTimeoutMs || 90000,
      allowRelativeDoclingEndpoint: !!this.initOptions.allowRelativeDoclingEndpoint,
      production: !!this.initOptions.production,
    };
    return workerRequest(this.worker, 'docling-only', payload, [buffer], this.statusHandler);
  }

  async runLovableFlow(file, initialPayload, handlers = {}) {
    await this.ready();
    const buffer = await file.arrayBuffer();
    const payload = {
      buffer,
      payload: { version: initialPayload.version || RELEASE_VERSION, ...initialPayload },
      filename: file.name,
      contentType: file.type || 'application/pdf',
      doclingEndpoint: this.initOptions.doclingEndpoint,
      doclingApiKey: this.initOptions.doclingApiKey || '',
      doclingApiKeyHeader: this.initOptions.doclingApiKeyHeader || 'x-api-key',
      doclingTimeoutMs: this.initOptions.doclingTimeoutMs || 120000,
      targetedRecoveryMaxPagesPerBatch: this.initOptions.targetedRecoveryMaxPagesPerBatch || 12,
      bypassDoclingCache: !!this.initOptions.bypassDoclingCache,
      clearDoclingCacheBeforeRun: !!this.initOptions.clearDoclingCacheBeforeRun,
      normalizerApiKey: this.initOptions.normalizerApiKey || '',
      normalizerApiKeyHeader: this.initOptions.normalizerApiKeyHeader || 'x-api-key',
      normalizerTimeoutMs: this.initOptions.normalizerTimeoutMs || 90000,
      allowRelativeDoclingEndpoint: !!this.initOptions.allowRelativeDoclingEndpoint,
      production: !!this.initOptions.production,
    };
    return workerRequest(this.worker, 'lovable-flow', payload, [buffer], this.statusHandler, handlers.onPreview);
  }

  async parseWithPreview(file, options, handlers = {}) {
    const payload = optionsToLovablePayload(file, options);
    const flow = await this.runLovableFlow(file, payload, handlers);
    return {
      preview: flow.budget_preview,
      final: flow.final_result,
      budgetStage: flow.budget_stage,
      compositionsStage: flow.compositions_stage,
      flow,
    };
  }

  async mergeStages(budgetPayload, compositionsPayload, options) {
    validateOptions(options);
    await this.ready();
    return workerRequest(this.worker, 'merge', {
      budget: budgetPayload,
      compositions: compositionsPayload,
      options: {
            ...options,
        filename: 'upload.pdf',
        content_type: 'application/pdf',
      },
    }, [], this.statusHandler);
  }

  async getState() {
    await this.ready();
    return workerRequest(this.worker, 'get-state', {}, [], this.statusHandler);
  }

  reset() {
    this.worker.terminate();
    this.createWorker();
  }

  cancelCurrent() { this.reset(); }
  terminate() { this.worker.terminate(); }
}
