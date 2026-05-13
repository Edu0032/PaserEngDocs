# Changelog — v61.0.35 Candidate Profile Consensus Engine

## Objetivo

Esta versão adiciona um orquestrador de decisão para organizar todos os perfis e evidências já extraídos: Docling, PyMuPDF, Evidence Graph, cruzamento orçamento × composições, ownership de vizinhos, reparse seletivo, validações matemáticas e filtros de poluição.

O foco é somar precisão sem piorar os resultados já bons: a correção só é aplicada quando o candidato vence por consenso; em caso de dúvida, o JSON é mantido e a pendência vai para auditoria/correction document.

## Principais alterações

- Novo módulo `candidate_profile_consensus_engine.py`.
- Integração do consensus engine no merge final, após o Selective Field Reparse Executor e antes do targeted recovery pesado.
- Orquestração dos candidatos vindos de:
  - valor atual conservador;
  - descrições confirmadas por `codigo|banco`;
  - cruzamento orçamento sintético × composições;
  - subtração de fragmentos pertencentes ao item anterior/próximo;
  - quarentena de poluição textual;
  - ownership resolver.
- Reverse repair mais seguro: descrição longa/poluída pode ser substituída por descrição menor e limpa se os fragmentos removidos forem explicados pelos vizinhos.
- Novo suporte de merge entre `base_config` do administrador e `base_config` do usuário.
- HTML de testes atualizado com aba “Consenso de perfis”.
- Documentação Lovable adicionada para payload, JSON final, correction document, enrichment, base_config/interface e bundle.

## Regra de segurança

```text
Se o candidato novo não provar que é melhor que o valor atual, o valor atual permanece.
```

## Testes principais

- ANP 01 contaminado é reduzido para `AQUISIÇÃO DE ASFALTO DILUIDO CM-30` quando os fragmentos de cima/baixo são explicados por itens vizinhos.
- Descrição curta e limpa não recebe patch agressivo.
- Candidato que contém descrição de vizinho não substitui campo limpo.
- Merge de base_config admin + usuário preserva regras globais e adiciona perfil personalizado.
