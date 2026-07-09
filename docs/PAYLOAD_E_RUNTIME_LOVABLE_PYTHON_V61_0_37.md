# Payload e Runtime — o que o Lovable entrega ao Python/worker

## Regra central

O Lovable entrega ao worker dois objetos separados:

```json
{
  "runtime": {},
  "payload": {}
}
```

- `runtime` configura como o worker chama a API Docling.
- `payload` descreve semanticamente o documento.

O Lovable não deve chamar a API Docling diretamente. Quem chama a API é o worker/Python/Pyodide.

## Runtime

```json
{
  "docling_api_url": "https://SUA-URL/docling/extract-table-structure",
  "docling_api_key": "SUA_CHAVE",
  "docling_api_key_header": "x-api-key",
  "docling_timeout_ms": 240000,
  "normalizer_mode": "local_pyodide",
  "performance_profile": "browser_robust",
  "table_structure_enabled": true,
  "normalizer_targeted_recovery_enabled": true,
  "targeted_recovery_max_pages_per_batch": 12
}
```

## Payload semântico

O payload deve conter apenas:

- `version`;
- `base_id`;
- `document`;
- `ranges`;
- `seed_pages`;
- `document_hints`;
- `tables`;
- `user_base_config`.

Não colocar no payload:

- URL da API;
- chave da API;
- timeout;
- normalizer URL;
- regex universais;
- contratos fixos;
- schemas globais.

## Exemplos

- `examples/payloads/payload_empty_v61_0_37.json`
- `examples/payloads/payload_filled_v61_0_37.json`
- `examples/payloads/runtime_worker_local_tunnel_v61_0_37.json`
