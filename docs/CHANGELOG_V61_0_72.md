# v61.0.73-inline-budget-totals-strategic-diff-recovery

## Objetivo

Aumentar a fidelidade documental e a taxa de extração sem inflar o JSON final: cada valor público deve continuar sendo token declarado do PDF; as ferramentas novas apenas inventariam, comparam, sinalizam e organizam evidências.

## Mudanças principais

- Adicionado `budget_total_lines.py`:
  - cria `orcamento_sintetico.linhas_totais` para `TOTAL GERAL`, metas e submetas;
  - restaura o token pt-BR do total geral, por exemplo `698159,11` → `698.159,11`;
  - não recalcula totais nem altera valores públicos por soma em cadeia.
- Adicionado `light_reextraction_diff_scan.py`:
  - faz varredura leve PDF × JSON procurando anchors `código + banco` presentes no PDF e ausentes no JSON;
  - diagnóstico apenas, sem escrita de campos públicos;
  - evita falsos positivos como linha de referência `SINAPI - 04/2025`.
- Melhorado `compact_correction_document.py`:
  - `resumo_final_curto` agora é limpo, direto e mais útil para Lovable;
  - problemas e patches carregam local, composição, página, campo, ação recomendada e `crop_hint` quando houver.
- Integrado tudo ao `integrity_orchestrator.py`, nos fluxos reais exportados para browser/Lovable.
- Métricas finais adicionadas:
  - `budget_total_line_count`;
  - `budget_has_total_geral_line`;
  - `light_diff_scan_status`;
  - `light_diff_scan_potential_missing_code_count`.

## Política mantida

- Valor público = valor declarado no PDF.
- Cálculo = auditoria/validação, nunca sobrescrita pública.
- Reextração leve encontra diferenças, mas não inventa valores.
- Documento de correção final deve ser curto, rico em localização e sem logs pesados.

## Validação

- `pytest parser_browser`: 234 passed.
- `pytest api_docling`: 4 passed.
- `node --check` nos workers e browser demo: OK.
- `quality_safety_scan`: OK.
- Fluxo real validado com PDF real + JSON problemático v61 e JSON limpo v71.
