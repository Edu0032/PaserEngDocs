# API Docling

API FastAPI usada pelo ParserOrca para obter estrutura de tabelas de páginas selecionadas de PDFs.

## Rodar localmente

```bash
pip install -r requirements-server.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

## Endpoints

```text
GET  /health
GET  /healthz
GET  /version
GET  /docs
GET  /docling/runtime
POST /docling/validate-payload
POST /docling/extract-table-structure
```

## Observação

A API não substitui o parser. Ela fornece estrutura tabular para o parser executado no navegador via Pyodide.
