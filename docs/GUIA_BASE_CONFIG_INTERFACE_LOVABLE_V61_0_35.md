# Guia da interface Lovable baseada no base_config — v61.0.35

## Conceito

Existem duas camadas:

```text
base_config do administrador + base_config do usuário = config efetivo do parser
```

O parser agora possui função de merge profundo para sobrepor o config do usuário sem destruir regras globais.

## Base_config do administrador

Deve ficar sob controle do administrador da plataforma. Contém regras universais:

- regex globais;
- unidades comuns;
- bancos conhecidos;
- schemas SINAPI-like;
- schemas SICRO;
- regras de recheck;
- Quality Gate;
- tolerâncias matemáticas;
- cache/Docling/runtime;
- contrato de saída.

A interface admin pode editar módulos em `base_config.d`:

```text
00_core.json
10_units_common.json
20_code_patterns_sinapi_flexible.json
40_sicro_output_contract.json
60_recheck_rules.json
80_custom_bank_profiles.json
90_config_ui_schema.json
```

## Base_config do usuário

Deve ser uma camada separada e menor. O caso principal é permitir que o usuário construa uma tabela personalizada.

Fluxo sugerido:

1. Usuário clica em “Adicionar estrutura personalizada”.
2. Lovable abre uma grade semelhante a Excel.
3. Usuário cria os headers do modelo de orçamento/composição que usa.
4. Para cada header, a interface pede o canônico correspondente: `codigo`, `descricao`, `und`, `quant`, `valor_unit`, etc.
5. O perfil é salvo em `user_base_config.custom_bank_profiles.profiles`.
6. Na execução do parser, o config admin faz merge com o config do usuário.

Exemplo:

```json
{
  "custom_bank_profiles": {
    "profiles": {
      "usuario_modelo_prefeitura_x": {
        "display_name": "Modelo Prefeitura X",
        "family": "sinapi_like",
        "templates": [
          {
            "id": "composicao_padrao",
            "type": "flat_table",
            "columns": [
              {"header": "COD", "canonical": "codigo", "required": true},
              {"header": "SERVIÇO", "canonical": "descricao", "required": true},
              {"header": "UN", "canonical": "und"},
              {"header": "QTD", "canonical": "quant"},
              {"header": "PREÇO", "canonical": "valor_unit"},
              {"header": "TOTAL", "canonical": "total"}
            ]
          }
        ]
      }
    }
  }
}
```

## Importante

O usuário não deve editar diretamente regex globais perigosos. Isso fica para admin. O usuário cria perfis e estruturas próprias, que o parser usa junto com o config global.

## Validação

A interface deve validar:

- toda coluna tem `canonical`;
- headers não repetem canônico obrigatório sem necessidade;
- perfil tem `family`;
- template tem `columns`;
- regex, quando permitidos ao admin, compilam corretamente.
