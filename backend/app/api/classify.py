"""POST /classify - the deterministic risk-tier verdict.

Pure CPU and free to run, but on a public URL "free" must not mean "open":
the endpoint sits behind the same short-lived BFF service token /ask uses,
and the same per-minute burst guard. The frontend reaches it only through a
server-side route that mints that token; a browser never holds it.
"""

from fastapi import APIRouter, Request

from app.api.deps import Caller, ServiceToken
from app.classifier.engine import classify
from app.classifier.models import ClassificationResult, SystemDescription
from app.config import PER_MINUTE_LIMIT
from app.rate_limit import limiter

router = APIRouter()


@router.post("/classify", response_model=ClassificationResult)
@limiter.limit(PER_MINUTE_LIMIT)
def classify_system(
    request: Request,  # required by slowapi to key the limit
    system: SystemDescription,
    caller: Caller = ServiceToken,
) -> ClassificationResult:
    return classify(system)
