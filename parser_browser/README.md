# v61.0.35-candidate-profile-consensus-engine

Monorepo do parser browser/Pyodide + API Docling para análise de orçamento sintético e composições.

## Destaque da versão

A v61.0.35 adiciona o **Candidate Profile Consensus Engine**, um orquestrador que administra candidatos e perfis de extração antes da recuperação pesada por PDF.

Ele considera:

- valor atual conservador;
- Evidence Graph;
- cruzamento orçamento sintético × composições;
- Description Ownership Resolver;
- subtração de fragmentos pertencentes a itens vizinhos;
- filtros de poluição;
- reparse seletivo;
- perfis aprendidos.

A regra é conservadora: o parser só altera o JSON quando o candidato vence por consenso; caso contrário, mantém o valor e registra revisão.

## Artefatos Lovable

- `release/lovable_browser_bundle_v61_0_35.zip`
- documentação em `docs/*_V61_0_35.md`

## Testes

Ver `docs/TEST_REPORT_V61_0_35.md`.
