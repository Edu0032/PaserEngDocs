const RELEASE_VERSION = 'v61.0.35-candidate-profile-consensus-engine';

export type BrowserParseOptions = {
  base_id?: string;
  orcamento_inicio: number;
  orcamento_fim: number;
  composicoes_inicio: number;
  composicoes_fim: number;
  obra_nome?: string;
  obra_localizacao?: string;
  orgao_nome?: string;
  prefeitura_nome?: string;
  contratante_nome?: string;
  dynamic_ignore_phrases?: string | string[];
  metadata_extraida_ia?: Record<string, unknown>;
  strict_validation?: boolean;
  filename?: string;
  content_type?: string;
  performance_profile?: 'default' | 'standard' | 'fast' | 'browser_fast' | 'browser_robust' | 'robust' | string;
  [key: string]: unknown;
};

export type LovablePayload = Record<string, any>;

export type WorkerInitOptions = {
  workerUrl?: string;
  manifestUrl?: string;
  sourceArchiveUrl?: string;
  pyodideBaseUrl?: string;
  versionTag?: string;
  cacheBust?: string;
  debugNoCache?: boolean;
  doclingEndpoint?: string;
  doclingApiKey?: string;
  doclingApiKeyHeader?: string;
  doclingTimeoutMs?: number;
  normalizerEndpoint?: string;
  normalizerApiKey?: string;
  normalizerApiKeyHeader?: string;
  normalizerTimeoutMs?: number;
  allowRelativeDoclingEndpoint?: boolean;
  production?: boolean;
};

export type WorkerStatusDetail = {
  stage: string;
  worker?: 'parser';
  state?: string;
  [key: string]: unknown;
};

export type BrowserPreviewPayload = {
  status: 'partial';
  preview: true;
  preview_kind?: string;
  orcamento_sintetico: any;
  stage_meta?: Record<string, unknown>;
  docling_seed_pdf?: Record<string, unknown>;
  [key: string]: unknown;
};

export type LovableFlowResult = {
  status: 'ok';
  docling_response: any;
  docling_seed_pdf: any;
  budget_preview: BrowserPreviewPayload;
  budget_stage: any;
  compositions_stage: any;
  final_result: any;
  correction_document: any;
};

export type BrowserPreviewHandlers = {
  onPreview?: (payload: BrowserPreviewPayload) => void | Promise<void>;
};

