# Changelog — v61.0.24

`v61.0.39-deep-area-sweep-iterative-closure`

## Objetivo

Transformar a rechecagem SINAPI-like e do orçamento sintético em uma camada realmente orientada por perfil do documento, usando descrições confirmadas como âncoras positivas e negativas, e reforçando a recuperação local de linhas quebradas acima/abaixo com PyMuPDF.

## Principais mudanças

- Novo `BrokenLineRecoveryEngine` compartilhado em `app/parser/broken_line_recovery.py`.
- Rechecagem agora roda também no `orcamento_sintetico`, não apenas nas composições.
- Registry de descrições confirmadas por `codigo|banco`, cruzando orçamento sintético e composições.
- Descrições confirmadas são usadas para:
  - preencher descrições truncadas;
  - bloquear anexação de fragmentos em linhas que já estão completas;
  - reduzir possibilidades em linhas vizinhas quebradas.
- Targeted recovery local com PyMuPDF agora testa:
  - linha alvo isolada;
  - continuação para baixo;
  - fragmento acima + linha alvo;
  - fragmento acima + linha alvo + continuação abaixo.
- `collectTargetedRecoveryTargets()` agora percorre `composicoes.sinapi_like.principais` e `composicoes.sinapi_like.auxiliares_globais`.
- Worker envia `description_registry` para o normalizer local.
- Recovery agent aceita patches não-prefixados quando há evidência de fragmento acima e a descrição atual aparece como sequência interna do candidato.
- `document_learning_layer` separa bandas de coluna por família/tabela, evitando misturar `budget.descricao` com `composition.descricao`.
- Novo `CodeValueClassifier` aceita códigos SINAPI/PRÓPRIO com `.`, `/`, `-` e letras, sem confundir com dinheiro pt-BR.
- Correção do veto anti-poluição genérico para repetições como `Insumo Insumo Insumo` e `Material Material Material`.

## SICRO

O motor SICRO v20 continua autoritativo. Esta versão não altera a lógica SICRO central; mantém a política de adapter não destrutivo e concentra as mudanças na rechecagem de orçamento/SINAPI-like.
