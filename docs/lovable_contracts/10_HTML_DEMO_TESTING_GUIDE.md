# 10 — Guia de teste pelo HTML demo

1. Suba a API Docling local.
2. Sirva `parser_browser/browser/demo` por HTTP.
3. Abra `index.html`.
4. Selecione o PDF.
5. Ajuste `runtime_options` na tela: endpoint, cache, timeout.
6. Garanta que o payload contém só dados do documento.
7. Clique em `Testar Docling com seed`.
8. Clique em `Executar fluxo completo browser`.
9. Verifique abas: Final, Correção, Evidências, Enriquecimento, Acurácia, Cobertura, Base Config, Contrato Lovable.
10. Baixe todos os outputs.

Não abra por `file://`; use servidor HTTP local.
