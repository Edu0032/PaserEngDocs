# Contrato do Documento de Correção para Revisão no Lovable

Versão aplicável: v61.0.75-correction-output-contract-and-review-index

## Objetivo

O `documento_correcao` é o índice de revisão do Lovable. Ele deve ser simples para a interface, mas rico o suficiente para abrir o PDF na página correta e focar o recorte da composição/orçamento enquanto o usuário corrige.

Ele não é um log de debug. Hipóteses longas, tentativas internas e rastros de recuperação ficam em `analise_orcamentaria.debug_recovery`.

## Estrutura principal

```json
{
  "documento_correcao": {
    "schema_version": "correction_document.v2.actionable_review",
    "resumo_final_curto": { ... },
    "problemas": [ ... ],
    "problemas_por_categoria": { ... }
  }
}
```

## `resumo_final_curto`

Contém visão humana e acionável:

- `summary`: totais, status, contadores e resumo do quality gate.
- `problemas`: lista plana de problemas/revisões.
- `problemas_por_categoria`: agrupamento por origem.
- `pending_errors`: compatibilidade com versões antigas; erros bloqueantes/extração.
- `warnings`: avisos e incoerências documentais.
- `possible_left_behind_lines`: linhas suspeitas encontradas no PDF e não encaixadas no JSON.
- `applied_patches`: patches seguros aplicados.
- `supporting_material`: caminhos para evidências e debug.

## Categorias de problema

### `quality_gate`

Problemas gerados pelo gate final. Podem bloquear o JSON quando têm `gravidade = blocking`.

### `extraction`

Problemas onde o parser pode não ter extraído tudo que está visível no PDF. Exemplo: campo numérico crítico ausente ou composição não avaliável por falta de campo.

### `document_consistency`

O parser extraiu os valores do PDF, mas o próprio PDF apresenta divergência matemática/documental. O Lovable deve mostrar alerta, mas não recalcular automaticamente nem sobrescrever o valor público.

### `possible_left_behind_lines`

Linhas candidatas encontradas pelo scan PDF × JSON. Elas não são aplicadas automaticamente. O Lovable deve abrir a página/crop, mostrar os candidatos de composição e permitir confirmação manual.

## Campos de cada problema

Cada item de `problemas` deve seguir este formato compacto:

```json
{
  "id": "...",
  "categoria": "extraction | document_consistency | quality_gate | left_behind_scan",
  "tipo": "...",
  "gravidade": "blocking | warning | info",
  "status": "pendente | aviso | resolvido | needs_user_review",
  "local": {
    "source_section": "orcamento_sintetico | composicoes_analiticas",
    "path": "...",
    "item": "4.5.2",
    "codigo": "93391",
    "banco": "SINAPI",
    "composicao": "93391|SINAPI",
    "row_group": "insumos",
    "row_index": 4,
    "page": 24,
    "page_interval": {
      "page_start": 24,
      "page_end": 24,
      "page": 24
    }
  },
  "campo": "total",
  "valor_atual": "...",
  "valor_pdf": "...",
  "valor_calculado": "...",
  "acao_recomendada": "...",
  "material_apoio": {
    "crop_hint": {
      "ui_action": "open_pdf_page_and_focus_region",
      "page": 24,
      "page_start": 24,
      "page_end": 24,
      "focus": "93391|SINAPI",
      "line_preview": "..."
    },
    "line_preview": "...",
    "evidence_ref": "documento_evidencias.evidence_registry"
  }
}
```

## Como o Lovable deve usar

1. Ler `documento_correcao.problemas` para montar a lista da janela de revisão.
2. Ao clicar em um problema, usar `material_apoio.crop_hint` para abrir a página e focar a região/linha.
3. Usar `local.composicao`, `local.item`, `local.codigo`, `local.banco`, `row_group` e `row_index` para localizar a entidade editável no JSON.
4. Usar `evidence_ref` para buscar evidências detalhadas quando necessário.
5. Nunca recalcular ou sobrescrever valores públicos por conta própria. Valores públicos representam tokens declarados pelo PDF; cálculos são auditoria.

## Onde ficam os dados pesados

- Evidências físicas: `documento_evidencias`.
- Debug/hipóteses/tentativas longas: `analise_orcamentaria.debug_recovery`.
- Métricas finais: `quality_metrics` e `meta.performance`.
