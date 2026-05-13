# Manual do documento de enriquecimento de base — v61.0.35

O enrichment document registra descobertas que podem melhorar o parser no futuro sem virar hardcode específico de documento.

## Exemplos de enriquecimento

```json
{
  "new_units_detected": [
    {"value": "M3XKM", "confidence": 0.96, "evidence": ["coluna UND", "repetiu no orçamento"]}
  ],
  "new_bank_aliases": [],
  "new_header_aliases": [],
  "custom_bank_profile_suggestions": []
}
```

## Como usar

- Sugestões globais/universais vão para aprovação do administrador.
- Sugestões específicas do usuário vão para o `user_base_config`.
- Nada deve ser salvo automaticamente como regra global sem revisão.

## Admin vs usuário

Admin pode aprovar:

- unidade comum nova;
- regex universal;
- alias de banco nacional;
- regra de Quality Gate;
- schema fixo.

Usuário pode criar:

- perfil de banco/tabela própria;
- aliases locais de headers;
- estrutura de orçamento personalizada;
- layout recorrente do próprio órgão/empresa.
