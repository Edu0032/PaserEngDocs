# v61.0.55 — architecture-cleanup-and-output-schema-stability

## Objetivo

Consolidar a arquitetura de outputs do parser para o Lovable: cada documento agora tem papel, schema e caminho canônico claros. A versão não muda a regra de extração principal; ela torna a saída mais previsível, testável e fácil de consumir.

## Melhorias principais

- Novo `output_schema_stability.py`.
- `documento_correcao`, `documento_evidencias`, `documento_enriquecimento` e `analise_orcamentaria` recebem `schema_version=outputs.v1`.
- Novo `analise_orcamentaria.outputs_package_manifest` com nomes/caminhos canônicos dos outputs.
- Novo `analise_orcamentaria.lovable_operational_summary` com status operacional direto para UI.
- `painel_lovable` ficou mais completo, incluindo orçamento, composições, SICRO, cobertura e instrução de download dos outputs.
- `documento_enriquecimento` agora separa sugestões por confiança: alta confiança, para revisão e rejeitadas como ruído.
- `extraction_coverage_report` ganhou `family_breakdown` e política explícita para ruídos/itens não bloqueantes.
- `base_config_layering_report` ganhou política simples de conflitos e modelo efetivo de configuração.
- HTML demo atualizado para v61.0.55.

## Regra de consumo

O Lovable deve consumir:

1. `final_result` para popular o sistema.
2. `documento_correcao` para revisão humana e pendências.
3. `documento_evidencias` para provas técnicas.
4. `documento_enriquecimento` para sugestões de base_config/admin.
5. `analise_orcamentaria` para métricas, cobertura, schema e painéis.
