# Manual Lovable — Outputs do Parser v61.0.47

Este manual explica como o Lovable deve consumir os outputs gerados pelo parser browser/Pyodide.

## 1. Visão geral dos outputs

O fluxo completo retorna um objeto principal com estes artefatos importantes:

```json
{
  "status": "ok",
  "budget_preview": "...",
  "budget_stage": "...",
  "compositions_stage": "...",
  "final_result": "...",
  "correction_document": "...",
  "correction_preliminary": "..."
}
```

O Lovable deve tratar `final_result` como o JSON principal. Dentro dele existem três documentos de maior importância:

```json
{
  "orcamento_sintetico": {},
  "composicoes": {},
  "documento_correcao": {},
  "documento_enriquecimento": {},
  "analise_orcamentaria": {},
  "validacao": {},
  "meta": {}
}
```

## 2. `final_result`

É o output principal para alimentar o sistema.

### 2.1 `orcamento_sintetico`

Estrutura esperada:

```json
{
  "orcamento_sintetico": {
    "itens_raiz": [
      {
        "item": "3.2.7",
        "codigo": "ANP 01",
        "fonte": "Próprio",
        "especificacao": "AQUISIÇÃO DE ASFALTO DILUIDO CM-30",
        "und": "t",
        "quant": "1,50",
        "custo_unitario_sem_bdi": "8.408,43",
        "custo_unitario_com_bdi": "9.544,40",
        "custo_parcial": "14.316,60",
        "filhos": []
      }
    ]
  }
}
```

### Como consumir

- `item`: hierarquia do orçamento.
- `codigo + fonte`: identidade principal da linha.
- `especificacao`: descrição pública.
- `und`, `quant`, `custo_unitario_*`, `custo_parcial`, `custo_total`: campos matemáticos.
- `filhos`: metas/submetas e itens folha.

### Regra importante

Metas e submetas podem não ter `codigo`, `quant` ou preço unitário. Itens folha normalmente devem ter esses campos.

## 3. `composicoes`

As composições podem vir separadas por famílias.

```json
{
  "composicoes": {
    "sinapi_like": {
      "principais": {},
      "auxiliares_globais": {}
    },
    "sicro": {
      "principais": {},
      "auxiliares_globais": {}
    }
  }
}
```

## 4. Composições SINAPI-like

### 4.1 Composição principal

```json
{
  "composicoes": {
    "sinapi_like": {
      "principais": {
        "89446|SINAPI": {
          "principal": {
            "codigo": "89446",
            "banco": "SINAPI",
            "descricao": "TUBO, PVC, SOLDÁVEL...",
            "und": "M",
            "quant": "1,0000000",
            "valor_unit": "5,47",
            "total": "5,47"
          },
          "composicoes_auxiliares": [],
          "insumos": []
        }
      }
    }
  }
}
```

### Como consumir

- A chave `89446|SINAPI` é a identidade composta.
- `principal` descreve a composição principal.
- `composicoes_auxiliares` lista auxiliares referenciadas dentro da principal.
- `insumos` lista insumos usados na composição.

### Relação com orçamento sintético

A composição principal pode confirmar:

- `codigo`
- `banco/fonte`
- `descricao/especificacao`
- `und`
- `valor_unit` / custo unitário compatível

Mas não deve sobrescrever automaticamente:

- quantidade do orçamento;
- custo parcial do orçamento.

## 5. Auxiliares globais SINAPI-like

```json
{
  "auxiliares_globais": {
    "88267|SINAPI": {
      "principal": {
        "codigo": "88267",
        "banco": "SINAPI",
        "descricao": "ENCANADOR COM ENCARGOS COMPLEMENTARES",
        "und": "H",
        "quant": "1,0000000",
        "valor_unit": "22,45",
        "total": "22,45"
      }
    }
  }
}
```

### Regra importante

Uma auxiliar referenciada dentro de uma composição principal pode não ter auxiliar global. Isso ocorre por erro humano ou omissão do orçamento. O Lovable deve tratar isso como pendência auditável, não como falha fatal.

Classificação:

- auxiliar sem global + linha interna completa: warning leve;
- auxiliar sem global + campos vazios: pendência média;
- auxiliar sem global + impede soma da composição: pendência crítica.

## 6. Composições SICRO

O SICRO é tratado pelo motor separado `sicro_only`.

```json
{
  "composicoes": {
    "sicro": {
      "principais": {},
      "auxiliares_globais": {}
    }
  }
}
```

### Regra estrutural

- Composição SICRO com número de item: `principais`.
- Composição SICRO sem número de item: `auxiliares_globais`.

### O Lovable não deve exigir

- regra SINAPI-like em SICRO;
- `quant × valor_unit = total` genérico para seções SICRO;
- reprocessamento das seções A-F pelo parser principal.

