# Manual do Correction Document — v61.0.35

O `documento_correcao` é a lista final de pendências e alertas reais após merge, recheck, consensus engine, targeted recovery e Quality Gate.

## Objetivo

Ele não deve esconder falhas. Se o Quality Gate detectou problema, o correction document deve refletir esse problema.

## Estrutura recomendada

```json
{
  "versao": "v61.0.39-deep-area-sweep-iterative-closure",
  "resumo": {
    "total_blocos_analisados": 0,
    "total_registros_com_erro": 0,
    "total_divergencias_matematicas": 0,
    "total_blocos_com_campos_vazios": 0,
    "total_quality_gate_issues": 0
  },
  "composicoes_com_problema": [],
  "problemas_orcamento": [],
  "quality_gate": {},
  "targeted_recovery": {},
  "consensus_engine": {},
  "warnings": []
}
```

## Como interpretar

- `total_registros_com_erro = 0`: não há pendências estruturais conhecidas.
- `quality_gate.ok = false`: interface deve mostrar status de revisão, mesmo se o JSON tiver sido gerado.
- `patches rejected/ambiguous`: não são falhas do parser; são pontos onde o sistema preferiu não arriscar correção destrutiva.

## Problemas que devem aparecer

- campos vazios essenciais;
- divergências matemáticas prováveis;
- descrições com poluição;
- linhas com `=>` no texto público;
- valores públicos como float;
- SICRO mal classificado;
- patch suspeito/rejeitado/revertido;
- Docling sem uso de canonical/first_row;
- Quality Gate falso.

## Interface Lovable

A tela deve separar:

1. erros que precisam correção manual;
2. warnings de documento inconsistente;
3. patches aplicados automaticamente;
4. patches rejeitados por segurança;
5. itens para alimentar base_config/enrichment.
