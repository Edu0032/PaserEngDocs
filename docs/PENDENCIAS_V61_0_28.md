# Pendências declaradas — v61.0.28

Nada ficou de fora das correções listadas como P0/P1/P2 na análise anterior em nível de implementação defensiva.

Observações honestas:

1. A API Docling externa real não foi executada neste ambiente; foi testado o contrato da API, validação de payload, trace, cache key e uso do payload real através do endpoint de validação.
2. A correção do item `3.2.7 ANP 01` impede a geração/aplicação futura do patch destrutivo. Um JSON antigo já contaminado pela v61.0.27 é agora marcado pelo Quality Gate como falho, mas o parser não inventa automaticamente a descrição correta sem evidência segura; nesses casos, o correction document deve solicitar revisão ou reextração.
3. A separação completa do monólito `compositions.py` continua como evolução arquitetural futura. Nesta versão, o foco foi endurecer o fluxo existente sem arriscar regressões grandes.
