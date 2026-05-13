# Guia Lovable — Bundle v61.0.27

## Arquivo

```text
release/lovable_browser_bundle_v61_0_27.zip
```

## Pontos importantes

- A IA/Lovable deve continuar informando o vínculo entre header visível do PDF e canônico do parser.
- O payload público deve conter somente dados variáveis do documento: ranges, seed pages, headers observados, canônicos, first row samples, famílias detectadas e metadados da obra.
- Regras fixas como regex, schemas, tolerâncias, políticas de execução e contratos internos devem ficar em `base_config`.
- A API Docling deve receber apenas mini-PDF seed e contexto útil de tabela. Ela não deve receber full PDF nem regras internas do parser.
- SICRO continua exclusivo do motor SICRO v20.

## Endpoint novo da API Docling

```text
POST /docling/validate-payload
```

Use antes da extração para verificar se o payload está limpo e se contém contexto suficiente para o Docling.
