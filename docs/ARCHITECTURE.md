# Arquitetura do ParserOrca

## Objetivo

A arquitetura separa a leitura estrutural do PDF, o parser executado no navegador, os contratos JSON e os mecanismos de validação/revisão.

## Camadas

```text
Browser/Lovable
  -> Worker Pyodide
    -> parser_browser/app/browser
      -> parser_browser/app/parser
        -> parser_browser/app/core
        -> parser_browser/app/integrations
  -> API Docling
    -> api_docling/app
```

## Parser browser

O pacote `parser_browser` contém o motor principal. Ele foi estruturado para funcionar em ambiente Pyodide, portanto evita dependências pesadas no navegador e delega a leitura de estrutura tabular ao serviço Docling.

Partes principais:

- `app/browser`: entrada do runtime browser/Pyodide.
- `app/parser`: estágios de extração, reconciliação, validação e organização do resultado.
- `app/core`: contratos, utilitários, normalizadores e modelos de apoio.
- `app/integrations`: comunicação com a API Docling.
- `app/config`: configurações e base de conhecimento.

## API Docling

A API fica em `api_docling`. Ela recebe trechos pequenos do PDF e retorna estrutura de tabela em JSON. O objetivo é reduzir o custo no navegador e manter o parser principal executando no cliente.

## Contratos

Os contratos estão em `schemas/` e em `docs/lovable_contracts/`. Eles descrevem a estrutura esperada de entrada, runtime options, base config, saída final, evidências e documento de correção.

## Testes

Os testes em `tests/` verificam estabilidade de contrato, consistência de campos, regressões em cenários reais e compatibilidade das saídas com a interface de revisão.
