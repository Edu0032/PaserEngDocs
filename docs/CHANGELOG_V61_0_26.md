# Changelog — v61.0.26

`v61.0.39-deep-area-sweep-iterative-closure`

## Foco

A versão v61.0.26 aumenta a taxa de acertos do orçamento sintético e das composições SINAPI-like com uma camada central de evidências, reparse seletivo por perfil e motor de hipóteses para fragmentos quebrados.

## Implementado

- Evidence Graph central por `codigo|banco`.
- Descrições confirmadas agora servem como evidência positiva e como bloqueio negativo contra anexação errada de fragmentos.
- Recheck por Evidence Graph aplicado ao orçamento sintético e às composições SINAPI-like antes do registry conservador.
- `document_learning_profile.selective_reparse_plan` com alvos fracos de orçamento e composição.
- Targeted recovery mantém hipóteses pontuadas na evidência dos patches.
- Payload Docling mais limpo: mantém header observado + canônico + samples de primeira linha, mas não envia chaves de transporte/API key/timeouts como corpo de processamento.
- Remoção de hardcode de palavras de serviço/profissão no detector JS de recovery; a decisão passa a usar perfil, tamanho, truncamento e Evidence Graph.
- Testes golden para Evidence Graph, reparse seletivo, payload Docling limpo e classificador código vs dinheiro.

## Mantido

- Adapter SICRO segue não destrutivo.
- Classificação SICRO continua: tem item = principal; sem item = auxiliar global.
- Códigos com `/`, `-`, ponto e letras continuam aceitos quando não são valores pt-BR.
