# Changelog — v61.0.39-deep-area-sweep-iterative-closure

## Objetivo

Esta versão corrige o erro real observado no fluxo Lovable:

```text
ERRO: Mini-PDF direcionado excede o limite de páginas.
```

O erro acontecia depois de Docling, orçamento, composições e merge. A etapa `targeted_recovery` coletava mais de 12 páginas e tentava gerar um único mini-PDF direcionado, derrubando o fluxo inteiro.

## Mudanças principais

- Targeted recovery agora processa páginas em lotes de até 12 páginas.
- Falha em um lote de targeted recovery é não fatal.
- O JSON final ainda é entregue mesmo quando um lote de recuperação falha.
- Os patches de todos os lotes são mesclados em `meta.targeted_recovery`.
- O log agora expõe `targeted-recovery-batch-started`, `targeted-recovery-batch-finished` e `targeted-recovery-batch-failed-nonfatal`.
- Adicionado contrato de interface admin/usuário para `base_config`.
- Adicionados exemplos oficiais de payload vazio, payload preenchido, runtime local/túnel e overlays de config.
- Removidos arquivos de deploy específicos do Render do monorepo principal.

## Ordem do targeted recovery

O targeted recovery roda depois de:

1. Docling seed;
2. refinamento local;
3. orçamento preview;
4. composições;
5. merge dos estágios;
6. rechecagens de perfil/evidência que acontecem dentro do merge.

Ele roda antes da montagem final do debug overlay e da resposta final ao Lovable.

## Observação

Docling continua sendo uma API separada dentro de `api_docling`. O browser/parser v61.0.37 usa a API Docling v61.0.36 corrigida para CORS/performance.
