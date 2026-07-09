# Changelog — v61.0.33

`v61.0.39-deep-area-sweep-iterative-closure`

## Selective Field Reparse Executor

- Adicionado executor de reprocessamento seletivo por campo fraco.
- A primeira correção agora prioriza cruzamento seguro orçamento sintético ↔ composições antes da recuperação pesada por PDF.
- O executor gera candidatos por `codigo|banco`, usa Evidence Graph/descrições confirmadas e aplica patch somente quando a evidência é superior ao valor atual.
- Campos fracos sem candidato seguro são enviados como alvos cirúrgicos para o targeted recovery local.
- O worker passa a coletar alvos vindos de `meta.performance.selective_field_reparse_executor.targets`.
- O HTML de testes ganhou aba **Reparse seletivo** para inspecionar patches, rejeições e alvos.

## Segurança

- Candidatos poluídos continuam em quarentena e não podem virar descrição confirmada.
- Candidato longo não substitui valor atual limpo apenas por conter mais texto.
- Correções aceitas são registradas em `meta.performance.selective_field_reparse_executor.applied`.
