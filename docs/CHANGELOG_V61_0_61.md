# v61.0.62 — fidelity gate existing recovery hardening

## Objetivo

Fortalecer as ferramentas já existentes, sem criar uma arquitetura paralela: o parser deve usar o PDF como fonte soberana, usar cálculo apenas como seletor/validador e impedir `status=ok` quando ainda existe campo financeiro público ausente que afeta matemática.

## Mudanças principais

- `physical_numeric_tail_recovery.py` foi melhorado para usar o delta matemático apenas como seletor de tokens físicos já presentes no PDF.
- O recovery agora tenta uma busca local adicional por código/banco e valor esperado dentro do mesmo bloco de composição quando a cauda numérica não fica presa ao segmento normal da linha.
- O relatório do recovery passou a expor `blocking_unresolved`, com linhas que continuam sem `und/quant/valor_unit/total` em blocos matematicamente problemáticos.
- O `quality_gate` final agora expõe `severity_summary` e `blocking_issue_count`.
- O `documento_correcao.resumo` sincroniza `quality_gate_blocking_issue_count` e `quality_gate_severity_summary`.
- O Pyodide source bundle foi reconstruído com `app/` e `db/base_config.json` atualizados.

## Política mantida

- Campo público financeiro só pode receber token físico do PDF.
- Matemática pode apontar o que procurar, mas não cria valor público.
- Se o PDF contém o valor, o recovery deve tentar coletar no contexto físico correto.
- Se não coletar e o campo afeta matemática, o JSON não pode sair como `ok`.
