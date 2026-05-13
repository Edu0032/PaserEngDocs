# Guia geral do bundle, contratos e execução — v61.0.35

## Arquivo do bundle Lovable

```text
release/lovable_browser_bundle_v61_0_35.zip
```

## Conteúdo principal

```text
browser/
  pyodide/
    manifest.json
    api_pdf_pyodide_src.zip
    pyodide-parser-worker.js
  demo/
    index.html
    api-pdf-browser.js
    pyodide/
docs/
  PAYLOAD_LOVABLE_CAMPO_A_CAMPO_V61_0_35.md
  MANUAL_JSON_FINAL_V61_0_35.md
  MANUAL_CORRECTION_DOCUMENT_V61_0_35.md
  MANUAL_ENRICHMENT_DOCUMENT_V61_0_35.md
  GUIA_BASE_CONFIG_INTERFACE_LOVABLE_V61_0_35.md
```

## Fluxo recomendado

```text
PDF completo no browser
→ Lovable/código/IA monta payload document-specific
→ Pyodide cria seed PDF
→ API Docling lê apenas seed PDF
→ Docling retorna perfil inicial de colunas
→ PyMuPDF calibra perfil localmente
→ parser faz orçamento e composições
→ cruzamento orçamento × composições
→ Evidence Graph
→ Selective Field Reparse Executor
→ Candidate Profile Consensus Engine
→ Targeted Recovery local apenas para casos restantes
→ Quality Gate
→ Correction Document
→ final_result
```

## Candidate Profile Consensus Engine

Novo orquestrador da v61.0.35. Ele compara perfis/candidatos:

- valor atual;
- Evidence Graph;
- orçamento × composições;
- ownership de vizinhos;
- subtração de fragmentos dos itens acima/abaixo;
- pollution guard;
- perfil aprendido.

Só aplica correção se houver consenso suficiente. Caso contrário, mantém o valor e registra revisão.

## Contratos importantes

- SICRO continua exclusivo do motor SICRO v20.
- Payload Lovable deve preservar header visual ↔ canônico.
- Valores públicos vindos do PDF devem preservar formato pt-BR.
- `quality_gate.ok=false` deve rebaixar status.
- Correction document deve refletir o estado final.

## HTML de testes

O HTML de simulação agora inclui abas:

- JSON final;
- correction document;
- Docling/seed;
- acurácia;
- reparse seletivo;
- consenso de perfis;
- debug overlay.
