# Budget Puzzle Entity Closure — v61.0.43

## Ideia central

Um orçamento não é apenas texto extraído. Ele é um conjunto de entidades que se relacionam:

- item do orçamento sintético;
- composição principal;
- composição auxiliar contextual;
- composição auxiliar global;
- insumo;
- ocorrência física do mesmo `codigo+banco` no PDF;
- evidência matemática;
- evidência de consenso.

A v61.0.43 cria uma camada para montar essas relações e usar o encaixe entre entidades como evidência de fechamento.

## Fluxo

1. Extração inicial do orçamento e das composições.
2. Motor SICRO separado processa blocos SICRO.
3. Line Certainty Closure roda as correções leves e consenso de campos.
4. Physical Evidence Index varre o PDF inteiro.
5. Dentro dos ranges conhecidos, evidências usam estrutura de tabela.
6. Fora dos ranges, evidências são mantidas como contexto bruto.
7. Entity Relation Graph conecta orçamento, principais, auxiliares e insumos por `codigo+banco`.
8. Fragment Ownership Graph atribui fragmentos físicos a donos prováveis.
9. Field Consensus recebe suporte de ownership quando o valor pertence ao mesmo cluster.
10. Strict but Realistic Closure audita se a linha fecha por prova forte ou consenso forte.

## Fechamento realista

A versão não exige evidência perfeita isolada para tudo. Ela aceita fechamento por consenso forte quando:

- as entidades relacionadas concordam;
- não há conflito grave;
- os campos têm validação de tipo;
- a matemática confirma quando aplicável;
- a evidência física ou cruzada existe;
- o fragmento não pertence a outra linha fechada.

## Evidência fora da tabela

Se o `codigo+banco` aparece fora dos ranges do orçamento/composições, a v43 não tenta forçar colunas. Ela coleta a linha bruta, identifica valores/unidades próximos e registra como evidência mais fraca, útil para consenso e não como prova automática absoluta.
