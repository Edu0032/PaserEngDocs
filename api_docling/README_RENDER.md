# Render deploy — API Docling v61.0.36

Esta pasta é a única que deve ser hospedada no Render para o endpoint Docling.

## Campos no Render

Root Directory, se o repositório for monorepo:

```text
api_docling
```

Build Command:

```text
pip install -r requirements-server.txt
```

Start Command:

```text
gunicorn app.main:app -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT --workers 1 --threads 1 --timeout 180 --graceful-timeout 180 --log-level info
```

Health Check Path:

```text
/health
```

## Variáveis de ambiente

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

## Endpoints

```text
GET  /health
GET  /healthz
GET  /docs
POST /docling/validate-payload
POST /docling/extract-table-structure
```

## Correção v61.0.36

- Corrige CORS/preflight `OPTIONS` para chamadas do Lovable com `x-api-key`.
- Aceita `DOCLING_TIMEOUT_SECONDS=120` como alias oficial usado no Render.
- Reusa o `DocumentConverter` do Docling entre requisições do mesmo worker para reduzir overhead.
- Mantém OCR desligado por padrão.
- Mantém cache semântico estável com limite de entradas.
