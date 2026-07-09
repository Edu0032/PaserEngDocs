# ParserOrca — v61.0.75-correction-output-contract-and-review-index

Versão focada somente em **saída, contrato de revisão e documento de correção**. O motor de extração, o motor SICRO e as políticas de cálculo não foram alterados nesta versão.

## Objetivo da v61.0.75

- Manter o JSON final fiel ao PDF.
- Organizar problemas, incoerências e pendências em um `documento_correcao` simples, curto e acionável.
- Garantir que cada problema tenha, quando disponível: local, página, intervalo de páginas, composição, item, código, banco, campo, valor atual, valor do PDF, crop hint e referência de evidência.
- Mover hipóteses, logs longos e tentativas internas para `analise_orcamentaria.debug_recovery`.
- Documentar o contrato para a janela dinâmica do Lovable abrir página/recorte enquanto o usuário edita.

## Contratos principais

- `final_result`: valores públicos finais, com totais de metas/submetas inline (`custo_total`) e itens folha com `custo_parcial`.
- `documento_correcao.resumo_final_curto`: resumo humano/acionável para Lovable.
- `documento_correcao.problemas`: índice plano de problemas e revisões.
- `documento_correcao.problemas_por_categoria`: agrupamento por origem do problema.
- `documento_evidencias`: evidências, índices e materiais auxiliares.
- `analise_orcamentaria.debug_recovery`: debug pesado, hipóteses e rastros internos.

Leia também: `docs/lovable_contracts/13_CORRECTION_DOCUMENT_UI_REVIEW_CONTRACT.md`.
