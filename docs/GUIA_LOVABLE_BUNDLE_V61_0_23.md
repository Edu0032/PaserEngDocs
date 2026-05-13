# Guia Lovable — Bundle v61.0.23

## Arquivo a usar

```text
release/lovable_browser_bundle_v61_0_23.zip
```

O bundle contém:

```text
browser/
  pyodide/
    manifest.json
    api_pdf_pyodide_src.zip
    pyodide-parser-worker.js
  demo/
```

## Como executar no Lovable

1. Descompacte o bundle no projeto.
2. Sirva a pasta `browser` estaticamente.
3. Carregue `browser/pyodide/manifest.json`.
4. O worker carregará Pyodide 0.29.3, `pydantic`, `pymupdf`, `pypdf` e `api_pdf_pyodide_src.zip`.
5. Envie o PDF completo para o worker.
6. Envie apenas as páginas seed para a API Docling.
7. Passe a estrutura retornada pelo Docling ao parser em `structured_tables`, `normalizer_clean_payload` ou `tables`.
8. O parser executará orçamento, composições, SICRO v20, recheck SINAPI-like, targeted recovery local e correction final.

## Fluxo esperado

```text
PDF completo no browser
→ seed PDF para Docling
→ payload com headers/amostras ajuda Docling e normalizer
→ Normalizer local PyMuPDF refina colunas
→ parser orçamento com document profile
→ parser composições SINAPI-like/PRÓPRIO
→ motor SICRO v20 autoritativo
→ adapter SICRO não destrutivo
→ SINAPI profile recheck com gates anti-poluição
→ merge final separado por família
→ Quality Gate final
→ correction_document final
```

## Logs esperados

```text
[normalizer-local] exports ok
[normalizer-local] refinamento concluído
[parser-budget] preview do orçamento pronto
[parser-compositions] iniciado
[runtime] merging-stages
[targeted-recovery-pdf-ready]
[normalizer-local-recovery-finished]
[targeted-recovery-patches-committed]
```

## Logs que não devem aparecer

```text
PARSER_FUNCTION_NOT_FOUND
Failed to fetch em normalizer externo
collectTargetedRecoveryTargets is not defined
buildSelectedPagesPdfBufferFromPath is not defined
```

## Configuração recomendada legada

O payload leve é recomendado, mas o formato antigo ainda funciona:

```json
{
  "base_id": "misto",
  "orcamento_inicio": 2,
  "orcamento_fim": 4,
  "composicoes_inicio": 9,
  "composicoes_fim": 139,
  "normalizer_mode": "local_pyodide",
  "performance_profile": "browser_robust",
  "table_structure_enabled": true,
  "normalizer_targeted_recovery_enabled": true
}
```

## Saídas principais

- `final_result`: resultado final completo.
- `composicoes`: saída pública separada em `sinapi_like` e `sicro`.
- `documento_correcao`: problemas reais pós-recovery.
- `auditoria_final.quality_gate`: checagem final de integridade.
- `meta.performance.document_learning_profile`: perfil aprendido do documento.
- `meta.performance.enrichment_report`: unidades/bancos novos detectados.
