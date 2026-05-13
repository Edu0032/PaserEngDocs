# Manual do JSON final — v61.0.35

## Estrutura geral

```json
{
  "base_id": "misto",
  "orcamento_sintetico": {},
  "composicoes": {
    "sinapi_like": {"principais": {}, "auxiliares_globais": {}},
    "sicro": {"principais": {}, "auxiliares_globais": {}},
    "aliases_auxiliares": {}
  },
  "validacao": {},
  "documento_correcao": {},
  "auditoria_final": {},
  "meta": {},
  "status": "ok|ok_with_warnings|quality_gate_failed"
}
```

## Orçamento sintético

`orcamento_sintetico.itens_raiz` é uma árvore:

- `meta`: grupo principal;
- `submeta`: grupo intermediário;
- `item`: linha folha, normalmente associável a composição.

Itens folha possuem:

```json
{
  "item": "3.2.7",
  "codigo": "ANP 01",
  "fonte": "PRÓPRIO",
  "especificacao": "AQUISIÇÃO DE ASFALTO DILUIDO CM-30",
  "und": "t",
  "quant": "1,50",
  "custo_unitario_com_bdi": "9.544,40",
  "custo_parcial": "14.316,60"
}
```

Valores públicos vindos do PDF devem ficar em string pt-BR.

## Composições SINAPI-like/PRÓPRIO

```json
{
  "item": "4.1.1.1",
  "principal": {
    "codigo": "93358",
    "banco": "SINAPI",
    "descricao": "ESCAVAÇÃO MANUAL DE VALA. AF_09/2024",
    "und": "m³",
    "quant": "2,84",
    "valor_unit": "96,36",
    "total": "273,62"
  },
  "composicoes_auxiliares": [],
  "insumos": []
}
```

A interface pode mostrar:

- card da composição principal;
- tabela de auxiliares;
- tabela de insumos;
- validação matemática;
- patches aplicados/rejeitados.

## Composições SICRO

SICRO é contrato próprio. O parser não deve converter SICRO para SINAPI-like.

```json
{
  "item": "3.3.1",
  "principal": {},
  "sicro": {
    "secoes": {
      "A": {"nome": "Equipamentos", "linhas": []},
      "B": {"nome": "Mão de Obra", "linhas": []},
      "C": {"nome": "Materiais", "linhas": []},
      "D": {"nome": "Atividades Auxiliares", "linhas": []},
      "E": {"nome": "Tempos Fixos", "linhas": []},
      "F": {"nome": "Momentos de Transporte", "linhas": []}
    },
    "resumos": {},
    "validacao": {}
  }
}
```

Regra oficial:

```text
SICRO com item → composicoes.sicro.principais
SICRO sem item → composicoes.sicro.auxiliares_globais
```

O motor SICRO v20 é a fonte autoritativa. O adapter só organiza, preserva e valida; não remove colunas do motor.

## `meta.performance`

Contém relatórios internos úteis para Lovable:

- `document_learning_profile`;
- `evidence_graph`;
- `selective_field_reparse_executor`;
- `candidate_profile_consensus_engine`;
- `debug_overlay`;
- `accuracy_report`, quando houver golden esperado.

## Como gerar interface

1. Exibir status geral e Quality Gate.
2. Mostrar árvore do orçamento sintético.
3. Permitir abrir cada composição associada por `codigo|banco`.
4. Mostrar SICRO em abas A-F.
5. Mostrar correction document como lista de revisão.
6. Mostrar consensus/reparse/debug em tela de diagnóstico/admin.
