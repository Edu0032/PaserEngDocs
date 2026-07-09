# Changelog — v61.0.48-output-contract-and-human-error-correction

## Objetivo

Corrigir e profissionalizar o contrato dos outputs do parser para o Lovable, separando claramente resultado final, correção, evidências e enriquecimento do sistema.

## Mudanças principais

- `documento_enriquecimento` voltou ao papel correto: sugerir informações gerais para enriquecer `base_config`/admin, como unidades novas, aliases de banco/fonte, padrões de código e templates de seção.
- Novo `documento_evidencias`: concentra as provas usadas para fechar/corrigir linhas, incluindo índice físico, índice documental, cascata local, matemática e cadeias de reconstrução.
- `documento_correcao` ganhou `auditoria_humana`, com fila de revisão, classificação de pendências, ações sugeridas e política para lidar com possíveis erros humanos no PDF.
- Novo export Pyodide/Lovable `run_output_contract_final_flow_file_json`.
- Novo export `organize_output_documents_json`, para reorganizar outputs após recovery tardio ou qualquer patch posterior.
- Worker Lovable agora reorganiza os outputs após ciclos de targeted recovery, evitando documento de correção/enriquecimento desatualizado.
- Bundle retorna também `evidence_document` e `enrichment_document` no resultado do fluxo, além de `correction_document`.

## Política de enriquecimento

O parser nunca altera `base_config` automaticamente. O `documento_enriquecimento` é apenas sugestivo e deve passar por revisão humana/Admin no Lovable.

## Política de erro humano

Erros possíveis do PDF/orçamento original não devem quebrar o parser nem gerar preenchimento inventado. Eles devem ser registrados no `documento_correcao.auditoria_humana` com evidências, categoria e próxima ação recomendada.
