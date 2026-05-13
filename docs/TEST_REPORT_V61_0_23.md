# Test Report — v61.0.23

## Comandos executados

```text
python -m compileall -q parser_browser/app api_docling/app
PYTHONPATH=parser_browser pytest -q tests
```

## Resultado

```text
35 passed
```

## Cobertura principal

- Versões e bundle Pyodide atualizados.
- Worker sem dependência de Normalizer API externa.
- `base_config` editável e carregamento modular por fragmentos.
- Classificadores SICRO de código, unidade e seção.
- Correção do bug de seção `F Banco Insumo Momento de Transporte...` que podia cair em `A` por causa do anchor de letra única.
- Export final SICRO não destrutivo, preservando linha principal e seções A-F.
- JSON final separado em `composicoes.sinapi_like` e `composicoes.sicro`.
- Quality Gate final.
- Correction document SICRO-aware para contrato flat e contrato nested v61.0.23.
- Payload leve Lovable aceito pelo browser e pelo modelo de intake.
- Contexto Docling com `first_row_samples` confirmado no payload limpo, inclusive quando `observed_headers` chega como lista simples de textos.
- Regex SINAPI aceitando `/` e `-`, sem aceitar dinheiro como código.
- Recheck SINAPI-like com veto de poluição.

## Limitação do teste local

O serviço Docling real não foi executado neste ambiente. Foram testados o contrato de payload, o uso de `first_row_samples`/headers no payload limpo e a integração local com PyMuPDF/normalizer. O teste end-to-end com Docling real deve ser executado no Lovable/Render com uma API Docling ativa e PDF real.
