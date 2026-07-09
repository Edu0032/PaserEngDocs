# 06 — Documento de correção

O Lovable deve priorizar `documento_correcao.painel_lovable` e `documento_correcao.auditoria_humana`.

## Severidades

- `bloqueantes`: impedem uso seguro do JSON.
- `revisoes_recomendadas`: devem ser mostradas para decisão humana, mas não bloqueiam necessariamente.
- `avisos`: informação útil, geralmente não bloqueante.
- `diagnosticos_internos`: para desenvolvimento; não mostrar como erro principal.

## Erro humano vs extração

Quando uma composição não fecha, o parser tenta procurar linha candidata que feche a matemática. Se todos os componentes foram extraídos e a diferença permanece, o caso é marcado como provável erro humano/documental.
