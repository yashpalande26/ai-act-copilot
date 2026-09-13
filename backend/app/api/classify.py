from fastapi import APIRouter

from app.classifier.engine import classify
from app.classifier.models import ClassificationResult, SystemDescription

router = APIRouter()


@router.post("/classify", response_model=ClassificationResult)
def classify_system(system: SystemDescription) -> ClassificationResult:
    return classify(system)
