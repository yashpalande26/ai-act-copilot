from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    # conftest forces APP_ENV=test; on Railway this field reads "production".
    assert response.json() == {"status": "ok", "environment": "test"}


# --- OpenAPI surface is off in production ---------------------------------


def test_docs_available_outside_production():
    # The app under test was built with APP_ENV=test, so defaults apply.
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_docs_kwargs_disable_every_schema_route_in_production():
    from app.main import _docs_kwargs

    assert _docs_kwargs("production") == {
        "docs_url": None,
        "redoc_url": None,
        "openapi_url": None,
    }
    assert _docs_kwargs("dev") == {}
    assert _docs_kwargs("test") == {}