export function createDownload(filename: string, data: string) {
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

function appendQueryParam(url: string, key: string, value?: string): string {
  if (!value) return url;
  const joiner = url.includes('?') ? '&' : '?';
  return `${url}${joiner}${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`;
}

function validateOptions(options: Omit<BrowserParseOptions, 'filename' | 'content_type'>) {
  const required = ['orcamento_inicio', 'orcamento_fim', 'composicoes_inicio', 'composicoes_fim'] as const;
  for (const field of required) {
    const value = options[field];
    if (!Number.isInteger(value)) {
      throw new Error(`Campo inválido: ${field} precisa ser inteiro.`);
    }
  }
}

function optionsToLovablePayload(file: File, options: Omit<BrowserParseOptions, 'filename' | 'content_type'>): LovablePayload {
  if ((options as any).ranges) {
    return {
      version: (options as any).version || RELEASE_VERSION,
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
    base_id: options.base_id || 'misto',
    filename: file.name,
    content_type: file.type || 'application/pdf',
    document: {
      filename: file.name,
      title: options.obra_nome || '',
    },
    ranges: {
      budget: { start: budgetStart, end: Number(options.orcamento_fim) },
      compositions: { start: compStart, end: Number(options.composicoes_fim) },
    },
    docling_seed_pages: {
      budget: (options as any).docling_seed_pages?.budget || (options as any).docling_seed_pages?.budget_header_page || budgetStart,
      composition: (options as any).docling_seed_pages?.composition || (options as any).docling_seed_pages?.composition_schema_page || compStart,
    },
    docling_seed_pdf_policy: {
      enabled: true,
      extract_in_pyodide: true,
      send_full_pdf_to_docling: false,
      allow_full_pdf_fallback: false,
      preserve_full_page: true,
      deduplicate_pages: true,
    },
    runtime: {
      mode: 'browser_only',
      strict_validation: !!options.strict_validation,
      profile: options.performance_profile || 'browser_robust',
    },
    output_options: (options as any).output_options || {
      include_tipo_in_final_json: false,
      include_summary_rows_raw: true,
      include_control_line_debug: false,
      include_docling_page_map: true,
    },
    performance: {
      profile: options.performance_profile || 'browser_robust',
      composition_text_fallback_mode: 'smart',
    },
    metadata_extraida_ia: options.metadata_extraida_ia || {},
    ai_hints: (options as any).ai_hints || {},
    tables: (options as any).tables || {},
    fixed_contract: (options as any).fixed_contract || {},
    parser_contract: (options as any).parser_contract || {
      contract_version: RELEASE_VERSION,
      docling_clean_payload_field: 'docling_clean_payload',
      tables_contract_field: 'tables',
      use_top_level_tables_as_table_hints: true,
      docling_is_primary_structure_source: true,
      preserve_ignored_columns_for_geometry: true,
      effective_bounds_rule: 'x0_to_next_physical_x0',
    },
  };
}

function workerRequest<T = any>(
  worker: Worker,
  type: string,
  payload: any,
  transfer: Transferable[] = [],
  onStatus?: (stage: string, detail: WorkerStatusDetail) => void,
  onPreview?: (payload: BrowserPreviewPayload) => void | Promise<void>,
): Promise<T> {
  return new Promise((resolve, reject) => {
    const onMessage = async (event: MessageEvent) => {
      const { type: msgType, stage, payload: msgPayload, ...rest } = event.data || {};
      if (msgType === 'status') {
        onStatus?.(stage, { stage, worker: 'parser', ...(rest as WorkerStatusDetail) });
        return;
      }
      if (msgType === 'preview') {
        onStatus?.('preview-ready', { stage: 'preview-ready', worker: 'parser', preview: msgPayload });
        try {
          await onPreview?.(msgPayload);
        } catch (error: any) {
          worker.removeEventListener('message', onMessage);
          reject(new Error(`Falha no handler de preview: ${error?.message || String(error)}`));
        }
        return;
      }
      if (msgType === 'result' || msgType === 'ready') {
        worker.removeEventListener('message', onMessage);
        resolve((msgType === 'ready' ? undefined : msgPayload) as T);
        return;
      }
      if (msgType === 'state') {
        onStatus?.('state', { stage: 'state', worker: 'parser', statePayload: msgPayload });
        return;
      }
      if (msgType === 'error') {
        worker.removeEventListener('message', onMessage);
        const err = new Error(msgPayload?.message || 'Falha no worker do parser.');
        (err as any).code = msgPayload?.code;
        (err as any).detail = msgPayload?.detail;
        reject(err);
      }
    };
    worker.addEventListener('message', onMessage);
    worker.postMessage({ type, payload }, transfer);
  });
}

export class ApiPdfBrowserClient {
  private initOptions: WorkerInitOptions;
  private statusHandler?: (stage: string, detail: WorkerStatusDetail) => void;
  private worker!: Worker;
  private readyPromise!: Promise<void>;

  constructor(options: WorkerInitOptions = {}, onStatus?: (stage: string, detail: WorkerStatusDetail) => void) {
    this.initOptions = options;
    this.statusHandler = onStatus;
    this.createWorker();
  }

  private createOneWorker(): Worker {
    let workerUrl = this.initOptions.workerUrl || '/browser/pyodide/pyodide-parser-worker.js';
    workerUrl = appendQueryParam(workerUrl, 'v', this.initOptions.versionTag || RELEASE_VERSION);
    workerUrl = appendQueryParam(workerUrl, 'cb', this.initOptions.cacheBust || '');
    return new Worker(workerUrl, { type: 'classic' });
  }

  private createWorker() {
    this.worker = this.createOneWorker();
    this.readyPromise = workerRequest(this.worker, 'init', this.initOptions, [], this.statusHandler).then(() => undefined);
  }

  async ready(): Promise<void> {
    return this.readyPromise;
  }

  private async runFileTask(file: File, options: Omit<BrowserParseOptions, 'filename' | 'content_type'>, type: 'parse' | 'parse-base' | 'parse-budget' | 'parse-compositions'): Promise<any> {
    validateOptions(options);
    await this.ready();
    const buffer = await file.arrayBuffer();
    const payloadOptions = {
      base_id: options.base_id || 'misto',
      performance_profile: options.performance_profile || 'default',
      ...options,
      filename: file.name,
      content_type: file.type || 'application/pdf',
    };
    return workerRequest(this.worker, type, { buffer, options: payloadOptions }, [buffer], this.statusHandler);
  }

  /** @deprecated Use parseBase() or runLovableFlow(). */
  async parse(file: File, options: Omit<BrowserParseOptions, 'filename' | 'content_type'>): Promise<any> {
    return this.parseBase(file, options);
  }

  async parseBase(file: File, options: Omit<BrowserParseOptions, 'filename' | 'content_type'>): Promise<any> {
    return this.runFileTask(file, options, 'parse-base');
  }

  async parseBudgetStage(file: File, options: Omit<BrowserParseOptions, 'filename' | 'content_type'>): Promise<any> {
    return this.runFileTask(file, options, 'parse-budget');
  }

  async parseCompositionsStage(file: File, options: Omit<BrowserParseOptions, 'filename' | 'content_type'>): Promise<any> {
    return this.runFileTask(file, options, 'parse-compositions');
  }

  async runDoclingOnly(file: File, initialPayload: LovablePayload): Promise<any> {
    await this.ready();
    const buffer = await file.arrayBuffer();
    const payload = {
      buffer,
      payload: { version: initialPayload.version || RELEASE_VERSION, ...initialPayload },
      filename: file.name,
      contentType: file.type || 'application/pdf',
      doclingEndpoint: this.initOptions.doclingEndpoint || initialPayload?.docling_api_url,
      doclingApiKey: this.initOptions.doclingApiKey || initialPayload?.docling_api_key || '',
      doclingApiKeyHeader: this.initOptions.doclingApiKeyHeader || initialPayload?.docling_api_key_header || 'x-api-key',
      doclingTimeoutMs: this.initOptions.doclingTimeoutMs || initialPayload?.docling_timeout_ms || 120000,
      normalizerApiKey: this.initOptions.normalizerApiKey || initialPayload?.normalizer_api_key || '',
      normalizerApiKeyHeader: this.initOptions.normalizerApiKeyHeader || initialPayload?.normalizer_api_key_header || 'x-api-key',
      normalizerTimeoutMs: this.initOptions.normalizerTimeoutMs || initialPayload?.normalizer_timeout_ms || 90000,
      allowRelativeDoclingEndpoint: !!(this.initOptions.allowRelativeDoclingEndpoint || initialPayload?.allow_relative_docling_endpoint),
      production: !!(this.initOptions.production || initialPayload?.production),
    };
    return workerRequest<any>(this.worker, 'docling-only', payload, [buffer], this.statusHandler);
  }

  async runLovableFlow(file: File, initialPayload: LovablePayload, handlers: BrowserPreviewHandlers = {}): Promise<LovableFlowResult> {
    await this.ready();
    const buffer = await file.arrayBuffer();
    const payload = {
      buffer,
      payload: {
        version: initialPayload.version || RELEASE_VERSION,
        ...initialPayload,
      },
      filename: file.name,
      contentType: file.type || 'application/pdf',
      doclingEndpoint: this.initOptions.doclingEndpoint || initialPayload?.docling_api_url,
      doclingApiKey: this.initOptions.doclingApiKey || initialPayload?.docling_api_key || '',
      doclingApiKeyHeader: this.initOptions.doclingApiKeyHeader || initialPayload?.docling_api_key_header || 'x-api-key',
      doclingTimeoutMs: this.initOptions.doclingTimeoutMs || initialPayload?.docling_timeout_ms || 120000,
      normalizerApiKey: this.initOptions.normalizerApiKey || initialPayload?.normalizer_api_key || '',
      normalizerApiKeyHeader: this.initOptions.normalizerApiKeyHeader || initialPayload?.normalizer_api_key_header || 'x-api-key',
      normalizerTimeoutMs: this.initOptions.normalizerTimeoutMs || initialPayload?.normalizer_timeout_ms || 90000,
      allowRelativeDoclingEndpoint: !!(this.initOptions.allowRelativeDoclingEndpoint || initialPayload?.allow_relative_docling_endpoint),
      production: !!(this.initOptions.production || initialPayload?.production),
    };
    return workerRequest<LovableFlowResult>(this.worker, 'lovable-flow', payload, [buffer], this.statusHandler, handlers.onPreview);
  }

  async parseWithPreview(
    file: File,
    options: Omit<BrowserParseOptions, 'filename' | 'content_type'> | LovablePayload,
    handlers: BrowserPreviewHandlers = {},
  ): Promise<{ preview: BrowserPreviewPayload; final: any; budgetStage: any; compositionsStage: any; flow: LovableFlowResult; }> {
    const payload = optionsToLovablePayload(file, options as any);
    const flow = await this.runLovableFlow(file, payload, handlers);
    return {
      preview: flow.budget_preview,
      final: flow.final_result,
      budgetStage: flow.budget_stage,
      compositionsStage: flow.compositions_stage,
      flow,
    };
  }

  async mergeStages(budgetPayload: any, compositionsPayload: any, options: Omit<BrowserParseOptions, 'filename' | 'content_type'>): Promise<any> {
    validateOptions(options);
    await this.ready();
    return workerRequest(
      this.worker,
      'merge',
      {
        budget: budgetPayload,
        compositions: compositionsPayload,
        options: {
          base_id: options.base_id || 'misto',
          performance_profile: options.performance_profile || 'default',
          ...options,
          filename: 'upload.pdf',
          content_type: 'application/pdf',
        },
      },
      [],
      this.statusHandler,
    );
  }

  async getState(): Promise<any> {
    await this.ready();
    return workerRequest(this.worker, 'get-state', {}, [], this.statusHandler);
  }

  reset(): void {
    this.worker.terminate();
    this.createWorker();
  }

  cancelCurrent(): void {
    this.reset();
  }

  terminate(): void {
    this.worker.terminate();
  }
}
