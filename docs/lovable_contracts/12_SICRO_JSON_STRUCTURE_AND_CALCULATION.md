# Estrutura SICRO no JSON final — v61.0.57

Este documento explica **como o Lovable deve ler composições SICRO** no `final_result` gerado pelo parser.

A regra principal é simples:

- **SINAPI-like/Próprio** usa `principal + composicoes_auxiliares + insumos`.
- **SICRO** usa `principal + secoes A-F`.

O motor SICRO é autoritativo. O parser Python não deve converter SICRO para o modelo SINAPI-like no JSON público.

---

## 1. Caminho no JSON

As composições SICRO ficam em:

```json
final_result.composicoes.sicro
```

Dentro desse bloco existem duas coleções:

```json
{
  "principais": {},
  "auxiliares_globais": {}
}
```

A classificação segue a regra oficial do projeto:

```txt
SICRO com item próprio emitido pelo motor SICRO → principais
SICRO sem item próprio emitido pelo motor SICRO → auxiliares_globais
```

O parser **não deve herdar item do orçamento sintético** para promover uma composição SICRO. Se o motor SICRO não entregou item próprio, a composição é auxiliar/global no contrato público. Se o Lovable entender que deveria haver vínculo com o sintético, isso vira revisão de relacionamento, não reclassificação automática.

---

## 2. Estrutura pública de uma composição SICRO

Formato esperado:

```json
{
  "principal": {
    "codigo": "1234567",
    "banco": "SICRO",
    "servico": "Compactação de aterros a 100% do Proctor intermediário",
    "unidade": "m³",
    "quantidade": "1,0000000",
    "custo_unitario": "6,05",
    "custo_total": "6,05",
    "document_consistency": {
      "status": "sem_referencia_no_sintetico"
    }
  },
  "secoes": {
    "A": {"nome": "Equipamentos", "linhas": []},
    "B": {"nome": "Mão de Obra", "linhas": []},
    "C": {"nome": "Materiais", "linhas": []},
    "D": {"nome": "Atividades Auxiliares", "linhas": []},
    "E": {"nome": "Tempo Fixo", "linhas": []},
    "F": {"nome": "Momento de Transporte", "linhas": []}
  },
  "resumos": {},
  "validacao": {},
  "paginas": [72, 73],
  "pagina_inicio": 72,
  "pagina_fim": 73
}
```

### Campos que **não devem existir** em SICRO público

Na principal SICRO, o Lovable não deve esperar os aliases SINAPI-like:

```txt
descricao
und
quant
valor_unit
total
banco_coluna
banco_canonico
natureza
tipo
```

No bloco SICRO, o Lovable também não deve esperar:

```txt
composicoes_auxiliares
insumos
detalhes
sicro
```

O conteúdo correto está diretamente em `principal`, `secoes`, `resumos` e `validacao`.

---

## 3. Seções SICRO A-F

### Seção A — Equipamentos

Representa equipamentos usados na composição.

Campos comuns:

```txt
codigo
banco
equipamento
quantidade
utilizacao.operativa
utilizacao.improdutiva
custo_operacional.operativa
custo_operacional.improdutiva
custo_horario
```

Cálculo conceitual:

```txt
custo_horario = composição do custo operacional ponderado por utilização
```

O parser preserva os valores textuais do PDF; o Lovable pode usar esses campos para exibir ou recalcular em camada própria.

---

### Seção B — Mão de obra

Representa mão de obra usada na composição.

Campos comuns:

```txt
codigo
banco
mao_obra
quantidade
salario_hora
custo_horario
```

Cálculo conceitual:

```txt
custo_horario = quantidade × salario_hora
```

---

### Seção C — Materiais

Representa materiais diretos.

Campos comuns:

```txt
codigo
banco
material
unidade
quantidade
preco_unitario
custo
```

Cálculo:

```txt
custo = quantidade × preco_unitario
```

---

### Seção D — Atividades auxiliares

Esta é a seção que **interliga composições SICRO**.

Uma linha da seção D referencia outra composição auxiliar/global SICRO. Isso significa que alterações no preço da composição auxiliar referenciada devem impactar diretamente a composição principal que contém essa linha D.

Campos comuns:

```txt
codigo
banco
atividade_auxiliar
unidade
quantidade
preco_unitario
custo
referencia
```

Exemplo:

```json
{
  "codigo": "1107892",
  "banco": "SICRO",
  "atividade_auxiliar": "Concreto fck = 20 MPa",
  "unidade": "m³",
  "quantidade": "0,0500000",
  "preco_unitario": "678,85",
  "custo": "33,94",
  "referencia": {
    "tipo": "composicao_auxiliar_sicro",
    "chave": "1107892|SICRO",
    "impacto": "preco_da_auxiliar_referenciada_afeta_o_custo_da_principal_sicro"
  }
}
```

Cálculo:

```txt
custo = quantidade × preco_unitario
```

Relação:

```txt
principal SICRO atual
  → seção D
    → composição auxiliar SICRO referenciada por codigo+banco
```

