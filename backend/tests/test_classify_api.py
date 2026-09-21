from fastapi.testclient import TestClient

from app.config import PER_MINUTE_LIMIT
from app.main import app
from tests._auth import auth_headers

client = TestClient(app)

CREDIT_SCORING = {
    "intended_purpose": "Score loan applicants' creditworthiness",
    "use_case": "CREDITWORTHINESS_SCORING",
    "affects_natural_persons": True,
}


def test_classify_high_risk_creditworthiness():
    response = client.post("/classify", json=CREDIT_SCORING, headers=auth_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["risk_tier"] == "HIGH_RISK"
    assert body["triggering_article"] == "Annex III, point 5(b)"


def test_classify_fraud_detection_carve_out():
    response = client.post(
        "/classify",
        json={
            "intended_purpose": "Detect fraudulent transactions",
            "use_case": "FINANCIAL_FRAUD_DETECTION",
            "affects_natural_persons": True,
        },
        headers=auth_headers(),
    )
    assert response.status_code == 200
    assert response.json()["risk_tier"] == "MINIMAL_RISK"


def test_classify_invalid_request_returns_422():
    response = client.post(
        "/classify",
        json={
            "intended_purpose": "",
            "use_case": "OTHER",
            "affects_natural_persons": True,
        },
        headers=auth_headers(),
    )
    assert response.status_code == 422


# --- the endpoint is gated like /ask -------------------------------------


def test_classify_unauthenticated_is_401_before_validation():
    # Empty body on purpose: the token check must run BEFORE body validation,
    # so an anonymous caller gets 401, never a 422 that describes the schema.
    response = client.post("/classify", json={})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_classify_wrong_secret_is_401():
    response = client.post(
        "/classify", json=CREDIT_SCORING, headers=auth_headers(secret="not-the-key")
    )
    assert response.status_code == 401


def test_classify_per_minute_limit_returns_429():
    limit = int(PER_MINUTE_LIMIT.split("/")[0])
    codes = [
        client.post(
            "/classify", json=CREDIT_SCORING, headers=auth_headers()
        ).status_code
        for _ in range(limit + 1)
    ]
    assert codes[:limit] == [200] * limit
    assert codes[-1] == 429
