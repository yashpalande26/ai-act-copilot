from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    # conftest forces APP_ENV=test; on Railway this field reads "production".
    assert response.json() == {"status": "ok", "environment": "test"}