Se o Lovable permitir edição do preço da auxiliar referenciada, ele deve reavaliar as composições principais que a usam na seção D.

---

### Seção E — Tempo fixo

Representa tempos fixos associados a insumos/serviços.

Campos comuns:

```txt
insumo
banco
tempo_fixo
codigo
unidade
quantidade
preco_unitario
custo
```

Cálculo:

```txt
custo = quantidade × preco_unitario
```

A seção E pode carregar dois códigos relevantes: o `insumo` de origem e o `codigo` do serviço de tempo fixo.

---

### Seção F — Momento de transporte

Representa transporte por momento, normalmente com ramificações de DMT.

Campos comuns:

```txt
insumo
banco
momento_transporte
unidade
quantidade
dmt
custo
```

O objeto `dmt` pode conter ramificações por tipo/faixa de transporte, com quantidade e preço unitário de DMT.

---

## 4. Como calcular o total SICRO

O motor SICRO pode retornar `resumos` e `validacao`. O Lovable deve preferir esses campos para exibir auditoria.

Em termos conceituais, o custo da composição SICRO é derivado da combinação das seções:

```txt
custo_total/principal ≈ soma dos custos das seções aplicáveis, conforme contrato SICRO
```

Mas cada seção tem semântica própria. Não aplique a regra SINAPI-like simples `soma de insumos + auxiliares` ignorando as seções. Use:

```txt
A: equipamentos
B: mão de obra
C: materiais
D: atividades auxiliares
E: tempo fixo
F: momento de transporte
```

Quando `validacao.ok = true`, o motor SICRO considera a estrutura consistente dentro do contrato SICRO.

---

## 5. Relacionamento com o orçamento sintético

O orçamento sintético pode conter itens com `fonte = SICRO` ou `SICRO3`.

O vínculo lógico é por:

```txt
codigo + banco normalizado
```

Exemplo:

```txt
1234567|SICRO
7654321|SICRO
```

Se o orçamento referencia um código SICRO e há composição SICRO com a mesma chave, o Lovable pode relacionar os dois.

Se há composição SICRO com item próprio mas sem referência no orçamento, isso é uma revisão de relacionamento.

Se há item SICRO no orçamento e a composição não foi encontrada, isso é uma pendência/revisão para o Lovable.

---

## 6. Diferença entre dados públicos e evidências

`final_result` deve ser limpo e leve.

Informações como bbox, hipóteses, raw trace, targeted recovery, fragmentos físicos ou debug não pertencem ao SICRO público. Elas devem ficar em:

```txt
documento_evidencias
analise_orcamentaria
debug_overlay
```

---

## 7. Regra de compatibilidade com SINAPI-like

Não tente ler SICRO assim:

```txt
principal + composicoes_auxiliares + insumos
```

Leia SICRO assim:

```txt
principal + secoes.A-F
```

A seção D é o equivalente relacional mais próximo de “auxiliares”, mas ela deve continuar como seção D, pois sua semântica é própria do SICRO.

## Atualização v61.0.58 — relação SICRO sem cascata no Python

A partir da `v61.0.59-document-fidelity-and-public-numeric-guard`, o Python trata a saída do motor SICRO como **fonte de verdade somente leitura** para os valores públicos.

### Regra principal

O parser Python **não recalcula**, **não cascateia** e **não sobrescreve** valores de uma linha SICRO usando o preço de outra composição auxiliar. Ele apenas:

1. preserva os valores extraídos pelo motor SICRO na própria composição/seção;
2. expõe relações entre composições, principalmente na seção D;
3. informa ao Lovable que alterações manuais em auxiliares podem impactar composições que as referenciam.

### Seção D

A seção D representa atividades auxiliares referenciadas por uma composição SICRO. Cada linha D deve manter os valores impressos na própria linha do PDF:

```json
{
  "codigo": "1107892",
  "banco": "SICRO3",
  "atividade_auxiliar": "Concreto fck = 20 MPa...",
  "unidade": "m³",
  "quantidade": "0,0420000",
  "preco_unitario": "678,8500",
  "custo": "28,5117",
  "referencia": {
    "tipo": "composicao_auxiliar_sicro",
    "chave": "1107892|SICRO",
    "relacao": "secao_D_referencia_auxiliar_sem_mutacao_no_python",
    "impacto_lovable": "se_o_preco_da_auxiliar_for_alterado_no_lovable_recalcular_a_cadeia_que_referencia_esta_auxiliar"
  }
}
```

Campos como `_cascaded_from`, `sicro_section_totals`, `valor_unit`, `total`, `und` e `quant` não pertencem ao contrato público SICRO.

### Responsabilidade do Lovable

Se o usuário alterar uma composição auxiliar SICRO no Lovable, o Lovable deve usar as relações da seção D para identificar quais composições principais referenciam essa auxiliar e recalcular/revisar a cadeia afetada no próprio sistema. Essa cascata é uma ação de negócio do Lovable, não uma mutação feita pelo parser Python durante a extração.
