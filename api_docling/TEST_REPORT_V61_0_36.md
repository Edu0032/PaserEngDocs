# Test Report — v61.0.36-api-docling-cors-performance-hardening

## Comandos executados

```bash
python -m compileall -q api_docling/app
cd api_docling && PYTHONPATH=. pytest -q
```

Resultado:

```text
4 passed
compileall OK
```

## Testes manuais com TestClient

Ambiente usado:

```env
API_PDF_ENV=production
API_PDF_API_KEY=secret
API_PDF_CORS_ALLOW_ORIGINS=*
DOCLING_TIMEOUT_SECONDS=120
API_PDF_DOCS_ENABLED=true
```

Verificações:

```text
OPTIONS /docling/extract-table-structure => 200
Access-Control-Allow-Origin => *
GET /health => 200
GET /healthz => 200
GET /docs => 200
GET /docling/runtime sem x-api-key => 401
GET /docling/runtime com x-api-key => 200
settings.docling_timeout_seconds => 120
```

## O erro anterior resolvido

Antes:

```text
OPTIONS /docling/extract-table-structure HTTP/1.1 400
Failed to fetch
```

Depois:

```text
OPTIONS /docling/extract-table-structure HTTP/1.1 200
```
