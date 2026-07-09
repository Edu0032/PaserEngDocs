# 04 — Runtime options

`runtime_options` não faz parte do documento. Ele controla a execução.

Campos comuns:

- `docling_endpoint`
- `docling_timeout_ms`
- `clear_cache_before_run`
- `bypass_docling_cache`
- `targeted_recovery_max_pages_per_batch`
- `normalizer_mode`

Se o usuário marcar “limpar cache”, o tempo do Docling pode subir, pois o cache será removido antes da execução.
