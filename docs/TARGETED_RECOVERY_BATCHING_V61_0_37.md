# Targeted Recovery em lotes — v61.0.37

## Problema corrigido

Quando havia muitos campos suspeitos, o worker tentava criar um único mini-PDF direcionado com todas as páginas alvo. O construtor de mini-PDF limita esse tipo de arquivo a 12 páginas para proteger memória/tempo no browser.

Antes:

```text
20 páginas alvo → tenta um único mini-PDF → erro fatal
```

Agora:

```text
20 páginas alvo → lote 1 com até 12 páginas + lote 2 com páginas restantes → patches mesclados
```

## Parâmetro configurável

O limite por lote pode ser passado ao worker:

```json
{
  "targeted_recovery_max_pages_per_batch": 12
}
```

Também é aceito em runtime/parser contract, mas o limite máximo continua 12 por segurança.

## Comportamento não fatal

Se um lote falhar, o sistema registra:

```json
{
  "status": "error_nonfatal",
  "reason": "targeted_recovery_batch_failed"
}
```

A falha é adicionada em `unresolved` e no `correction_document`, mas o fluxo final continua.

## Logs esperados

```text
targeted-recovery-batch-started
targeted-recovery-batch-finished
targeted-recovery-batch-failed-nonfatal
```