O parser principal só integra e audita a saída do motor SICRO.

## 7. `documento_correcao`

É o documento usado para revisão, auditoria e resolução de problemas.

Estrutura principal:

```json
{
  "documento_correcao": {
    "resumo_executivo": {},
    "auditoria_consolidada": {},
    "pendencias_para_resolucao": [],
    "reparos_aplicados_consolidados": [],
    "candidatos_rejeitados_consolidados": [],
    "ordem_execucao_pipeline": [],
    "line_certainty_closure": {},
    "physical_evidence_index": {},
    "document_evidence_index": {},
    "local_line_cascade_repair": {},
    "budget_puzzle_resolver": {},
    "budget_reconstruction_graph": {},
    "composition_cost_reconciliation": {},
    "budget_hierarchy_reconciliation": {},
    "entity_chain_conflict_resolver": {},
    "targeted_recovery": {}
  }
}
```

### Como consumir

- `resumo_executivo`: painel rápido.
- `pendencias_para_resolucao`: fila de revisão.
- `reparos_aplicados_consolidados`: o que o parser corrigiu.
- `candidatos_rejeitados_consolidados`: candidatos recusados e motivo.
- `local_line_cascade_repair`: prova da busca local em cascata.
- `line_certainty_closure`: status de fechamento das linhas.
- `physical_evidence_index`: onde o parser encontrou evidências no PDF.

## 8. `documento_enriquecimento`

É um documento explicativo para o Lovable entender as evidências usadas sem precisar ler todo o correction document.

```json
{
  "documento_enriquecimento": {
    "version": "v61.0.48-output-contract-and-human-error-correction",
    "document_type": "documento_enriquecimento",
    "source_of_truth_policy": {},
    "pipeline_execution_order": [],
    "evidence_indexes": {},
    "cascade_repairs": {},
    "math_field_summary": {},
    "chain_summary": {},
    "lovable_consumption_hints": {}
  }
}
```

### Como consumir

- `source_of_truth_policy`: explica quais seções são primárias e quais são auxiliares.
- `pipeline_execution_order`: ordem das ferramentas.
- `evidence_indexes`: resumo dos índices lógico e físico.
- `cascade_repairs`: reparos encontrados pela busca local em cascata.
- `math_field_summary`: resumo das validações matemáticas.
- `chain_summary`: resumo das cadeias orçamento → composição → auxiliares.

## 9. `analise_orcamentaria`

Contém análise consolidada e contrato de consumo.

```json
{
  "analise_orcamentaria": {
    "outputs_contract": {
      "final_result_path": "root",
      "correction_document_path": "documento_correcao",
      "enrichment_document_path": "documento_enriquecimento"
    },
    "pipeline_consolidation": {},
    "budget_reconstruction": {},
    "core_extraction_accuracy": {}
  }
}
```

## 10. Políticas de seções auxiliares

Nem todo PDF tem memória de cálculo, curva ABC, cronograma ou BDI.

O parser não depende delas.

Quando existem:

- memória de cálculo: pode ajudar com contexto, unidade e quantidade final, mas não com preço/custo/total sem validação;
- curva ABC: diagnóstica;
- cronograma: diagnóstico financeiro por período;
- BDI: diagnóstico de parâmetros;
- texto bruto fora dos ranges: evidência fraca, útil apenas quando encaixa com `codigo+banco` e matemática.

## 11. Campos matemáticos

Campos fundamentais:

- orçamento: `quant`, `custo_unitario_sem_bdi`, `custo_unitario_com_bdi`, `custo_parcial`, `custo_total`;
- composição: `quant`, `valor_unit`, `total`.

Regras:

- orçamento folha: `quant × custo_unitario_com_bdi ≈ custo_parcial`;
- composição SINAPI-like: `quant × valor_unit ≈ total`;
- composição principal: soma dos componentes pode validar `valor_unit`;
- meta/submeta: soma dos filhos pode validar total.

A matemática guia a busca. Ela não inventa campo público.

## 12. Como o Lovable deve decidir status visual

Sugestão:

- `closed_100`: mostrar como confirmado.
- `closed_by_strong_consensus`: mostrar como confirmado por consenso.
- `closed_with_warning`: mostrar com alerta.
- `unresolved`: enviar para revisão.

As listas de revisão devem vir principalmente de:

```json
"documento_correcao.pendencias_para_resolucao"
```

## 13. Endpoint Pyodide recomendado

Para o fluxo completo Lovable, usar o worker `lovable-flow`.

Para enriquecimento explícito após merge local:

```txt
run_core_extraction_accuracy_flow_file_json(file_path, final_json, options_json)
```

Esse endpoint retorna o JSON final já com:

- `documento_correcao`
- `documento_enriquecimento`
- `analise_orcamentaria.outputs_contract`
- fechamento pós-índice físico
- cascata local de campos matemáticos

