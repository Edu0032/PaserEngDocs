# Changelog — v61.0.25

## Foco

Integração real do motor de rechecagem profile-aware no orçamento sintético e revisão de sanitização para eliminar regras fixas destrutivas.

## Implementado

- Targeted recovery local agora suporta `family=budget` e `family=composition`.
- Worker coleta alvos do `orcamento_sintetico.itens_raiz` além de `composicoes.sinapi_like.*`.
- Patches de orçamento escrevem em `especificacao`, não em `descricao`.
- `recovery_agent` aceita patches de `descricao` e `especificacao`.
- Patches no-op são rejeitados antes da escrita e também no commit.
- `document_learning_profile`, `enrichment_report` e `profile_aware_recheck` ficam preservados no `meta.performance` final.
- Sanitizers de orçamento e composição deixaram de cortar descrições apenas por conter cargos técnicos como `ENGENHEIRO` ou `ARQUITETO`.
- Payload enviado ao Docling foi limpo: regras fixas de execução/parser não são mais enviadas por padrão; o payload carrega evidências do documento e hints de tabela.
- `seed_pages` do payload leve agora também alimenta o payload Docling no worker.

## Validação

- 47 testes automatizados passando.
- Teste pequeno de fluxo completo validou orçamento e composição com descrição quebrada para baixo.
- `ENGENHEIRO CIVIL DE OBRA JUNIOR COM ENCARGOS COMPLEMENTARES` não é mais apagado pelos sanitizers.
