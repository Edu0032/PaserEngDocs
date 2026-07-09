# Changelog — v61.0.48-output-contract-and-human-error-correction

## Objetivo

A v61.0.43 muda a camada de fechamento para tratar o orçamento como um quebra-cabeças de entidades relacionadas: orçamento sintético, composições principais, auxiliares contextuais, auxiliares globais, insumos e evidências físicas do PDF passam a ser vistos como peças do mesmo grafo.

## Principais mudanças

- Novo `entity_relation_graph.py` para mapear entidades e relações por `codigo+banco`.
- Novo `budget_puzzle_resolver.py` para consolidar contexto de entidades, fragmentos físicos e fechamento realista.
- Novo `fragment_ownership_graph.py` para registrar fragmentos físicos candidatos/fechados por dono provável.
- Novo `raw_occurrence_context_parser.py` para tratar ocorrências fora dos intervalos de orçamento/composições como texto bruto útil, sem forçar bandas de tabela.
- Novo `ownership_aware_field_consensus.py` para enriquecer candidatos do consenso quando há suporte de fragmentos físicos pertencentes à mesma entidade.
- Novo `strict_but_realistic_closure.py` para auditar linhas com fechamento criterioso, porém sem bloquear consensos fortes e coerentes.
- `physical_evidence_index.py` agora varre o documento inteiro uma vez: dentro dos ranges conhecidos usa tratamento estruturado; fora deles usa contexto bruto de menor peso.
- `line_certainty_closure.py` agora injeta o Budget Puzzle Resolver dentro do ciclo de fechamento e expõe o resultado no `correction_document`.

## Regras preservadas

- Matemática continua gerando expectativa em `_calc`; ela não escreve campo público sem evidência encontrada.
- Quantidades contextuais continuam protegidas: orçamento, composição e auxiliar global não sobrescrevem quantidades uns dos outros.
- SICRO continua autoritativo no motor `sicro_only`; a v43 não cria novo motor SICRO nem duplica contratos A-F no parser principal.
- SICRO com item permanece em principais; SICRO sem item permanece em auxiliares globais.

## Impacto esperado

- Melhor fechamento de linhas com campos vazios usando relações reais entre orçamento, composição principal e auxiliares.
- Menos poluição entre linhas, porque fragmentos físicos passam a ter dono provável.
- Mais aproveitamento de evidências fora das tabelas, como memoriais, notas e ocorrências textuais de `codigo+banco` em outros layouts.
- Correction document mais rico, incluindo `budget_puzzle_resolver`, `fragment_ownership_graph` e `strict_but_realistic_closure`.
