# 03 — Base config configurável

## Modelo simples

```text
effective_base_config = base_config_default_do_ZIP + admin_config_overlay + user_config_overlay
```

O ZIP é somente o padrão publicado pela plataforma. Ele não deve ser editado em runtime.

## Admin

O admin pode ter uma cópia completa do base_config com adições, ou um overlay parcial. Na execução, o Lovable envia isso ao parser como `admin_config_overlay`.

## Usuário/projeto

O usuário/projeto pode ter um overlay menor, com bancos personalizados, aliases locais ou unidades aceitas.

## Documento de enriquecimento

O parser gera sugestões. O Lovable/Admin decide se aceita. Ao aceitar, salva em admin/user overlay para próximas execuções.
