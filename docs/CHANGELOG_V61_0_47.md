# Changelog — v61.0.48-output-contract-and-human-error-correction

## Objetivo da versão

A v61.0.47 endurece a extração do núcleo do orçamento: orçamento sintético, composições analíticas e campos matemáticos. O foco não é depender de memória de cálculo, curva ABC, cronograma ou BDI. Essas seções continuam opcionais e apenas auxiliares. O parser deve funcionar bem mesmo quando o PDF contém somente orçamento sintético e composições.

## Melhorias principais

- Novo módulo `local_line_cascade_repair.py`.
- Novo módulo `output_documents_organizer.py`.
- Novo endpoint Pyodide/Lovable `run_core_extraction_accuracy_flow_file_json`.
- O worker Lovable passa a chamar o fluxo v47 de enriquecimento e fechamento, que roda índice físico, cascata local, closure e organização dos outputs.
- Campos matemáticos vazios agora recebem uma busca local agressiva em torno da linha conhecida por `codigo+banco`.
- A matemática continua sem escrever valores públicos sozinha: ela calcula expectativa e procura esse valor no PDF físico ou nas evidências extraídas.
- Seções auxiliares são opcionais e não são fonte primária de verdade.
- Memória de cálculo pode ajudar com contexto/quantidade, mas não sobrescreve preço, custo parcial, total ou BDI.
- `documento_enriquecimento` passa a ser emitido no JSON final para orientar o Lovable sobre evidências, cadeias e enriquecimentos.
- `analise_orcamentaria.outputs_contract` explica os caminhos dos principais outputs.

## Filosofia de extração

1. Extração agressiva.
2. Correção inteligente.
3. Fechamento por evidência.
4. Validação matemática sempre que aplicável.
5. Seções auxiliares ajudam, mas não são obrigatórias.
6. O valor público precisa sair do PDF ou de evidência extraída/cruzada, nunca apenas de cálculo isolado.

## Campos priorizados

- `quant`
- `valor_unit`
- `total`
- `custo_unitario_sem_bdi`
- `custo_unitario_com_bdi`
- `custo_parcial`
- `custo_total`
- `und`
- `descricao` / `especificacao`

## Novo fluxo de cascata local

Quando uma linha não fecha:

1. O parser já conhece `codigo+banco` e família da linha.
2. Calcula expectativas matemáticas quando possível.
3. Procura candidatos no índice físico do PDF.
4. Procura o valor esperado na mesma ocorrência física do `codigo+banco`.
5. Respeita política de seção.
6. Valida tipo do campo.
7. Aplica apenas se o candidato se encaixar com a linha.
8. Reexecuta o closure.

## Segurança

- Não copia quantidade entre orçamento e composição sem evidência forte.
- Não usa memória de cálculo para preço/custo/total.
- Não permite que `CM-30` vire unidade `cm`.
- Não transforma código com barra ou letras em número monetário.
- Não revalida SICRO com regra SINAPI-like. O motor `sicro_only` permanece autoritativo.
