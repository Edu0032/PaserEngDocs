# Render — API Docling v61.0.11

Start command:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Endpoint principal: `POST /docling/extract-table-structure`.

Cache para testes: `POST /admin/cache/clear` e `GET /admin/cache/stats`.

A API aceita somente mini-PDF seed. O PDF completo deve ficar no browser/Pyodide.
