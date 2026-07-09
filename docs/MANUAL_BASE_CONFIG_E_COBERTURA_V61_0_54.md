# Manual Lovable — Base Config e Cobertura v61.0.54

## 1. Base config no browser/Lovable

O arquivo `db/base_config.json` dentro do ZIP é o **default da plataforma**. Ele serve como fallback e contrato publicado junto com o bundle.

Como o ZIP é extraído de novo a cada execução, ele não deve ser usado como banco persistente de configurações. A persistência deve ficar no Lovable/backend.

### Fluxo simples

```txt
base_config efetivo =
  base_config do ZIP
  + overlay/cópia do administrador
  + overlay do usuário/projeto
```

### Admin config

O administrador pode salvar:

- uma cópia completa do base_config com adições; ou
- um overlay pequeno só com mudanças.

Os dois modelos funcionam porque o parser faz `deep merge` em memória.

### User config

O overlay do usuário deve ser pequeno e focado em:

- banco personalizado;
- aliases locais;
- templates de tabela personalizados;
- unidades aceitas a partir do `documento_enriquecimento`.

Não deve conter endpoint, timeout, API key, política de cache ou regras internas críticas.

### Payload documental

O payload continua sendo apenas sobre o documento:

- nome e páginas;
- ranges;
- páginas seed;
- headers observados;
- samples/primeira linha;
- contexto documental.

## 2. Documento de cobertura

O parser agora gera:

```txt
analise_orcamentaria.extraction_coverage_report
```

Ele responde:

- quantos itens do orçamento existem no JSON;
- quantas ocorrências físicas do PDF foram mapeadas;
- quantas linhas candidatas ficaram sem mapeamento;
- como o SICRO foi classificado;
- quais casos precisam revisão Lovable.

## 3. Como Lovable deve consumir

### Se `budget.status = ok`
O orçamento foi coberto pelas evidências físicas disponíveis.

### Se existem `unmapped_physical_candidates`
Mostrar para revisão apenas quando a família for `budget`, `composition` ou `sicro` dentro de intervalos conhecidos. Candidatos em `raw_auxiliary_context` são evidência auxiliar e normalmente não bloqueiam.

### SICRO
O Lovable deve revisar:

- composição SICRO com item mas sem referência no sintético;
- item SICRO no sintético sem composição encontrada;
- auxiliar global SICRO não usada, se isso for relevante para o usuário.

Não reclassificar automaticamente principal/auxiliar.
