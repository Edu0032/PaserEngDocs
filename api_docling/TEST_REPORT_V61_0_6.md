# Test report — v61.0.11-sicro-section-engine-and-span-fix

## Objetivo da versão

Garantir que os patches retornados pela API Normalizer Recovery sejam realmente aplicados ao `final_result`, verificados no próprio JSON final e usados para recalcular o `correction_document` final antes de entregar ao Lovable.

## Testes executados

```bash
python -m compileall -q app

node --check browser/pyodide/pyodide-parser-worker.js
node --check browser/demo/pyodide/pyodide-parser-worker.js
node --check browser/demo/api-pdf-browser.js

PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q \
  tests/test_smoke.py \
  tests/test_tipo_column_collection.py \
  tests/test_v60_docling_column_map_and_contract.py \
  tests/test_v61_normalizer_api.py \
  tests/test_v61_targeted_recovery.py \
  tests/test_v61_patch_commit.py -q
```

Resultado: **18 passed**.

## Teste funcional adicional com o PDF DERACRE

Foi gerado um mini-PDF com as páginas problemáticas `[18, 66, 78]` do PDF de teste e a função `recover_fields` da API Normalizer foi executada com os alvos vindos do correction document/final anterior.

Resultado:

- patches retornados: 6
- unresolved: 0
- patches committed no `final_result`: 6
- patches failed: 0
- `correction_document.resumo.total_registros_com_erro`: 0
- `total_divergencias_matematicas`: 0
- `total_blocos_com_campos_vazios`: 0

## Validações específicas

- `CADM01|PRÓPRIO > composicoes_auxiliares > 90777.descricao` passou de vazio para `ENGENHEIRO CIVIL DE OBRA JUNIOR COM ENCARGOS COMPLEMENTARES`.
- `95402|SINAPI.principal.descricao` foi completada.
- `90777|SINAPI.principal.descricao` foi preenchida.
- Insumo `00002706|SINAPI` foi preenchido nas páginas alvo.
- O commit do patch exige verificação pós-escrita (`verified_after_write=true`).
- Patch com identidade incompatível é rejeitado e não altera o JSON.

## Observações

- O cache da API Docling agora pode ser ignorado por execução com `bypass_cache=true`.
- A API Docling também expõe `/admin/cache/clear` e `/admin/cache/stats` para testes locais/Render.
- O HTML possui checkboxes para ignorar e limpar cache antes da execução.
