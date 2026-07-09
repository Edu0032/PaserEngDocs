# API Docling: execução local e hospedagem genérica

Este arquivo permanece como contrato de compatibilidade para a suíte de testes.

## Execução local

```bash
cd api_docling
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

## Execução em servidor Python

```bash
gunicorn app.main:app -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT --workers 1 --timeout 180
```

## Túnel local para testes de integração

```bash
cloudflared tunnel --url http://127.0.0.1:8000
```

## Observação

O serviço não depende de uma plataforma específica. A aplicação pode ser executada localmente, por túnel ou em hospedagem compatível com ASGI.
