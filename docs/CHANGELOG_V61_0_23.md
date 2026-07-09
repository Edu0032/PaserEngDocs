# Changelog — v61.0.23

## Nome

`v61.0.39-deep-area-sweep-iterative-closure`

## Mudanças principais

- Contrato público de composições separado por família:
  - `composicoes.sinapi_like.principais`;
  - `composicoes.sinapi_like.auxiliares_globais`;
  - `composicoes.sicro.principais`;
  - `composicoes.sicro.auxiliares_globais`.
- Adapter SICRO não destrutivo:
  - preserva a linha principal entregue pelo motor SICRO v20;
  - preserva `tipo`, `codigo`, `banco`, `descricao`, `und`, `quant`, `valor_unit`, `total` e demais colunas públicas existentes;
  - adiciona `banco_canonico` sem substituir o banco original (`SICRO3`, `DNIT`, etc.);
  - não remove campos de seção A-F que o motor já extraiu.
- Classificação SICRO corrigida:
  - composição com número de item entra em `composicoes.sicro.principais`;
  - composição sem número de item entra em `composicoes.sicro.auxiliares_globais`.
- Cleaner SICRO revisado para funcionar como preservador de contrato, não como compactador agressivo.
- Quality Gate final adicionado em `auditoria_final.quality_gate`, checando split de famílias, linhas SICRO incompletas, vazamento de floats e sincronização entre `validacao` e `documento_correcao`.
- Recheck SINAPI-like revisado com gates anti-poluição:
  - rejeita rótulos de resumo, `=>`, repetições como `Material Material`, sequências longas de números e textos de rodapé/cabeçalho;
  - só aplica correção de descrição quando há score suficiente;
  - registra reparos aplicados e rejeitados.
- Perfil de aprendizado do documento adicionado ao merge:
  - `document_learning_profile`;
  - `enrichment_report` com unidades/bancos observados.
- `base_config` agora aceita fragmentos em `db/base_config.d/*.json`, carregados em ordem alfabética com merge profundo.
- Payload leve v61.0.23 aceito pelo browser e pelos modelos de intake, mantendo compatibilidade com o formato antigo.
- Regex SINAPI flexibilizado para aceitar códigos com `/` e `-`, sem confundir códigos com valores monetários pt-BR.
- API Docling ajustada para receber `first_row_samples`/contexto do payload e manter o normalizer como etapa local Pyodide.

## Testes

- `python -m compileall -q parser_browser/app api_docling/app`
- `PYTHONPATH=parser_browser pytest -q tests`
- Resultado local: `34 passed`.

## Observação

O motor SICRO v20 continua autoritativo. A versão v61.0.23 evita destruir a estrutura já correta entregue por ele e concentra a inteligência pesada no SINAPI-like/orçamento, onde há maior risco de poluição e linhas quebradas.
