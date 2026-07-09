# API Docling

## Função

A API Docling identifica a estrutura de tabelas em páginas selecionadas do PDF. O parser no navegador usa essa resposta para interpretar colunas, linhas, cabeçalhos e blocos relevantes.

## Endpoint principal

```text
POST /docling/extract-table-structure
```

## Endpoints auxiliares

```text
GET  /health
GET  /healthz
GET  /version
GET  /docs
GET  /docling/runtime
POST /docling/validate-payload
```

## Execução local

```bash
cd api_docling
pip install -r requirements-server.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

## Variáveis úteis

```env
API_PDF_ENV=development
API_PDF_DOCS_ENABLED=true
API_PDF_CORS_ALLOW_ORIGINS=*
DOCLING_OCR_ENABLED=false
DOCLING_TIMEOUT_SECONDS=120
API_PDF_REQUIRE_KEY=false
```

## Papel no fluxo

A API não processa o documento completo. O navegador envia somente páginas ou recortes necessários para inferência de estrutura. O parser final continua no Pyodide/browser.
