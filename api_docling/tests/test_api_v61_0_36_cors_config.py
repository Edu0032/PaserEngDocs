import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _create_app(monkeypatch, *, key="secret"):
    monkeypatch.setenv("API_PDF_ENV", "production")
    monkeypatch.setenv("API_PDF_CORS_ALLOW_ORIGINS", "*")
    monkeypatch.setenv("API_PDF_API_KEY", key)
    monkeypatch.setenv("API_PDF_API_KEY_HEADER", "x-api-key")
    monkeypatch.setenv("DOCLING_TIMEOUT_SECONDS", "120")
    monkeypatch.setenv("API_PDF_DOCS_ENABLED", "true")
    sys.path.insert(0, str(ROOT))
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
    import app.config.settings as settings_mod
    import app.api as api_mod
    importlib.reload(settings_mod)
    importlib.reload(api_mod)
    created = api_mod.create_app()
    try:
        sys.path.remove(str(ROOT))
    except ValueError:
        pass
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
    return created


def test_cors_preflight_allows_lovable_with_x_api_key(monkeypatch):
    from fastapi.testclient import TestClient
    app = _create_app(monkeypatch)
    client = TestClient(app)
    response = client.options(
        "/docling/extract-table-structure",
        headers={
            "Origin": "https://example.lovable.app",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-api-key,content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "*"
    assert "POST" in response.headers.get("access-control-allow-methods", "")
    assert "x-api-key" in response.headers.get("access-control-allow-headers", "").lower()


def test_docling_timeout_accepts_render_env_alias(monkeypatch):
    app = _create_app(monkeypatch)
    assert app.state.settings.docling_timeout_seconds == 120


def test_protected_endpoint_still_requires_api_key(monkeypatch):
    from fastapi.testclient import TestClient
    app = _create_app(monkeypatch)
    client = TestClient(app)
    assert client.get("/docling/runtime").status_code == 401
    assert client.get("/docling/runtime", headers={"x-api-key": "secret"}).status_code == 200


def test_health_and_healthz_are_public(monkeypatch):
    from fastapi.testclient import TestClient
    app = _create_app(monkeypatch)
    client = TestClient(app)
    assert client.get("/health").status_code == 200
    assert client.get("/healthz").status_code == 200
