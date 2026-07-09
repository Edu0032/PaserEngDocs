# v61.0.49 — Browser Base Config Contract and Demo Refresh

## Objetivo

Corrigir a falha real do browser/Pyodide em que o parser carregava o código, mas não encontrava `db/base_config.json` dentro do runtime Pyodide. A versão também atualiza o HTML de testes para refletir o contrato correto:

- `base_config` guarda regras fixas, políticas internas, API, timeouts, cache, normalizer, targeted recovery e políticas de execução.
- `payload` guarda somente informações variáveis do documento: metadados, ranges, páginas seed, headers observados, canônicos, samples e hints do documento.
- `documento_enriquecimento` apenas sugere melhorias para revisão/admin; nunca altera `base_config` automaticamente.

## Correções

- O pacote `api_pdf_pyodide_src.zip` agora inclui:
  - `app/`
  - `db/base_config.json`
  - `db/base_config.d/*.json`
- `app.config.loader` agora procura `base_config` de forma robusta em ambiente local e Pyodide:
  - `parser_browser/db`
  - `./db`
  - `./parser_browser/db`
  - `/home/pyodide/db`
- O erro `Nenhum arquivo de configuração encontrado em /home/pyodide/db/base_config.json` deixa de ocorrer quando o bundle v49 é usado corretamente.

## HTML demo

- Atualizado para `v61.0.49`.
- Removidos campos de runtime do payload editável.
- Endpoint, API key, cache, timeout e lote do targeted recovery continuam na interface, mas são enviados como opções do worker, não como payload do documento.
- Adicionadas abas:
  - Evidências
  - Enriquecimento
- Adicionados logs específicos para:
  - `physical-evidence-index-started`
  - `physical-evidence-index-finished`
  - `output-documents-organized`

## Base Config

Novo fragmento:

```txt
db/base_config.d/95_payload_runtime_boundary.json
```

Ele registra explicitamente a fronteira entre payload documental e configuração de runtime/base_config.

## Compatibilidade

A API Docling permanece na versão `v61.0.36-api-docling-cors-performance-hardening`; esta versão altera o parser/browser/bundle Lovable.
