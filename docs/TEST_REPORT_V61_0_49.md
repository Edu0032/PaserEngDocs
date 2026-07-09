# Test Report — v61.0.49

## Validações executadas

```txt
python -m compileall -q parser_browser/app api_docling/app
OK

PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=parser_browser pytest -q
155 passed

PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=api_docling pytest -q api_docling/tests
4 passed

node --check parser_browser/browser/pyodide/pyodide-parser-worker.js
OK

node --check parser_browser/browser/demo/pyodide/pyodide-parser-worker.js
OK

node --check parser_browser/browser/demo/api-pdf-browser.js
OK

node --check extracted demo index module
OK

python tools/quality_safety_scan.py .
OK

zip -T monorepo
OK
zip -T bundle Lovable
OK
```

## Testes novos

Arquivo:

```txt
tests/test_v61_0_49_browser_base_config_contract.py
```

Cobertura:

- `base_config` declara que o payload é somente documental.
- HTML demo não injeta runtime/API/cache/timeout no payload.
- `api_pdf_pyodide_src.zip` contém `db/base_config.json` e `db/base_config.d/95_payload_runtime_boundary.json`.
- HTML demo expõe abas de Evidências e Enriquecimento.

## Bug corrigido

Erro anterior:

```txt
Nenhum arquivo de configuração encontrado em /home/pyodide/db/base_config.json
```

Causa: o ZIP do Pyodide continha `app/`, mas não continha `db/`.

Correção: o source archive agora empacota `app/` e `db/`.
