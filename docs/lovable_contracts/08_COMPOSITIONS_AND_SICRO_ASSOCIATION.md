# 08 — Composições SINAPI-like, próprias e SICRO

SINAPI-like, próprios e SICRO seguem o mesmo objetivo: relacionar orçamento, composições principais, auxiliares e insumos por código+banco, item e evidência matemática.

## SINAPI-like/próprios

- `principais`: composições associáveis a itens do orçamento ou com item próprio.
- `composicoes_auxiliares`: linhas internas referenciadas dentro de uma principal.
- `insumos`: materiais, mão de obra, equipamentos etc.
- `auxiliares_globais`: composições auxiliares detalhadas fora de uma principal.

Não copie quantidade do orçamento para composição. A quantidade do orçamento é quantidade da obra; a composição geralmente é base 1.

## SICRO

SICRO tem estrutura de seções, mas a associação geral continua por item e código+banco.

- SICRO com item próprio: `principal`;
- sem item próprio: `auxiliar_global`.

A seção D é especial: ela referencia atividades auxiliares. Se o preço de uma auxiliar referenciada na seção D muda, o custo da composição principal que referencia essa auxiliar também deve ser impactado pela cadeia.

Se uma composição SICRO tem item mas não aparece no orçamento sintético, o parser não reclassifica. Ele registra revisão para o Lovable.
