# Payload Lovable campo a campo — v61.0.23

A v61.0.23 aceita um payload leve. O Lovable deve enviar principalmente informações que mudam por documento. Regras fixas, schemas, aliases, unidades, regex, limites de recheck e políticas de saída ficam no `base_config`.

## Payload mínimo recomendado

```json
{
  "base_id": "misto",
  "document": {
    "filename": "orcamento.pdf",
    "page_count": 148,
    "obra_nome": "Construção da casa do produtor"
  },
  "ranges": {
    "budget": {"start": 2, "end": 4},
    "compositions": {"start": 9, "end": 139}
  },
  "seed_pages": {
    "budget": 2,
    "composition": 9
  },
  "document_hints": {
    "families_detected": ["sinapi_like", "sicro"],
    "custom_bank_ids": []
  }
}
```

## Campos

### `base_id`

Identifica a base de configuração. Normalmente use `misto`.

### `document`

Metadados do arquivo:

- `filename`: nome do PDF;
- `page_count`: quantidade de páginas, quando disponível;
- `obra_nome`, `obra_localizacao`, `orgao_nome`, `contratante_nome`: metadados úteis para auditoria.

### `ranges`

Intervalos reais do documento:

- `ranges.budget.start/end`: orçamento sintético;
- `ranges.compositions.start/end`: composições analíticas.

### `seed_pages`

Páginas enviadas para Docling/API de estrutura:

- `seed_pages.budget`: página com cabeçalho representativo do orçamento;
- `seed_pages.composition`: página com composição representativa.

### `document_hints`

Sinais leves detectados pela IA/Lovable:

- `families_detected`: por exemplo `sinapi_like`, `sicro`, `proprio`;
- `custom_bank_ids`: ids de perfis personalizados escolhidos pelo usuário.

## Payload opcional com tabelas observadas

Use quando a IA conseguir identificar headers e amostras da primeira linha.

```json
{
  "observed_tables": {
    "budget": {
      "headers_observed": ["ITEM", "CÓDIGO", "FONTE", "ESPECIFICAÇÕES DOS SERVIÇOS", "UND", "QUANT."],
      "first_row_samples": [
        {"canonical": "codigo", "text": "74209/001"},
        {"canonical": "descricao", "text": "ADMINISTRAÇÃO LOCAL DA OBRA"}
      ]
    },
    "composition_sinapi_like": {
      "headers_observed": ["Código", "Banco", "Descrição", "Tipo", "Und", "Quant.", "Valor Unit", "Total"],
      "first_row_samples": [
        {"canonical": "codigo", "text": "90777"},
        {"canonical": "banco", "text": "SINAPI"}
      ]
    }
  }
}
```

Essas amostras são usadas pelo Docling/adapter limpo como contexto, e pelo normalizer local para confirmar colunas.

## Compatibilidade

O formato antigo ainda é aceito:

```json
{
  "base_id": "misto",
  "orcamento_inicio": 2,
  "orcamento_fim": 4,
  "composicoes_inicio": 9,
  "composicoes_fim": 139,
  "docling_seed_pages": {"budget": 2, "composition": 9},
  "tables": {}
}
```

## O que não deve ficar no payload novo

Essas informações são fixas e devem ficar no `base_config`:

```text
normalizer_mode
table_structure_enabled
schemas fixos
aliases fixos
unidades
regex de códigos
regras de recheck
quality gate
política de saída
```

## Prompt para o Lovable montar payload

```text
Analise o PDF de orçamento e gere apenas o payload variável do documento para o parser browser v61.0.23.
Identifique:
1. intervalo do orçamento sintético;
2. intervalo das composições analíticas;
3. página seed do orçamento;
4. página seed de composição representativa;
5. famílias detectadas: sinapi_like, sicro, proprio ou banco personalizado;
6. headers observados e primeira linha de conteúdo quando estiverem claros;
7. cabeçalhos/rodapés recorrentes apenas se forem específicos deste PDF.

Não invente schemas, regex, unidades ou regras fixas. Essas informações pertencem ao base_config.
```
