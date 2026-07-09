# v61.0.53 — Review Reduction and Semantic Consistency

## Objetivo

Reduzir revisões recomendadas sem esconder problemas reais, melhorar a consistência semântica dos resultados, adicionar confiança por entidade e deixar claro quando uma divergência matemática de composição é erro de extração, falta de evidência ou provável erro humano do PDF.

## Principais mudanças

- Novo módulo `semantic_consistency.py`.
- Remoção auditável de ruído textual seguro em descrições, como marcador final `=>`.
- Diagnóstico de composições cuja soma dos componentes não fecha com o total da principal.
- Busca de linhas candidatas que explicam divergência matemática antes de classificar como possível erro humano.
- Relatório de confiança por entidade em `analise_orcamentaria.entity_confidence_report`.
- Documento de correção mais seletivo: revisões fracas viram aviso ou diagnóstico ignorado.
- Targeted recovery reduz ruído de descrições já informativas quando não há candidato melhor.
- HTML demo ganhou abas `Confiança entidades` e `Revisões Lovable`.

## Política mantida

- O parser extrai o que está no PDF e valida matematicamente.
- Se todos os valores foram extraídos corretamente e a composição não fecha, o caso deve ser apresentado como provável erro humano/documental.
- Quantidade do orçamento não sobrescreve quantidade da composição.
- Quantidade da auxiliar global não sobrescreve consumo contextual dentro da principal.
- SICRO continua com motor separado e regra: com item = principal; sem item = auxiliar global.
