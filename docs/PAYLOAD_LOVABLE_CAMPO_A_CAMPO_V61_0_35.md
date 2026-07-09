# Payload Lovable campo a campo — v61.0.35

## Princípio

O payload público deve carregar **informações variáveis do documento**. Regras fixas, regex, tolerâncias, schemas, bancos universais, unidades universais, regras de recheck, cache e políticas internas ficam no `base_config` do administrador.

O Lovable não deve depender apenas da IA. A interface pode extrair com código tudo que for objetivo: nome do arquivo, quantidade de páginas, ranges selecionados pelo usuário, headers visíveis, primeira linha da tabela, campos do formulário e configurações de runtime. A IA deve ser usada principalmente para interpretar trechos difíceis, escolher seed pages quando o código não conseguir, classificar famílias e sugerir ruídos recorrentes.

## Estrutura recomendada

```json
{
  "version": "v61.0.39-deep-area-sweep-iterative-closure",
  "base_id": "misto",
  "document": {},
  "ranges": {},
  "seed_pages": {},
  "tables": {},
  "document_hints": {},
  "user_base_config": {}
}
```

## `version`

Versão do contrato usado pela interface. Ajuda o parser e o Lovable a exibirem avisos quando o payload foi criado para versão antiga.

## `base_id`

Identifica o perfil base do parser. Para documentos mistos com orçamento sintético, SINAPI-like, PRÓPRIO e SICRO, usar:

```json
"base_id": "misto"
```

## `document`

Informações do PDF e da obra.

```json
{
  "filename": "orcamento.pdf",
  "page_count": 148,
  "title": "Construção da casa do produtor",
  "obra_nome": "Construção da casa do produtor",
  "obra_localizacao": "Sena Madureira/AC",
  "orgao_nome": "DERACRE"
}
```

Como obter:

- `filename`: código do upload.
- `page_count`: leitura direta do PDF.
- `title/obra_nome/localização`: código pode procurar texto de capa/cabeçalho; se incerto, pedir à IA para confirmar.

## `ranges`

Intervalos 1-based do orçamento e composições.

```json
{
  "budget": {"start": 2, "end": 4},
  "compositions": {"start": 9, "end": 139}
}
```

Como obter:

- Preferencialmente pela interface: usuário confirma páginas.
- Código pode sugerir usando palavras como `ORÇAMENTO SINTÉTICO`, `Composições Analíticas`, `Composições Principais`.
- IA pode revisar quando há ambiguidade.

## `seed_pages`

Páginas enviadas à API Docling para capturar perfil inicial.

```json
{
  "budget": 2,
  "composition": 9
}
```

Regras:

- `budget`: página com cabeçalho completo do orçamento sintético.
- `composition`: primeira página com tabela de composição representativa.
- Enviar apenas seed PDF para Docling, nunca o PDF inteiro, salvo modo administrativo de diagnóstico.

## `tables`

Contrato de headers observados pelo PDF vinculados aos canônicos do parser. Esta parte está correta e deve continuar existindo.

```json
{
  "budget": {
    "observed_headers": [
      {"text": "ITEM", "canonical": "item_agregador", "first_row_text": "1.1.1"},
      {"text": "CÓDIGO", "canonical": "codigo", "first_row_text": "74209/001"},
      {"text": "ESPECIFICAÇÕES DOS SERVIÇOS", "canonical": "descricao", "first_row_text": "PLACA DE OBRA EM CHAPA DE ACO GALVANIZADO"}
    ],
    "first_row_samples": []
  },
  "composition": {
    "observed_headers": [
      {"text": "Código", "canonical": "codigo", "first_row_text": "74209/001"},
      {"text": "Banco", "canonical": "banco", "first_row_text": "SINAPI"},
      {"text": "Descrição", "canonical": "descricao", "first_row_text": "PLACA DE OBRA EM CHAPA DE ACO GALVANIZADO"}
    ]
  }
}
```

### Como obter `observed_headers`

1. Código lê a região de cabeçalho por PyMuPDF/Docling/extração textual.
2. Lovable mostra os headers para o usuário/IA confirmar.
3. IA associa header visual ao canônico do parser.
4. O parser usa isso para Docling, normalizer, perfil e correções.

## `document_hints`

Dicas específicas deste PDF.

```json
{
  "families_detected": ["sinapi_like", "sicro", "proprio"],
  "custom_bank_ids": [],
  "recurring_noise_terms": ["DERACRE Página"]
}
```

Use para informações variáveis do documento. Não colocar regex universal aqui.

## `user_base_config`

Overlay opcional criado pela interface do usuário. Deve conter apenas estruturas personalizadas daquele usuário, como banco próprio com headers diferentes.

```json
{
  "custom_bank_profiles": {
    "profiles": {
      "usuario_banco_x": {
        "display_name": "Banco X do usuário",
        "family": "sinapi_like",
        "templates": [
          {
            "id": "orcamento_padrao_x",
            "type": "flat_table",
            "columns": [
              {"header": "COD", "canonical": "codigo"},
              {"header": "DESCRIÇÃO DO SERVIÇO", "canonical": "descricao"}
            ]
          }
        ]
      }
    }
  }
}
```

O parser faz merge profundo:

```text
base_config administrador + user_base_config = config efetivo da execução
```

## Campos que NÃO devem ficar no payload público

- `docling_api_url`
- `docling_timeout_ms`
- `normalizer_mode`
- `parser_contract`
- `fixed_contract`
- `output_options`
- regex universais
- schemas fixos
- tolerâncias internas
- regras de Quality Gate
- regras de recheck

Esses dados pertencem ao runtime interno ou ao `base_config`.

## Prompt exemplo para IA

```text
Analise o PDF de orçamento. Não invente dados. Primeiro use o texto extraído e as páginas detectadas pela interface.

Identifique apenas informações variáveis deste documento:
1. intervalo do orçamento sintético;
2. intervalo das composições analíticas;
3. página seed do orçamento com cabeçalho completo;
4. página seed de composição representativa;
5. headers visíveis da tabela e o canônico correspondente do parser;
6. primeira linha real de conteúdo de cada coluna;
7. famílias detectadas: SINAPI-like, SICRO, PRÓPRIO ou banco personalizado;
8. textos recorrentes específicos deste PDF que parecem cabeçalho/rodapé.

Não gere regex universais, regras internas, tolerâncias, schemas fixos nem configurações de API. Essas informações ficam no base_config do administrador.

Retorne um JSON compatível com v61.0.35.
```
