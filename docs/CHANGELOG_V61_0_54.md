# v61.0.54 — Coverage, Config and SICRO Audit

## Objetivo

A v61.0.54 aumenta a confiança da extração verificando também **cobertura**: não basta validar as linhas já extraídas; o parser agora relata se linhas físicas candidatas do PDF foram mapeadas no JSON final e separa melhor o que é falha de extração, evidência auxiliar bruta ou revisão humana.

## Principais mudanças

- Novo `extraction_coverage.py`.
- Novo `analise_orcamentaria.extraction_coverage_report`.
- Novo resumo de cobertura dentro de `documento_evidencias.extraction_coverage_report`.
- Auditoria de cobertura SICRO sem alterar o motor `sicro_only`.
- Relatório `analise_orcamentaria.base_config_layering` explicando a dinâmica simples do base_config configurável.
- HTML demo atualizado com abas **Cobertura** e **Base config**.
- Export Pyodide novo:
  - `build_extraction_coverage_report_json`
  - `build_base_config_layering_report_json`

## Regra SICRO preservada

- Tem item próprio → principal.
- Não tem item próprio → auxiliar global.
- Tem item, mas não aparece no orçamento sintético → revisão Lovable, não reclassificação automática.
- Item SICRO no orçamento sem composição encontrada → revisão Lovable.

## Base config configurável

O ZIP contém o base_config default somente leitura. O Lovable deve persistir configurações fora do ZIP e enviá-las a cada execução:

1. `embedded_base_config` do ZIP.
2. `admin_base_config_overlay` ou cópia completa do admin sobrescreve o default.
3. `user_base_config_overlay` sobrescreve o admin apenas em configurações de usuário/projeto.

O parser faz merge em memória. O ZIP não é modificado.
