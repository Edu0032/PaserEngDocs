# JSON final e Correction Document — v61.0.38

## Estrutura geral

```json
{
  "status": "ok | ok_with_warnings | quality_gate_failed",
  "orcamento_sintetico": {},
  "composicoes": {
    "sinapi_like": {
      "principais": {},
      "auxiliares_globais": {}
    },
    "sicro": {
      "principais": {},
      "auxiliares_globais": {}
    }
  },
  "documento_correcao": {},
  "meta": {
    "performance": {}
  },
  "auditoria_final": {
    "quality_gate": {}
  }
}
```

## SINAPI-like

Use `composicoes.sinapi_like.principais` para composições ligadas ao orçamento.
Use `composicoes.sinapi_like.auxiliares_globais` para composições auxiliares reutilizáveis.

Linhas internas:

- `principal`;
- `composicoes_auxiliares`;
- `insumos`.

## SICRO

Use `composicoes.sicro.principais` e `composicoes.sicro.auxiliares_globais`.

Regra:

- tem `item` → principal;
- sem `item` → auxiliar global.

Renderize SICRO por seções:

- A: Equipamentos;
- B: Mão de obra;
- C: Materiais;
- D: Atividades auxiliares;
- E: Tempo fixo;
- F: Momento de transporte.

A interface deve renderizar as linhas SICRO dinamicamente, preservando todos os campos que vierem.

## Correction Document

Além das validações anteriores, a v61.0.38 adiciona:

```json
{
  "line_certainty_closure": {
    "summary": {
      "total_rows": 0,
      "closed_100": 0,
      "closed_with_warning": 0,
      "unresolved": 0,
      "sicro_issues": 0
    },
    "rows": [],
    "sicro_issues": [],
    "deep_area_sweep_targets": []
  }
}
```

A UI deve destacar linhas `unresolved` e permitir filtrar por família: orçamento, SINAPI-like e SICRO.
