# 01 — Contrato de input

O input lógico do parser é composto por quatro blocos separados.

## `document_payload`

Carrega somente informações do documento PDF atual:

```json
{
  "document": {"filename": "orcamento.pdf", "page_count": 148, "title": "..."},
  "ranges": {"budget": {"start": 2, "end": 4}, "compositions": {"start": 9, "end": 139}},
  "docling_seed_pages": {"budget": 2, "composition": 9},
  "tables": {
    "budget": {"observed_headers": [{"text": "CÓDIGO", "canonical": "codigo", "first_row_text": "12345/001"}]},
    "composition": {"observed_headers": [{"text": "Valor Unit", "canonical": "valor_unit"}]}
  }
}
```

Não coloque no `document_payload`: endpoint, timeout, API key, cache, políticas internas, runtime ou quality gate.

## `runtime_options`

Configura a execução atual:

```json
{
  "docling_endpoint": "http://127.0.0.1:8000/docling/extract-table-structure",
  "docling_timeout_ms": 240000,
  "clear_cache_before_run": false,
  "bypass_docling_cache": false,
  "targeted_recovery_max_pages_per_batch": 12
}
```

## `admin_config_overlay`

Configuração persistente do admin/plataforma. Pode ser overlay parcial ou uma cópia completa modificada do base_config padrão.

## `user_config_overlay`

Configuração persistente do usuário/projeto. Exemplo: banco personalizado, aliases locais, unidades aceitas naquele projeto.
