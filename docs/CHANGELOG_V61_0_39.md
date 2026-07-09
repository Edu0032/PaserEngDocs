# Changelog — v61.0.39-deep-area-sweep-iterative-closure

## Objetivo

A v61.0.39 evolui a v61.0.38 para transformar pendências do `Line Certainty Closure Engine` em recuperação ativa, separando claramente dois recursos diferentes:

1. **Extracted Evidence Cross Resolver**: cruzamento obrigatório e leve entre informações já extraídas.
2. **Full PDF Code-Bank Occurrence Sweep**: fallback pesado e tardio para procurar código+banco no PDF inteiro.

## Implementado

- Novo `parser_browser/app/parser/extracted_evidence_cross_resolver.py`.
- Novo `parser_browser/app/parser/field_patch_validators.py`.
- Novo `parser_browser/app/parser/code_occurrence_sweep.py`.
- Novo `parser_browser/app/parser/sicro_collection_enforcer.py`.
- `Line Certainty Closure Engine` agora registra relatório `extracted_evidence_cross_resolver`.
- `correction_document` agora separa:
  - `extracted_evidence_cross_resolver`
  - `full_pdf_code_bank_occurrence_sweep`
  - `line_certainty_closure`
  - `sicro_collection_enforcer`
- Targeted recovery agora aceita patches seguros de campos não-textuais:
  - `und`
  - `quant`
  - `valor_unit`
  - `total`
  - `custo_unitario_sem_bdi`
  - `custo_unitario_com_bdi`
  - `custo_parcial`
  - `custo_total`
- Recovery commit reexecuta o fechamento de linhas após patches aplicados.
- Worker Lovable ganhou ciclos de targeted recovery (`max_targeted_recovery_cycles`).
- Worker Lovable coleta alvos de fallback `full_pdf_code_bank_occurrence_sweep` quando há páginas/ranges disponíveis.
- SICRO final passa por enforcer: com item vai para `principais`; sem item vai para `auxiliares_globais`.

## Políticas preservadas

- Quantidade do orçamento não sobrescreve quantidade da composição.
- Quantidade da composição não sobrescreve quantidade do orçamento.
- Quantidade da auxiliar global não sobrescreve quantidade contextual dentro da principal.
- SICRO não passa por validação SINAPI-like.
- Matemática ajuda a confirmar candidatos; não deve inventar valores sem evidência.

## Testes

- Parser: `111 passed`.
- API Docling: `4 passed`.
- `compileall`: OK.
- `node --check`: OK.
- `quality_safety_scan`: OK.
