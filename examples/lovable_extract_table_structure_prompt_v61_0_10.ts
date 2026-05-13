// Template de prompt para Lovable — v61.0.11
// Use este arquivo como referência para a Edge Function que pede à IA a estrutura das tabelas.

const BUDGET_CANONICALS = [
  'item_agregador', 'codigo', 'fonte', 'descricao', 'und', 'quant',
  'custo_unitario_sem_bdi', 'custo_unitario_com_bdi', 'custo_parcial', 'custo_total',
] as const;

const COMP_CANONICALS = [
  'controle_linha', 'codigo', 'banco', 'descricao', 'tipo', 'und', 'quant', 'valor_unit', 'total',
] as const;

export function buildTableStructurePrompt(kind: 'budget' | 'composition', candidatePagesText: string) {
  const canonicals = kind === 'budget' ? BUDGET_CANONICALS : COMP_CANONICALS;
  return `Você analisa páginas de orçamentos brasileiros de obras. Sua tarefa é identificar ESTRUTURA DE TABELA, não extrair todos os dados.

TIPO: ${kind === 'budget' ? 'ORÇAMENTO SINTÉTICO' : 'COMPOSIÇÕES ANALÍTICAS SINAPI-LIKE'}
CANÔNICOS VÁLIDOS: ${canonicals.join(', ')}

REGRAS CRÍTICAS:
1. observed_headers deve seguir a ordem visual exata da esquerda para a direita.
2. Não reordene por canônico ou alfabeto.
3. Não invente colunas.
4. sample_text deve ser uma célula real da primeira linha do corpo.
5. Preserve números no formato brasileiro: 1,0000000; 1,2680; 52.365,69.
6. Preserve códigos: 74209/001; CP - 120; ANP 01; CADM.01; COMP.JCO.3.
7. Textos institucionais, BDI, datas, órgão e título vão em non_column_context ou table_parent_header.

ORÇAMENTO SINTÉTICO:
- item_agregador: ITEM. Ex.: 1.1.1.
- codigo: CÓDIGO. Ex.: 74209/001.
- fonte: FONTE/BANCO. Ex.: SINAPI, SICRO3, PRÓPRIO.
- descricao: DESCRIÇÃO/ESPECIFICAÇÕES DOS SERVIÇOS.
- und: UND/UNIDADE. Ex.: m².
- quant: QUANT./QUANTIDADE.
- custo_unitario_sem_bdi: S/ B.D.I dentro de CUSTO UNITÁRIO.
- custo_unitario_com_bdi: C/ B.D.I dentro de CUSTO UNITÁRIO.
- custo_parcial: CUSTO PARCIAL.
- custo_total: CUSTO TOTAL.

COMPOSIÇÕES SINAPI-LIKE:
- controle_linha: primeira coluna; header pode ser vazio ou número de item; conteúdo é Composição, Composição Auxiliar ou Insumo.
- codigo: Código da linha.
- banco: SINAPI, PRÓPRIO, SICRO3 etc.
- descricao: texto principal da linha.
- tipo: coluna Tipo; estrutural, ajuda a cortar descrição.
- und: unidade.
- quant: quantidade.
- valor_unit: valor unitário.
- total: total.

SICRO:
Não tente mapear seções A-F. Apenas indique sicro_present=true se detectar SICRO. O parser trata SICRO internamente.

PÁGINAS/TEXTO:
${candidatePagesText}`;
}
