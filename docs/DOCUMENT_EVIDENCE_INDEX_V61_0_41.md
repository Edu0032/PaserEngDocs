# Document Evidence Index — v61.0.41

O `Document Evidence Index` é uma camada de evidência global construída durante o fechamento de linhas. Ele não abre o PDF e não substitui o motor SICRO. Ele organiza o que já foi extraído, cruzado ou confirmado em um índice por `codigo+banco`.

## O que ele guarda

- Ocorrências por código+banco.
- Famílias: orçamento, SINAPI-like, SICRO integrado pelo motor separado.
- Páginas conhecidas.
- Valores candidatos por campo.
- Fontes e caminhos no JSON.
- Evidência bloqueada de linhas `closed_100`.

## Como ele é usado

1. O closure roda uma primeira extração/fechamento.
2. Linhas fechadas registram evidência forte.
3. O índice global é construído.
4. O `Field Consensus Engine` consulta esse índice para campos vazios.
5. A matemática pode confirmar candidatos, mas não cria valor público sozinha.

## Filosofia

O parser não deve perguntar “como corrijo essa linha isolada?”. Ele deve perguntar: “o documento já sabe esse valor em algum lugar confiável?”.
