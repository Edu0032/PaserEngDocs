# Relatório de testes — v61.0.32

Comandos executados no monorepo final extraído:

```bash
PYTHONPATH=parser_browser pytest -q
python -m compileall -q parser_browser/app api_docling/app
node --check parser_browser/browser/pyodide/pyodide-parser-worker.js
node --check parser_browser/browser/demo/pyodide/pyodide-parser-worker.js
node --check parser_browser/browser/demo/api-pdf-browser.js
python tools/quality_safety_scan.py .
PYTHONPATH=api_docling python - <<'PY'
from fastapi.testclient import TestClient
from app.main import app
client=TestClient(app)
payload={
  'document': {'filename':'x.pdf'},
  'ranges': {'budget': {'start':2,'end':4}, 'compositions': {'start':9,'end':10}},
  'seed_pages': {'budget':2,'composition':9},
  'docling_api_url':'http://x',
  'tables': {'budget': {'observed_headers':[{'text':'CÓDIGO','canonical':'codigo','first_row_text':'74209/001'}]}}
}
r=client.post('/docling/validate-payload', json=payload)
assert r.status_code == 200
assert r.json()['payload_usage']['tables']['budget']['canonical_mapping_used'] is True
assert r.json()['payload_usage']['tables']['budget']['first_row_samples_used'] is True
PY
```

Resultado:

```text
74 passed
compileall OK
node --check OK
quality_safety_scan OK
/docling/validate-payload OK
```

Testes novos adicionados:

- payload usage + split document/runtime;
- cache key estável;
- calibração Docling + PyMuPDF profile;
- reparse seletivo por campo fraco;
- métrica por campo;
- debug overlay para Lovable.
