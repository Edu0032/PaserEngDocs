# ParserOrca — v61.0.74-release-integrity-and-diff-scan-hardening

Versão focada em integridade de release, limpeza de hardcodes nocivos, scan diferencial PDF × JSON mais seguro e documento de correção compacto/acionável para o Lovable.

## Objetivo

O parser deve extrair com fidelidade aquilo que está no PDF. Valores públicos são tokens declarados no documento; cálculos servem para validação/auditoria e não sobrescrevem campos públicos.

## Principais garantias da v61.0.74

- Totais de metas/submetas são exibidos inline no próprio nó do orçamento, usando `custo_total`.
- Itens folha usam `custo_parcial` no próprio item.
- `linhas_totais` não é contrato público; índices de apoio ficam em `documento_evidencias`.
- O scan diferencial PDF × JSON é occurrence-aware: considera código, banco, página, cauda numérica, descrição e composições vizinhas.
- O documento de correção mantém somente pendências/avisos/patches acionáveis; debug pesado vai para `analise_orcamentaria.debug_recovery`.
- O `base_config` global não contém exemplos específicos do documento de teste.
- O pacote inclui validação de integridade de release, incluindo SHA do source zip do bundle.

## Arquivos importantes

- `parser_browser/app/parser/integrity_orchestrator.py` — coordena o fluxo real final.
- `parser_browser/app/parser/light_reextraction_diff_scan.py` — scan estratégico de conteúdo possivelmente deixado para trás.
- `parser_browser/app/parser/compact_correction_document.py` — documento de correção limpo para Lovable.
- `parser_browser/app/parser/budget_total_lines.py` — política de totais inline do orçamento.
- `tools/release_integrity_scan.py` — validação de integridade do pacote.

## Contrato com Lovable

O Lovable deve tratar valores públicos como valores declarados no PDF. Não deve recalcular `custo_parcial`, `custo_total`, `valor_unit` ou `total` para sobrescrever o JSON. Divergências matemáticas são alertas de consistência documental, não autorização para alterar o valor público.
