# v61.0.42 — Physical Evidence Index Active Closure

## Objetivo
Tornar a varredura obrigatória por `codigo+banco` uma etapa física, global e ativa: o PDF é lido uma vez, as ocorrências são indexadas por identidade, e o Line Certainty Closure reexecuta usando essas evidências antes do targeted recovery.

## Mudanças principais
- Adicionado `parser_browser/app/parser/physical_evidence_index.py`.
- Adicionados exports Pyodide:
  - `build_physical_evidence_index_file_json`
  - `enrich_physical_evidence_index_file_json`
- Worker Lovable agora executa `physical-evidence-index-started` logo após o merge e antes dos ciclos de targeted recovery.
- `Document Evidence Index` agora é enriquecido com evidência física do PDF.
- `Field Consensus Engine` passa a poder fechar campos a partir de `physical_pdf_index`.
- Matemática continua gerando `_calc` e só escreve campo público se o valor esperado existir em evidência física/lógica.
- `Adaptive Closure Scheduler` agora é operacional: linhas coerentes não consomem consenso pesado; P0/P1/P2 continuam ativas.
- O parser principal não executa validação SICRO A-F redundante; o motor `sicro_only` permanece autoritativo.
- `correction_document` agora registra `physical_evidence_index` e `sicro_native_audit_bridge`.

## Testes
- `127 passed` no parser/browser.
- `4 passed` na API Docling.
- `compileall OK`.
- `node --check OK` nos workers e demo API.
- `quality_safety_scan OK`.
- `zip -T OK` nos dois pacotes finais.
