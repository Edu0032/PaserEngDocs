# Integração Lovable ↔ Parser Python — v61.0.57

Este é o guia principal. O Lovable deve conseguir integrar o parser lendo estes documentos, sem depender do histórico do chat.

## Fluxo em uma linha

```text
PDF + document_payload + runtime_options + overlays de config
→ Pyodide worker
→ Docling seed + Normalizer local
→ orçamento + composições + SICRO
→ evidências + fechamento + cobertura + qualidade
→ final_result + documentos auxiliares
```

## O que o Lovable envia

1. `document_payload`: dados do PDF atual, como arquivo, ranges, páginas seed, headers observados e samples.
2. `runtime_options`: endpoint Docling, timeout, cache, modo local/remoto e opções da execução.
3. `admin_config_overlay`: configuração persistente da plataforma/admin.
4. `user_config_overlay`: configuração persistente do usuário/projeto.
5. `PDF`: arquivo completo; o browser gera mini-PDF seed para Docling.

## O que o parser retorna

1. `final_result`: JSON limpo para alimentar o sistema.
2. `documento_correcao`: pendências, revisões e possíveis erros humanos/documentais.
3. `documento_evidencias`: provas técnicas de como valores foram confirmados/corrigidos/rejeitados.
4. `documento_enriquecimento`: sugestões para melhorar base_config/admin, nunca autoaplicadas.
5. `analise_orcamentaria`: métricas, cobertura, confiança por entidade, stage reference, schemas e resumo operacional.

## Arquivos desta pasta

- `01_INPUT_CONTRACT.md`: payload, runtime options e overlays.
- `02_OUTPUTS_CONTRACT.md`: estrutura dos outputs.
- `03_BASE_CONFIG_CONTRACT.md`: dinâmica simples do base_config.
- `04_RUNTIME_OPTIONS_CONTRACT.md`: opções de execução.
- `05_PIPELINE_STAGES.md`: stages e ordem do fluxo.
- `06_ERROR_AND_CORRECTION_CONTRACT.md`: como consumir o documento de correção.
- `07_EVIDENCE_AND_ENRICHMENT_CONTRACT.md`: diferença entre evidência e enriquecimento.
- `08_COMPOSITIONS_AND_SICRO_ASSOCIATION.md`: como ler SINAPI-like, próprios e SICRO.
- `09_SCHEMA_COVERAGE_AND_MISSING_COLUMNS.md`: colunas ausentes e cobertura.
- `10_HTML_DEMO_TESTING_GUIDE.md`: teste local pelo HTML.
- `11_EXAMPLES_FULL_FLOW.md`: exemplos de execução e saída.
- `AUTO_STAGE_REFERENCE.md`: referência gerada do registry de stages.

## Referência SICRO v61.0.57

Para entender o contrato público SICRO no JSON final, incluindo as seções A-F, a seção D como relacionamento com auxiliares e as regras de cálculo/associação, leia:

- `12_SICRO_JSON_STRUCTURE_AND_CALCULATION.md`
