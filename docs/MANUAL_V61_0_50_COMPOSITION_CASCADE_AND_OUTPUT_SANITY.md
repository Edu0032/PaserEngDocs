# Manual v61.0.50 — Composition Cascade and Output Sanity

## O que mudou
A v61.0.50 reforça a cascata de fechamento das composições principais. Quando uma composição principal está com `quant`, `valor_unit` ou `total` vazios, o parser usa a soma das linhas internas e a relação com o orçamento sintético para buscar um fechamento seguro.

## Regra crítica de quantidade
Quantidades são contextuais:

- orçamento sintético: quantidade da obra;
- composição principal: quantidade-base da composição, normalmente `1`;
- auxiliar dentro de principal: consumo contextual naquela composição;
- auxiliar global: composição auxiliar em base própria.

O parser **não copia** quantidade do orçamento para a composição, nem quantidade da auxiliar global para a auxiliar contextual.

## Como o Lovable deve consumir
- `final_result`: dados limpos extraídos.
- `documento_correcao`: problemas, inconsistências, ausência de referência no sintético e ações humanas.
- `documento_evidencias`: provas usadas para fechar valores.
- `documento_enriquecimento`: sugestões para base_config/admin; não aplicar automaticamente.

## SICRO
A regra continua a mesma:

- SICRO com item próprio: principal;
- SICRO sem item: auxiliar global.

Se uma composição SICRO tem item, mas não aparece no orçamento sintético, o parser deve apenas registrar essa inconsistência para o Lovable revisar. Ele não deve reclassificar automaticamente.

## Payload × base_config
O payload do Lovable deve conter apenas dados do documento: ranges, seed pages, headers observados, samples e contexto textual específico do PDF.

Configurações de API, cache, timeout, normalizer, recovery, políticas internas e runtime pertencem ao `base_config`/admin ou às opções de inicialização do worker.
