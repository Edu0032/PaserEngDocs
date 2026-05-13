# Manual do base_config.json para interface Lovable — v61.0.23

O `parser_browser/db/base_config.json` é a base de conhecimento editável do parser. A v61.0.23 também carrega fragmentos em `parser_browser/db/base_config.d/*.json` em ordem alfabética, com merge profundo.

## Estrutura de carregamento

```text
base_config.json
  + base_config.d/00_core.json
  + base_config.d/10_units_common.json
  + base_config.d/20_code_patterns_sinapi_flexible.json
  + base_config.d/40_sicro_output_contract.json
  + base_config.d/60_recheck_rules.json
  + base_config.d/80_custom_bank_profiles.json
  + base_config.d/90_config_ui_schema.json
= config final do parser
```

## Ideia de produto Lovable

- Config global/admin: regras universais, unidades, aliases, schemas e regex.
- Config do usuário: bancos personalizados, aliases próprios e preferências.
- Antes de cada parser: merge global + usuário.
- Depois da extração: o parser entrega `enrichment_report` com unidades/bancos novos observados.

## Blocos principais

```json
{
  "knowledge_base": {},
  "knowledge_bases": {},
  "custom_bank_profiles": {},
  "recheck_rules": {},
  "quality_gate": {},
  "output_contract": {},
  "config_ui": {}
}
```

## Unidades

Unidades podem passar de quatro caracteres. Exemplo aceito:

```json
{
  "canonical": "M3XKM",
  "aliases": ["M3XKM", "m3xkm", "m³xkm", "m³.km"],
  "families": ["all"]
}
```

O parser também pode reportar novas unidades detectadas em `enrichment_report.new_units_detected`.

## Regex de códigos SINAPI

A v61.0.23 evita regex rígido demais. Códigos SINAPI podem ter `/` e `-`:

```text
74209/001
103672-01
CP - 120
```

Valores monetários como `6,05` ou `1.234,56` não devem ser aceitos como código.

## SICRO

O contrato SICRO fica em configuração, mas o motor v20 continua autoritativo. O adapter final não remove colunas extraídas.

Regras centrais:

```text
SICRO2, SICRO3 e DNIT normalizam para banco_canonico = SICRO.
O campo banco original é preservado.
Composição com item = principal.
Composição sem item = auxiliar global.
```

## Bancos personalizados

Exemplo de banco flat, semelhante ao SINAPI:

```json
{
  "id": "meu_banco_sinapi_like",
  "display_name": "Banco personalizado",
  "family": "sinapi_like",
  "enabled": true,
  "inherits_from": ["sinapi_like"],
  "templates": [
    {
      "id": "composicao_padrao",
      "type": "flat_table",
      "header_order": ["controle_linha", "codigo", "banco", "descricao", "tipo", "und", "quant", "valor_unit", "total"]
    }
  ]
}
```

Exemplo de banco seccional:

```json
{
  "id": "meu_banco_seccional",
  "display_name": "Banco Seccional Personalizado",
  "family": "sectioned",
  "enabled": true,
  "inherits_units_from": ["sinapi_like", "sicro"],
  "sections": {
    "A": {"name": "Equipamentos", "columns": ["codigo", "banco", "equipamento", "quantidade", "custo_horario"]}
  }
}
```

## Recheck rules

`recheck_rules` controla limites de score e vetos de poluição. O Lovable/admin pode ajustar sem alterar código.

Vetos típicos:

```text
Custo Total das Atividades
Valor com BDI
MO sem LS
Material Material
=>
sequências longas de números
```

## Regra importante

O parser deve aceitar chaves desconhecidas para permitir evolução da interface sem quebrar compatibilidade.
