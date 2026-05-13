# Relatório de testes — v61.0.27

## Comandos executados

```text
python -m compileall -q parser_browser/app api_docling/app
PYTHONPATH=parser_browser pytest -q
PYTHONPATH=api_docling python - <<'PY'
from fastapi.testclient import TestClient
from app.api import create_app
app = create_app()
client = TestClient(app)
# valida /docling/validate-payload
PY
node --check parser_browser/browser/pyodide/pyodide-parser-worker.js
node --check parser_browser/browser/demo/pyodide/pyodide-parser-worker.js
zip -T api_pdf_v61_0_27_monorepo_hardening_existing_flow.zip
zip -T lovable_browser_bundle_v61_0_27.zip
```

## Resultado

```text
59 passed
compileall OK
/docling/validate-payload OK
node --check OK
zip integrity OK
```

## Casos cobertos

- Regex SICRO sem caractere invisível/backspace.
- Scanner anti-hardcode/anti-caractere invisível.
- API Docling sem serviço normalizer no Render.
- Requirements da API sem auto-referência.
- Payload Docling preservando header observado ↔ canônico e sample da primeira linha.
- Payload Docling removendo chaves fixas de processamento.
- Metadata `payload_usage` da API.
- Budget math validator como gatilho de rechecagem, não erro fatal.
- Contrato de payload espelhado entre browser e API.
