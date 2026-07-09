# v61.0.60 — physical numeric tail recovery

## Objetivo

Fortalecer a fidelidade documental dos campos numéricos públicos em composições SINAPI-like quando o PDF quebra a linha visual e a cauda `Und / Quant. / Valor Unit / Total` fica separada ou fora da ordem textual.

## Mudanças principais

- Novo módulo `app/parser/physical_numeric_tail_recovery.py`.
- Recuperação física de cauda numérica no mesmo bloco da composição, usando página, item, código e banco já conhecidos.
- A matemática agora é usada apenas como seletor/validador de candidato; ela não escreve valores públicos.
- Se um bloco SINAPI-like tem componente com total ausente e a composição não fecha, o quality gate passa a bloquear `status=ok` até a recuperação física ou revisão.
- Integração no fluxo browser direto (`parse_document_browser`) e no fluxo de pós-processamento/accuracy (`run_core_extraction_accuracy_flow_file_json`).
- Novo helper Pyodide: `run_physical_numeric_tail_recovery_file_json`.
- Rebuild dos bundles `api_pdf_pyodide_src.zip` e manifests com versão v61.0.60.

## Caso regressivo principal

Composição `4.5.2 / 93391`:

- Principal: `m² 1,0000000 69,88 69,88`.
- Auxiliar `88256`: `H 0,2411000 31,60 7,61`.
- Insumo `00001297`: `m² 1,0571000 45,18 47,75`.

A composição agora fecha por soma dos totais reportados no PDF:

`7,61 + 3,14 + 9,86 + 1,52 + 47,75 = 69,88`.

## Política mantida

Campo público financeiro = token físico do PDF.  
Cálculo = auditoria/seleção/validação.  
Cálculo não sobrescreve automaticamente o JSON público.
