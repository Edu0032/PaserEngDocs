# Changelog — v61.0.48-output-contract-and-human-error-correction

## Objetivo

A versão v61.0.46 usa o PDF real DERACRE enviado como fixture de regressão e endurece o uso das evidências físicas sem criar uma nova família de ferramentas grandes. O foco é aumentar acerto com tuning orientado por erro real.

## Melhorias principais

- Physical Evidence Index agora é section-aware:
  - Orçamento sintético: evidência forte para campos de orçamento.
  - Composições analíticas: evidência forte para campos de composição.
  - Memória de cálculo: evidência útil para contexto/quantidade, mas não pode sobrescrever preço/custo.
  - Curva ABC, BDI e cronograma: evidência diagnóstica, sem escrita automática em campo público.
- Fusão local de linhas físicas divididas por PyMuPDF:
  - recupera rows como `89446|SINAPI` quando código/unidade e descrição/números aparecem em baselines diferentes;
  - evita roubar linha vizinha com limite local, barreira de item e bloqueio de linhas numéricas seguintes.
- Raw occurrence parser mais seguro:
  - evita transformar `CM-30` em unidade `cm`;
  - preserva unidade real quando aparece como token isolado (`t`, `m`, `m²`, etc.).
- Field Consensus agora respeita política de seção:
  - valores vindos de Memória/ABC não contaminam preço, total ou custo parcial;
  - candidatos rejeitados registram `evidence_section_policy_forbids_public_write`.
- Novo módulo `real_document_regression.py`:
  - roda expected_core contra PDFs reais;
  - mede pass/fail de âncoras críticas;
  - reporta section policies ativas e achados de tuning.
- Novo export Pyodide/Lovable:
  - `run_real_document_regression_file_json`.

## Prova com PDF real

O fixture `tests/fixtures/real_documents/deracre_casa_produtor.pdf` foi criado a partir do PDF enviado. O teste valida âncoras reais como:

- `74209/001|SINAPI`: `m²`, `6,00`, `634,16`, `3.804,96`, composição `521,39`.
- `89446|SINAPI`: `m`, `61,00`, `6,65`, `405,65`, composição `5,47`.
- `ANP 01|PROPRIO`: unidade `t`, custos `9.544,40` e `14.316,60`, sem falso `cm` vindo de `CM-30`.

## Compatibilidade

- O motor SICRO `sicro_only` continua autoritativo.
- A nova camada não cria validação SICRO redundante.
- Falhas de regressão/document evidence viram relatório/warning, não crash.
