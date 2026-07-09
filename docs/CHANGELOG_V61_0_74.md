# v61.0.75-correction-output-contract-and-review-index

## Mudanças principais

- Removidos exemplos específicos do documento de teste do `base_config` global e das superfícies ativas do bundle/docs.
- `light_reextraction_diff_scan` agora é occurrence-aware, evitando falso negativo quando um mesmo código aparece várias vezes.
- Debug pesado do orquestrador final deixou de ser gravado diretamente em `documento_correcao`.
- `clean_final_contract` agora envia relatório detalhado para `analise_orcamentaria.debug_recovery`.
- Adicionado `tools/release_integrity_scan.py` para validar SHA do bundle, versão de docs e hardcodes nocivos em superfícies ativas.
- Manifests Pyodide passam a ser atualizados com o SHA real do `api_pdf_pyodide_src.zip` no empacotamento.

## Política mantida

- Total de meta/submeta fica inline em `custo_total`.
- Total de item folha fica inline em `custo_parcial`.
- Scan diferencial só detecta conteúdo possivelmente deixado para trás; não escreve valor público sozinho.
- Correção final deve ser curta, acionável e com localização suficiente para Lovable abrir página/recorte.
