# 11 — Exemplos de fluxo completo

## Exemplo mínimo de payload

Veja `examples/lovable/minimal_payload.json`.

## Exemplo de runtime options

Veja `examples/lovable/runtime_options.local.json`.

## Exemplo de overlays

Veja:

- `examples/lovable/admin_config_overlay.example.json`
- `examples/lovable/user_config_overlay.example.json`

## Validação CLI

```bash
PYTHONPATH=parser_browser python tools/validate_lovable_contract.py \
  --payload examples/lovable/minimal_payload.json \
  --final final_result.json
```
