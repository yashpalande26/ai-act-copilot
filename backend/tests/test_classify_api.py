from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_classify_high_risk_creditworthiness():
    response = client.post(
        "/classify",
        json={
            "intended_purpose": "Score loan applicants' creditworthiness",
            "use_case": "CREDITWORTHINESS_SCORING",
            "affects_natural_persons": True,
        },
    )
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
    )
    assert response.status_code == 422
