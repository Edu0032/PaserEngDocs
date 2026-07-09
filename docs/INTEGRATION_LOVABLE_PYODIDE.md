# Integração Lovable e Pyodide

## Objetivo

Executar o parser Python no navegador e manter a experiência integrada à aplicação Lovable.

## Fluxo

```mermaid
sequenceDiagram
    participant UI as Interface Lovable
    participant Worker as Worker Pyodide
    participant API as API Docling
    participant Parser as Parser Python

    UI->>Worker: Envia PDF e opções de runtime
    Worker->>API: Envia mini-PDF seed
    API-->>Worker: Retorna estrutura de tabela
    Worker->>Parser: Executa pipeline de parsing
    Parser-->>Worker: Retorna JSON final e documentos auxiliares
    Worker-->>UI: Exibe resultado e pendências de revisão
```

## Entradas do worker

- PDF ou conteúdo extraído do PDF.
- Configurações do usuário.
- Opções de runtime.
- Estrutura de tabelas retornada pela API Docling.

## Saídas para a interface

- `final_result`
- `documento_correcao`
- `documento_evidencias`
- `analise_orcamentaria`

## Revisão visual

O documento de correção mantém informações de página, item e evidência. Isso permite que a interface abra a página ou recorte correspondente enquanto o usuário revisa uma divergência.
