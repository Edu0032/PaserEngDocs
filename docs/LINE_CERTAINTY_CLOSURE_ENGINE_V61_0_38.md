# Line Certainty Closure Engine — v61.0.38

## O que ele faz

O motor de fechamento de linhas verifica cada linha relevante do JSON final e tenta fechar todos os campos essenciais usando fatos já extraídos do documento.

Ele usa:

1. cruzamento orçamento ↔ composição;
2. cruzamento composição principal ↔ auxiliar global;
3. evidências repetidas por `codigo|banco`;
4. validação matemática;
5. posse de fragmentos confirmados;
6. contrato SICRO A-F;
7. geração de alvos cirúrgicos para targeted recovery.

## Orçamento sintético

Para item folha do orçamento, ele valida:

- `codigo`;
- `fonte`;
- `especificacao`;
- `und`;
- `quant`;
- `custo_unitario_com_bdi`;
- `custo_parcial`.

A matemática principal é:

```text
quant × custo_unitario_com_bdi ≈ custo_parcial
```

A quantidade do orçamento **não é copiada** da composição, porque no orçamento ela representa a quantidade da obra.

## SINAPI-like

Para linha principal/auxiliar/insumo, ele valida:

- `codigo`;
- `banco`;
- `descricao`;
- `und`;
- `quant`;
- `valor_unit`;
- `total`.

A matemática principal é:

```text
quant × valor_unit ≈ total
```

Para composição principal ligada ao orçamento, `valor_unit`/`total` da composição pode confirmar `custo_unitario_com_bdi` do orçamento.

## Composição auxiliar dentro de principal

Quando uma auxiliar aparece dentro de uma composição principal, ela pode usar a auxiliar global como fonte de verdade para:

- `descricao`;
- `und`;
- `valor_unit`.

Mas **não copia a quantidade** da auxiliar global. A quantidade dentro da principal é contextual e indica quanto aquela principal consome da auxiliar.

## SICRO

O motor não transforma SICRO em SINAPI-like. Ele valida:

- classificação principal/auxiliar global por existência de `item`;
- presença de `principal`;
- seções A-F;
- campos essenciais por seção;
- issues vindas de `sicro.validacao`.

Incoerências SICRO entram em:

```text
documento_correcao.line_certainty_closure
```

## Correction Document

O relatório é anexado em:

```json
{
  "documento_correcao": {
    "line_certainty_closure": {
      "summary": {},
      "rows": [],
      "sicro_issues": [],
      "deep_area_sweep_targets": []
    }
  }
}
```

Cada linha pendente aparece em `warnings` sem duplicação agressiva.
