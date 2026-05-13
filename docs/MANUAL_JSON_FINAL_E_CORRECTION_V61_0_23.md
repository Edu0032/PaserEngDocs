# Manual do JSON final e Correction Document — v61.0.23

## Estrutura principal

```json
{
  "base_id": "misto",
  "orcamento_sintetico": {},
  "composicoes": {
    "sinapi_like": {
      "principais": {},
      "auxiliares_globais": {}
    },
    "sicro": {
      "principais": {},
      "auxiliares_globais": {}
    },
    "aliases_auxiliares": {}
  },
  "validacao": {},
  "documento_correcao": {},
  "auditoria_final": {
    "quality_gate": {}
  },
  "meta": {}
}
```

## SINAPI-like/PRÓPRIO

SINAPI-like mantém o contrato clássico:

```json
{
  "item": "4.1.1.1",
  "principal": {
    "codigo": "93358",
    "banco": "SINAPI",
    "descricao": "ESCAVAÇÃO MANUAL DE VALA. AF_09/2024",
    "und": "m³",
    "quant": 2.84,
    "valor_unit": 96.36,
    "total": 273.62
  },
  "composicoes_auxiliares": [],
  "insumos": []
}
```

A rechecagem SINAPI-like pode recuperar descrições truncadas e totais matematicamente dedutíveis, mas só aplica correções quando passam pelos gates de evidência.

## SICRO

SICRO usa contrato próprio e não deve ser validado como SINAPI-like.

### Regra de classificação

```text
Tem número de item na composição SICRO → composicoes.sicro.principais
Não tem número de item → composicoes.sicro.auxiliares_globais
```

### Linha principal SICRO

A linha principal é preservada como foi entregue pelo motor SICRO v20. O adapter só adiciona aliases úteis e banco canônico.

```json
{
  "item": "3.1.4",
  "principal": {
    "tipo": "Composição",
    "codigo": "5503041",
    "banco": "SICRO3",
    "banco_canonico": "SICRO",
    "descricao": "Compactação de aterros a 100% do Proctor intermediário",
    "und": "m³",
    "quant": "1,0000000",
    "valor_unit": "6,05",
    "total": "6,05",
    "servico": "Compactação de aterros a 100% do Proctor intermediário",
    "unidade": "m³",
    "quantidade": "1,0000000",
    "custo_unitario": "6,05",
    "custo_total": "6,05"
  },
  "sicro": {
    "secoes": {},
    "resumos": {},
    "validacao": {"ok": true}
  }
}
```

### Seções SICRO A-F

As seções são preservadas em `sicro.secoes`:

```json
{
  "A": {"nome": "equipamentos", "public_key": "equipamentos", "linhas": []},
  "B": {"nome": "mao_obra", "public_key": "mao_obra", "linhas": []},
  "C": {"nome": "materiais", "public_key": "materiais", "linhas": []},
  "D": {"nome": "atividades_auxiliares", "public_key": "atividades_auxiliares", "linhas": []},
  "E": {"nome": "tempos_fixos", "public_key": "tempos_fixos", "linhas": []},
  "F": {"nome": "momentos_transporte", "public_key": "momentos_transporte", "linhas": []}
}
```

O cleaner remove apenas chaves internas de runtime, como `row_uid`, `block_uid`, `numeric_source` e rastros temporários. Ele não remove colunas de domínio extraídas do PDF.

## Correction Document

O `documento_correcao` deve representar o estado final pós-merge, pós-SICRO, pós-recheck e pós-targeted recovery.

```json
{
  "resumo": {
    "total_blocos_analisados": 0,
    "total_registros_com_erro": 0,
    "total_divergencias_matematicas": 0,
    "total_blocos_com_campos_vazios": 0,
    "total_blocos_sem_span_paginas": 0
  },
  "composicoes_com_problema": [],
  "targeted_recovery": {}
}
```

Se `total_registros_com_erro = 0`, o Lovable pode tratar o resultado estrutural como aceito. Avisos documentais devem ser mostrados como alerta, não como erro fatal de extração.

## Quality Gate

`auditoria_final.quality_gate` registra a última checagem:

```json
{
  "ok": true,
  "family_split_ok": true,
  "sicro_public_rows_incomplete": [],
  "numeric_fidelity_errors": [],
  "final_validation_synced": true,
  "issues": []
}
```

Se `ok = false`, o JSON ainda é entregue, mas o Lovable deve mostrar os problemas para revisão.
