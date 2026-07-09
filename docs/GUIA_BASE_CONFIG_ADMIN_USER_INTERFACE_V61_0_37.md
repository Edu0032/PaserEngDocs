# Guia Lovable — Interface do base_config admin/usuário

## Conceito

O sistema usa duas camadas de configuração:

1. `base_config` do administrador: regras globais do parser.
2. `user_base_config`: overlay personalizado do usuário.

Antes do parser rodar, o sistema faz:

```text
base_config_admin + user_base_config = config efetiva do parser
```

O merge é profundo, não destrutivo e ocorre antes da extração.

## Administrador

O administrador pode modificar regras globais, como:

- unidades universais;
- bancos globais;
- aliases universais de headers;
- padrões de código;
- schemas de orçamento;
- schemas SINAPI-like;
- contrato SICRO;
- regras de recheck;
- Quality Gate;
- políticas de cache/Docling;
- contrato do payload.

Essas alterações devem ser versionadas e publicadas. Ao publicar, elas são espelhadas para todos os usuários.

## Usuário normal

O usuário normal não deve alterar regras globais. Ele pode criar:

- bancos personalizados;
- modelos de tabela por interface tipo planilha;
- aliases locais;
- sugestões de unidades.

## Construtor de tabela personalizada

A interface deve permitir que o usuário desenhe uma tabela como no Excel:

- cada coluna tem `header` e `canonical`;
- pode marcar coluna como `ignore_in_domain`;
- pode marcar coluna como `control_column`;
- pode definir ordem física da tabela;
- pode definir família: `sinapi_like`, `budget_like` ou `sectioned`.

Exemplo de coluna ignorada:

```json
{
  "header": "TIPO",
  "canonical": "tipo",
  "ignore_in_domain": true,
  "include_in_final_json": false
}
```

## Arquivos oficiais

- `parser_browser/db/base_config.json`
- `parser_browser/db/base_config.d/*.json`
- `examples/config_ui/admin_base_config_patch_example_v61_0_37.json`
- `examples/config_ui/user_base_config_custom_table_example_v61_0_37.json`
