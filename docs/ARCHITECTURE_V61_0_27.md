# Arquitetura v61.0.27 — hardening do fluxo existente

Esta versão não muda a regra central do projeto: **SICRO é exclusivo do motor SICRO v20**. O parser principal apenas chama o motor nativo, recebe o contrato limpo e faz adaptação não destrutiva para o JSON final.

## Fronteiras de responsabilidade

- `parser_browser/app/sicro_only/*`: extração e validação SICRO v20.
- `parser_browser/app/parser/sicro_native_bridge.py`: adaptação não destrutiva do resultado SICRO para `Composicoes`.
- `parser_browser/app/parser/compositions.py`: fluxo legado SINAPI-like/PRÓPRIO; não deve reinterpretar SICRO final.
- `parser_browser/app/normalizer/field_recovery.py`: recuperação local profile-aware para orçamento e SINAPI-like.
- `api_docling/app/api.py`: API seed-only para estruturar tabelas; não recebe regras fixas do parser como payload operacional.

## Payload público

A IA/Lovable continua devendo associar header visual do PDF ao canônico usado no código. Esse vínculo é documento-específico e deve ir no payload. Regexes, schemas fixos, tolerâncias, políticas de execução e heurísticas universais devem ficar em `base_config`.

## Testes de proteção

A versão adiciona scanner contra caracteres invisíveis em regex e contra regexes rígidos de profissão/serviço no código de aplicação.
