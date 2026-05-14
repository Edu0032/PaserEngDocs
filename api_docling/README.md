# API Docling — v61.0.36

API FastAPI para extração de estrutura de tabelas com Docling, usada pelo parser browser/Pyodide.

## Função da API

A API recebe **somente o mini-PDF seed** com as páginas necessárias para inferir estrutura de colunas. O PDF completo deve permanecer no browser/Pyodide.

Endpoint principal:

```text
POST /docling/extract-table-structure
```

## Deploy no Render

Consulte `README_RENDER.md`.

Resumo:

```text
Build Command: pip install -r requirements-server.txt
Start Command: gunicorn app.main:app -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT --workers 1 --threads 1 --timeout 180 --graceful-timeout 180 --log-level info
Health Check Path: /health
```

## Variáveis principais

```env
API_PDF_ENV=production
API_PDF_DOCS_ENABLED=true
API_PDF_CORS_ALLOW_ORIGINS=*
DOCLING_OCR_ENABLED=false
DOCLING_TIMEOUT_SECONDS=120
API_PDF_REQUIRE_KEY=true
API_PDF_API_KEY_HEADER=x-api-key
API_PDF_API_KEY=sua_chave_secreta
```

## Endpoints úteis

```text
GET /health
GET /healthz
GET /version
GET /docs
GET /docling/runtime
POST /docling/validate-payload
POST /docling/extract-table-structure
```

## Notas de performance

- OCR fica desligado por padrão.
- A API recusa PDFs com mais de 3 páginas no endpoint Docling.
- O `DocumentConverter` do Docling é reaproveitado no mesmo worker.
- Respostas são cacheadas por chave semântica estável quando `bypass_cache=false`.
