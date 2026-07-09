# Deep Area Sweep Iterative Closure — v61.0.39

## Camada 1 — cruzamento leve obrigatório

O novo `Extracted Evidence Cross Resolver` roda dentro do closure e usa apenas o JSON já extraído, ledger de evidências e linhas já conhecidas. Ele não abre o PDF.

Ele cruza:

- orçamento sintético ↔ composição principal;
- composição principal ↔ orçamento sintético;
- auxiliar contextual dentro da principal ↔ auxiliar global;
- linhas `closed_100` ↔ linhas pendentes com mesmo código+banco.

Campos que podem ser cruzados:

- descrição/especificação;
- unidade;
- valor unitário/custo unitário compatível;
- total quando semanticamente seguro.

Campo que nunca é copiado entre contextos:

- quantidade.

## Camada 2 — Deep Area Sweep local

O targeted recovery local agora tem execução para campos não-textuais. Quando recebe targets de `und`, `quant`, `valor_unit`, `total` e custos, ele procura na banda de coluna correta, valida o tipo do valor e usa matemática quando possível.

## Camada 3 — Full PDF Code-Bank Occurrence Sweep

O `Full PDF Code-Bank Occurrence Sweep` é separado do cruzamento leve. Ele é fallback tardio: gera targets com `strategy = full_pdf_code_bank_occurrence_sweep` para linhas que continuam abertas depois do fechamento.

O worker pode transformar esses targets em páginas/ranges do PDF, procurando aparições físicas de código+banco e deixando o normalizer testar candidatos por banda.

## Ciclos de recovery

O worker executa ciclos limitados:

1. coleta targets;
2. monta mini-PDF por lotes;
3. recupera campos;
4. aplica patches;
5. reexecuta closure;
6. para se não houver progresso ou se atingir o limite.

Configuração esperada:

```json
{
  "accuracy_profile": {
    "max_targeted_recovery_cycles": 2,
    "max_full_pdf_code_bank_targets": 160
  }
}
```
