# Changelog — v61.0.27

`v61.0.39-deep-area-sweep-iterative-closure`

## Foco

Hardening do fluxo existente, sem trocar a arquitetura central. O processamento SICRO permanece exclusivo do motor SICRO v20; o parser principal só adapta o resultado de forma não destrutiva.

## Implementado

- Corrigido regex SICRO com caractere invisível `\x08`; padrões de seção foram movidos para `parser/sicro_section_patterns.py`.
- Adicionado scanner `tools/quality_safety_scan.py` contra caracteres invisíveis em regex e hardcodes perigosos de profissão/serviço no código de aplicação.
- Corrigidos `api_docling/requirements.txt`, `requirements-server.txt` e `render.yaml`; o deploy oficial agora sobe apenas a API Docling seed-only.
- Criado contrato compartilhado `payload_contract.py` em browser/API para limpar o payload Docling e preservar apenas contexto variável do documento.
- API Docling ganhou `/docling/validate-payload` para Lovable validar payload sem rodar Docling.
- Metadata da API Docling agora registra `payload_usage`, deixando claro se headers, canônicos e first row samples foram usados.
- `fixed_contract`, `parser_contract`, runtime e chaves de API não são encaminhados no payload de estrutura do Docling.
- Adicionado `BudgetMathValidator` para marcar linhas do orçamento como candidatas a rechecagem quando `quantidade × custo_unitário` divergir do `custo_parcial`.
- `selective_reparse_plan` passou a incluir `action`, `family`, `table_family` e página quando disponível, tornando os alvos mais diretamente consumíveis pelo targeted recovery.
- Renomeadas metadatas internas antigas `normalizer_api` do normalizer local para `normalizer_local`, evitando confusão com API externa.
- Novos testes de hardening, payload limpo, deploy Docling, scanner de segurança, orçamento matemático e espelhamento do contrato de payload entre browser/API.

## Pendências assumidas

- Não foi feita a extração completa de todos os módulos comuns para um pacote Python externo único, porque isso exigiria alterar paths de execução no Pyodide e no Render. Nesta versão foi implementado um contrato compartilhado mínimo e testado (`payload_contract.py`) nos dois runtimes.
- O monólito `compositions.py` não foi quebrado totalmente, para reduzir risco de regressão. Foi feita a primeira separação segura dos sinais SICRO em módulo dedicado.
