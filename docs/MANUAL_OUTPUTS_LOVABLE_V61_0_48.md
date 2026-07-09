# Manual Lovable — Outputs do Parser v61.0.48

Este manual explica como o Lovable deve consumir os outputs gerados pelo parser.

## 1. Visão geral dos outputs

A v61.0.48 entrega quatro documentos principais dentro do JSON de resposta:

```txt
final_result
├── orcamento_sintetico
├── composicoes
├── analise_orcamentaria
├── documento_correcao
├── documento_evidencias
└── documento_enriquecimento
```

Além disso, no retorno do worker Lovable, os mesmos documentos principais também são expostos como atalhos:

```txt
correction_document = final_result.documento_correcao
evidence_document = final_result.documento_evidencias
enrichment_document = final_result.documento_enriquecimento
```

## 2. final_result

É o JSON principal que deve alimentar o sistema.

Contém:

- `orcamento_sintetico`: metas, submetas e itens folha.
- `composicoes.sinapi_like`: composições principais, auxiliares globais e linhas internas.
- `composicoes.sicro`: composições SICRO vindas do motor SICRO autoritativo.
- `analise_orcamentaria`: resumos técnicos, contratos de output, métricas e status.

O Lovable deve usar este documento para persistir os dados extraídos no sistema.

## 3. documento_correcao

É o documento de revisão, auditoria e resolução de problemas.

Use para:

- montar fila de revisão humana;
- exibir campos vazios;
- exibir matemática que não fechou;
- mostrar candidatos rejeitados;
- mostrar reparos aplicados;
- mostrar suspeitas de erro humano no PDF;
- orientar ações de correção.

Estruturas importantes:

```txt
documento_correcao.auditoria_humana.summary
documento_correcao.auditoria_humana.queue
documento_correcao.auditoria_humana.categories_count
documento_correcao.reparos_aplicados_consolidados
documento_correcao.candidatos_rejeitados_consolidados
```

Cada item em `auditoria_humana.queue` traz:

```json
{
  "row_id": "budget:95877|SINAPI",
  "codigo": "95877",
  "banco": "SINAPI",
  "family": "budget",
  "missing_fields": ["custo_parcial"],
  "categories": ["campo_vazio", "campo_matematico_vazio"],
  "suggested_action": "procurar valores matemáticos na linha física...",
  "human_error_note": "pode ser falha do PDF/orçamento original..."
}
```

## 4. documento_evidencias

É o documento de provas e rastreabilidade.

Use para responder: “por que o parser aplicou esse valor?”

Contém:

- índices usados (`document_evidence_index`, `physical_evidence_index`);
- reparos aplicados pela cascata local;
- candidatos rejeitados pela cascata local;
- resumo matemático;
- cadeia orçamento → composição → auxiliares;
- política de fonte de verdade.

Este documento **não é** documento de enriquecimento do sistema. Ele é explicativo/auditável.

## 5. documento_enriquecimento

É o documento para enriquecer o sistema/base_config/admin.

Use para sugerir, com revisão humana:

- novas unidades observadas;
- unidades suspeitas;
- aliases de banco/fonte;
- padrões de código;
- templates/títulos de seção observados;
- guardas contra falsos positivos.

Nunca aplique automaticamente no `base_config`.

Estruturas principais:

```txt
documento_enriquecimento.unit_candidates.known_or_parser_supported_units
documento_enriquecimento.unit_candidates.new_unit_candidates
documento_enriquecimento.unit_candidates.suspicious_unit_candidates
documento_enriquecimento.bank_aliases_detected
documento_enriquecimento.code_patterns_detected
documento_enriquecimento.section_templates_detected
```

Exemplo:

```json
{
  "value": "M3XKM",
  "normalized": "M3XKM",
  "base_config_status": "parser_supported_but_review_if_missing_from_user_base_config",
  "suggested_action": "review_and_add_to_base_config_units_if_valid"
}
```

## 6. Composições SINAPI-like

Caminho típico:

```txt
final_result.composicoes.sinapi_like.principais["CODIGO|BANCO"]
```

Cada principal pode conter:

- `principal`: linha da composição principal;
- `composicoes_auxiliares`: auxiliares usadas dentro da principal;
- `insumos`: insumos usados dentro da principal;
- outros agrupamentos internos conforme extração.

A auxiliar interna pode ou não ter auxiliar global correspondente. Ausência de auxiliar global não é erro fatal; vira warning/pendência conforme impacto na composição.

## 7. Composições SICRO

Caminho típico:

```txt
final_result.composicoes.sicro.principais
final_result.composicoes.sicro.auxiliares_globais
```

O motor SICRO separado (`sicro_only`) é autoritativo. O parser principal não deve aplicar regras SINAPI-like nas seções SICRO.

Regra de coleção:

```txt
SICRO com número de item → principais
SICRO sem número de item → auxiliares_globais
```

## 8. Orçamento sintético

Caminho típico:

```txt
final_result.orcamento_sintetico.itens_raiz
```

O orçamento é hierárquico:

```txt
meta
└── submeta
    └── item folha
```

Itens folha costumam ter:

```txt
item, codigo, fonte/banco, especificacao, und, quant,
custo_unitario_sem_bdi, custo_unitario_com_bdi, custo_parcial
```

Metas/submetas podem ter menos campos e normalmente carregam descrição e total.

## 9. Como o Lovable deve usar os documentos

Fluxo recomendado:

1. Use `final_result` para popular o sistema.
2. Use `documento_correcao.auditoria_humana.queue` para montar revisão.
3. Use `documento_evidencias` para explicar decisões e correções ao usuário.
4. Use `documento_enriquecimento` para sugerir melhorias no admin/base_config.
5. Nunca confunda `documento_evidencias` com `documento_enriquecimento`.

## 10. Regra central

Tudo que entra no JSON final deve vir do PDF, com evidência e validação quando aplicável. O parser pode buscar agressivamente, mas não deve inventar valores.
