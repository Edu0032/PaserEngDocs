# Changelog — v61.0.32

`v61.0.39-deep-area-sweep-iterative-closure`

## v61.0.31 — Docling/Profile Hardening incluído

- Payload usage agora reconhece corretamente `observed_headers`, `canonical`, `first_row_text`, `sample_text` e `content_text`.
- Cache Docling usa chave semântica estável baseada em `seed_text_sha256`, `page_map`, `tables_hash`, `crop_policy_hash`, `parser_contract_hash`, `docling_context_hash` e versão de contrato.
- Trace Docling registra etapas: seed prepare, payload build, docling extract, runtime init, document conversion, table extraction, adapter, profile calibration, total e cache status.
- Resposta Docling inclui `metadata.calibrated_document_profile` e `calibrated_document_profile` no topo.
- Perfil calibrado combina perfil inicial Docling com bandas aprendidas localmente pelo PyMuPDF/document learning.
- Reparse seletivo por campo fraco ganhou módulo explícito `parser/selective_reparse.py`.

## v61.0.32 — Accuracy Benchmark incluído

- Novo pacote `app.accuracy` com métricas campo a campo.
- `compute_field_accuracy` compara orçamento e composições contra golden expected result.
- `generate_accuracy_report` cria relatório de acurácia por versão/caso.
- `build_debug_overlay` gera dashboard JSON para Lovable/HTML com colunas, issues, patches, unresolved e acurácia.
- Worker gera `final_result.meta.accuracy_report` quando o payload contém `expected_final_result`/`golden_expected_result`.
- Worker sempre gera `final_result.meta.debug_overlay`.
- HTML de testes atualizado com abas **Acurácia** e **Debug overlay**, além de logs de benchmark/debug.
