# Changelog — v61.0.34

`v61.0.39-deep-area-sweep-iterative-closure`

## Foco

A versão adiciona o **Description Ownership Resolver**, uma camada que decide se um fragmento de descrição pertence ao item alvo ou aos itens vizinhos. O objetivo é aumentar a taxa de acerto sem permitir recuperações agressivas que misturam descrições de linhas diferentes.

## Principais mudanças

- Adicionado `parser/description_ownership_resolver.py`.
- O reparse seletivo agora usa contexto de item anterior/próximo no orçamento sintético.
- O executor corrige descrições já contaminadas quando existe uma descrição limpa e segura do mesmo `codigo|banco` nas composições.
- O targeted recovery recebe `neighbor_context` no worker.
- O recovery local penaliza candidatos que contêm descrição confirmada da linha de cima ou da linha de baixo.
- O recovery local usa perfil de espaçamento vertical da página para limitar continuação de linha.
- O recovery local usa ocupação da célula de descrição para evitar anexar fragmentos a descrições curtas e já completas.
- Teste travado para o caso `ANP 01`: a descrição correta permanece `AQUISIÇÃO DE ASFALTO DILUIDO CM-30`, sem puxar ruído do item anterior ou do próximo.

