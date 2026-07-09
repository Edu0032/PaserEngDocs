# 09 — Coverage e colunas ausentes

O parser usa as colunas disponíveis entregues pelo payload, Docling e Normalizer.

Se uma coluna canônica não existe no PDF, isso não é erro fatal. O parser registra ausência de schema, usa as colunas existentes e valida o que for possível.

Diferença importante:

- coluna não presente no documento: não é falha de extração;
- coluna declarada/encontrada, mas campo vazio: pendência de extração/recovery.

Coverage mede se linhas físicas candidatas foram mapeadas no JSON para orçamento, composições e SICRO.
