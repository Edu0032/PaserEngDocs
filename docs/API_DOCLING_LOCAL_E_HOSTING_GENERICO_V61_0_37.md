# API Docling — Local, túnel e hospedagem genérica

## Local

```powershell
cd api_docling
.\.venv\Scripts\Activate.ps1
$env:API_PDF_ENV="development"
$env:API_PDF_DOCS_ENABLED="true"
$env:API_PDF_CORS_ALLOW_ORIGINS="*"
$env:DOCLING_OCR_ENABLED="false"
$env:DOCLING_TIMEOUT_SECONDS="120"
$env:API_PDF_REQUIRE_KEY="true"
$env:API_PDF_API_KEY_HEADER="x-api-key"
$env:API_PDF_API_KEY="parser-orca-docling-2026-chave-secreta"
uvicorn app.main:app --host 0.0.0.0 --port 8000 --timeout-keep-alive 240
```

## Cloudflare Tunnel

```powershell
cloudflared tunnel --url http://127.0.0.1:8000
```

No Lovable/runtime, usar:

```json
{
  "docling_api_url": "https://SUA-URL.trycloudflare.com/docling/extract-table-structure"
}
```

## Hospedagem genérica

A API é um app FastAPI. Com Gunicorn:

```bash
gunicorn app.main:app -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT --workers 1 --threads 1 --timeout 240 --graceful-timeout 240 --log-level info
```

OCR deve ficar desabilitado nos testes:

```env
DOCLING_OCR_ENABLED=false
```
