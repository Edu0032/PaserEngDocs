# Pendências declaradas — v61.0.30

## Não implementado nesta versão

- Não foi executado Docling real externo neste ambiente. A API/contrato/worker foram testados localmente; a chamada real depende do serviço ativo no Lovable/Render.
- A separação completa do monólito `parser_browser/app/parser/compositions.py` continua pendente, pois é uma refatoração grande e de risco. O SICRO permanece isolado no motor v20; não foi mexido na lógica interna do motor.
- Ainda não há benchmark estatístico com dezenas de PDFs reais. A v61.0.30 adiciona testes controlados que comprovam os ganhos em pontos críticos, mas o painel de acurácia por campo fica para uma etapa própria.
