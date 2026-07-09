# Changelog — v61.0.30

`v61.0.39-deep-area-sweep-iterative-closure`

## Foco

Versão combinada v29 + v30: camada de garantia final, recuperação segura V2 e uso mais real do perfil aprendido.

## Implementado

- Cross-table reconciliation reforçado como primeira correção: orçamento sintético ↔ composições, antes da rechecagem pesada.
- Reconcile bidirecional seguro: orçamento pode corrigir composição truncada, e composição pode corrigir orçamento truncado, apenas quando há compatibilidade forte.
- `PageLineGraph` para classificar linhas, barreiras, fragmentos soltos, linhas com valores financeiros e fronteiras de item/código.
- Targeted recovery com parâmetros mais rígidos:
  - prioriza `target_line_only` quando a linha atual já está boa;
  - não aceita hipótese longa por simples ganho de tamanho;
  - penaliza hipóteses `upward_target_downward_fragments`;
  - usa registro confirmado como bloqueio negativo;
  - usa barreiras de item/código/valor financeiro.
- Perfil aprendido (`document_learning_profile`) agora também pode fornecer bandas de colunas para o recovery quando `column_maps` não estiver presente.
- Quality/numeric guarantee reforçado: orçamento sintético também tem números públicos convertidos para string pt-BR.
- Quality Gate agora varre floats de forma recursiva em orçamento e composições.
- Worker envia `document_learning_profile` para o targeted recovery e adiciona alvos do `selective_reparse_plan`.
- Novos testes v61.0.30 cobrindo cross-table first pass, PageLineGraph, profile fallback, bloqueio do caso ANP 01 e formatação pública de orçamento.

## Mantido

- Processamento SICRO continua exclusivo do motor SICRO v20. A camada final apenas adapta, preserva e valida, sem reinterpretar o SICRO.
