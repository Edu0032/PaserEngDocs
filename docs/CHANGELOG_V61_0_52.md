# v61.0.53 — Output Clarity and Accuracy Hardening

## Objetivo

A v61.0.53 melhora a organização dos outputs e a leitura dos resultados pelo Lovable, sem criar dependência de comparadores entre versões. O foco é reduzir falsos positivos/negativos no documento de correção, organizar a fila de revisão por severidade, consolidar um relatório de acurácia acionável e validar o contrato final dos outputs.

## Mudanças principais

- Adicionado `app/parser/output_accuracy_report.py`.
- Adicionado `app/parser/output_contract_validator.py`.
- `documento_correcao.auditoria_humana` agora separa:
  - `bloqueantes`
  - `revisoes_recomendadas`
  - `avisos`
- Adicionado `documento_correcao.painel_lovable`, com status resumido para UI.
- Adicionado `analise_orcamentaria.accuracy_report`.
- Adicionado `analise_orcamentaria.output_contract_validation`.
- `documento_enriquecimento` permanece restrito a sugestões de base_config/admin.
- O HTML demo ganhou aba `Contrato outputs` e botão `Baixar todos outputs`.
- Targeted recovery ficou mais seletivo: menos alvos de descrição sem ganho real e mais foco em campos matemáticos/unidade/campos vazios.
- Normalização final de versões evita que metadados antigos de estágios intermediários confundam o Lovable.

## Resultado validado no PDF DERACRE

Fluxo completo com `run_output_contract_final_flow_file_json`:

- `status = ok`
- `quality_gate_ok = true`
- `quality_gate_issues = 0`
- `89446|SINAPI` fechado com `quant=1`, `valor_unit=5,47`, `total=5,47`
- `budget_math_ok_rate = 1.0`
- `budget_required_field_rate = 1.0`
- `composition_principal_required_field_rate = 1.0`
- `composition_principal_triplet_ok_rate = 1.0`
- `documento_correcao.painel_lovable.status = ok`

## Política preservada

- Quantidade do orçamento não sobrescreve quantidade da composição.
- Quantidade de auxiliar global não sobrescreve consumo contextual dentro da composição principal.
- SICRO continua com motor separado e regra: `tem item = principal`, `sem item = auxiliar global`.
- Seções auxiliares são opcionais e nunca substituem campos financeiros sem validação matemática e evidência primária.
