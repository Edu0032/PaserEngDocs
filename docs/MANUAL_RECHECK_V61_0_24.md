# Manual da Rechecagem — v61.0.24

## Ideia central

A rechecagem usa descrições confirmadas como conhecimento interno do documento. Se o parser sabe que `90777|SINAPI` corresponde a uma descrição completa, essa informação serve para corrigir linhas truncadas e para impedir que fragmentos soltos sejam anexados indevidamente nessa linha.

## Onde roda

- Orçamento sintético.
- Composições SINAPI-like/PRÓPRIO.
- Targeted recovery local com PyMuPDF.

## Fontes de evidência

- Repetição do mesmo `codigo|banco`.
- Concordância entre orçamento e composição.
- Qualidade textual da descrição.
- Posição geométrica do fragmento.
- Banda da coluna `descricao` aprendida por família/tabela.
- Veto anti-poluição.

## Códigos vs valores

Códigos podem conter:

```text
CADM.01
COMP.JCO.3
CP - 120
74209/001
103672-01
```

Valores financeiros/decimais pt-BR normalmente têm vírgula:

```text
1.234,56
6,05
100,0000
```

Portanto, ponto sozinho não transforma código em valor numérico.
