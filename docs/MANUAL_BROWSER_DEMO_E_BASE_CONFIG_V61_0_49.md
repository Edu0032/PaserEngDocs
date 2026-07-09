# Manual — HTML Demo, Payload e Base Config v61.0.49

## 1. Problema corrigido

Se o log do navegador mostrar:

```txt
Nenhum arquivo de configuração encontrado em /home/pyodide/db/base_config.json
```

isso significa que o arquivo `api_pdf_pyodide_src.zip` usado pelo worker não continha a pasta `db/`. Na v61.0.49, o ZIP interno do Pyodide inclui `db/base_config.json` e `db/base_config.d/`.

## 2. Contrato correto

### Base config

Contém informações fixas e administradas pela plataforma:

- políticas de parser;
- políticas de Docling;
- endpoint/caminho/timeout/cache quando aplicável;
- normalizer;
- targeted recovery;
- unidades conhecidas;
- aliases globais;
- padrões universais de códigos;
- contratos de saída;
- regras de segurança e qualidade.

### Payload Lovable

Contém somente informações do documento:

- nome do arquivo;
- número de páginas;
- ranges do orçamento e composições;
- páginas seed;
- headers observados;
- associação header → campo canônico;
- samples/first row text;
- contexto e ruídos específicos do documento.

O payload **não** deve carregar:

- `docling_api_url`;
- `docling_api_key`;
- `docling_timeout_ms`;
- `normalizer_*`;
- `docling_seed_pdf_policy`;
- `bypass_cache`;
- `clear_docling_cache_before_run`;
- `targeted_recovery_max_pages_per_batch`;
- `runtime`;
- `performance`;
- `output_options`;
- `parser_contract`;
- `base_id`.

Esses campos pertencem ao runtime/base_config/admin da plataforma.

## 3. Como testar pelo HTML

1. Suba a API Docling:

```bash
cd api_docling
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

2. Suba o HTML demo:

```bash
cd parser_browser/browser/demo
python -m http.server 5500
```

3. Abra:

```txt
http://127.0.0.1:5500/index.html
```

4. Configure os campos da interface:

```txt
Endpoint Docling: http://127.0.0.1:8000/docling/extract-table-structure
Budget seed: 2
Composition seed: 9
Budget início/fim: 2–4
Composições início/fim: 9–139
Timeout Docling: 240000
Targeted recovery págs/lote: 12
```

5. Clique:

```txt
Aplicar campos no payload
Validar payload
Testar Docling com seed
Executar fluxo completo browser
```

## 4. Logs esperados

Durante a execução, procure:

```txt
[normalizer-local] exports ok ... version=v61.0.50-composition-cascade-and-output-sanity
[seed-pdf] ... sent_pdf_kind=seed_pdf
[parser-budget] iniciado
[physical-evidence] iniciado
[physical-evidence] concluído
[outputs] documentos organizados
Fluxo completo browser concluído
```

## 5. Abas do HTML

- Preview orçamento: prévia do orçamento sintético.
- JSON final: resultado principal.
- Correção: `documento_correcao`.
- Evidências: `documento_evidencias`.
- Enriquecimento: `documento_enriquecimento`.
- Docling/seed: resposta da API Docling e metadados do mini-PDF seed.
- Budget stage: estágio intermediário do orçamento.
- Compositions stage: estágio intermediário das composições.
- Acurácia / Reparse / Consenso / Debug overlay: diagnósticos técnicos.

## 6. Regra para o Lovable

O Lovable deve montar o payload com dados do documento e enviar as opções de runtime separadamente ao worker/cliente. O Lovable não deve editar políticas internas de API, cache, timeout, normalizer ou targeted recovery dentro do payload documental.
