# Changelog — v61.0.36-api-docling-cors-performance-hardening

## Correções críticas

1. **CORS/preflight corrigido**
   - Em produção, a API não limpa mais `allow_origins=['*']` para `[]`.
   - O preflight `OPTIONS /docling/extract-table-structure` agora responde corretamente para chamadas do navegador/Lovable com `x-api-key`.
   - Adicionado fallback `OPTIONS /{full_path:path}` para probes simples.

2. **Timeout Render corrigido**
   - A API agora aceita `DOCLING_TIMEOUT_SECONDS=120`, além de `API_PDF_DOCLING_TIMEOUT_SECONDS`.
   - `DoclingClient` também lê o mesmo alias.

3. **Deploy Render mais robusto**
   - `requirements-server.txt` inclui `gunicorn`.
   - `requirements.txt` não é mais autorreferenciado.
   - `render.yaml` usa Gunicorn + Uvicorn Worker com `--timeout 180`.
   - Adicionado `/healthz` além de `/health`.

## Eficiência

1. **Cache de converter Docling**
   - O `DocumentConverter` passa a ser cacheado por configuração (`table_mode`, `do_cell_matching`, `do_ocr`).
   - Isso reduz overhead em chamadas subsequentes no mesmo worker sem alterar qualidade da extração.

2. **Cache semântico limitado**
   - O cache de resposta Docling continua usando chave semântica estável.
   - Adicionado limite por worker via `API_PDF_DOCLING_CACHE_MAX_ENTRIES`, padrão `32`.

## Testes

- `compileall` em `api_docling/app`.
- Testes automatizados de CORS, timeout, API key e health.
- Teste manual com `TestClient` simulando o preflight real do navegador.
