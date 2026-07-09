# Full PDF Occurrence Consensus — v61.0.40

A varredura por código+banco no PDF inteiro é separada do cruzamento leve entre extrações.

## Estratégia

1. Linhas abertas geram alvos por `codigo+banco`.
2. O worker/normalizer busca ocorrências no PDF inteiro.
3. Os candidatos retornados são agrupados por linha, campo e valor.
4. O valor só é aceito se for repetível ou muito forte, validado pelo tipo de campo.

Isso evita aplicar um candidato isolado de baixa confiança.
