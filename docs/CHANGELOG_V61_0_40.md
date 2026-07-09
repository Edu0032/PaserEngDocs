# Changelog — v61.0.48-output-contract-and-human-error-correction

A v61.0.40 evolui a v61.0.39 para exigir prova por campo antes de considerar uma linha realmente resolvida.

## Entrou

- Matemática agora gera `_calc.math_only_expectations`, mas não escreve campo público sozinha.
- `field_evidence_grade.py` classifica evidências como física, cruzada, matemática ou fraca.
- `extracted_relation_graph.py` formaliza permissões de cruzamento e bloqueia cópia indevida de quantidades contextuais.
- `full_pdf_occurrence_consensus.py` agrega ocorrências encontradas por código+banco no PDF inteiro antes de aplicar patches.
- Full PDF Code-Bank Sweep agora é uma etapa obrigatória estratégica para linhas ainda abertas, com consenso exigido.
- `sicro_section_closure.py` audita seções SICRO A-F.
- `final_reconciliation_pass.py` valida o estado final do JSON e do correction document.

## Regra crítica

Valor calculado pela matemática só pode ir para campo público se o mesmo valor for encontrado por evidência física, cruzamento extraído ou consenso rastreável.
