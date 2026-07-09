# Manual — Documento de Correção v61.0.51

## Ideia central

O `documento_correcao` não deve dizer apenas “falhou” ou “ok”. Ele deve informar ao Lovable o que é:

1. erro bloqueante;
2. revisão recomendada;
3. diagnóstico interno sem ação humana;
4. evidência de reparo aplicado;
5. possível erro humano do PDF.

## Campos principais

### `documento_correcao.resumo.total_registros_com_erro`

Conta apenas problemas bloqueantes do resultado final. Na v61.0.51, diagnostics como `no_op_same_value` e divergências de hierarquia que exigem revisão, mas não impedem o uso do JSON, não inflam esse número.

### `documento_correcao.resumo.total_pendencias_revisao`

Número de itens que o Lovable pode mostrar em fila de revisão. Inclui descrições potencialmente poluídas, subtotais suspeitos e referências orçamento ↔ composição que precisam de confirmação.

### `documento_correcao.auditoria_humana.summary`

Resumo legível para UI:

- `strict_unresolved_rows`: linhas realmente não fechadas;
- `reference_review_items`: revisão de relações e hierarquia;
- `targeted_recovery_actionable_unresolved`: pendências úteis vindas do targeted recovery;
- `targeted_recovery_diagnostic_ignored`: diagnósticos ruidosos ignorados, como `no_op_same_value`;
- `composition_principal_cascade_fields_repaired`: campos reparados pela cascata de composição.

### `documento_correcao.auditoria_humana.queue`

Fila que o Lovable pode mostrar ao usuário. Cada item possui `type`, `severity`, `message`, `evidence` e `suggested_action` quando aplicável.

## Regra de quantidades contextuais

- Orçamento sintético: quantidade da obra.
- Composição principal: normalmente base `1`.
- Auxiliar interna: consumo contextual dentro da composição principal.
- Auxiliar global: referência/base da composição auxiliar.

Essas quantidades não devem ser copiadas entre contextos sem validação.
