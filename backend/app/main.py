import os
import sys
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from app.api.admin import router as admin_router
from app.api.ask import router as ask_router
from app.api.assess import router as assess_router
from app.api.classify import router as classify_router
from app.api.history import router as history_router
from app.config import app_env
from app.rate_limit import limiter


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Railway injects RAILWAY_ENVIRONMENT_NAME on every deploy. Running there
    # without APP_ENV=production still works (the quota counts the instance's
    # own "dev" rows, so it stays protected) but every trace is mislabelled,
    # so say so loudly at boot rather than let it be discovered in the data.
    if os.environ.get("RAILWAY_ENVIRONMENT_NAME") and app_env() != "production":
        print(
            "ACTION REQUIRED: running on Railway with APP_ENV="
            f"{app_env()!r}. Set APP_ENV=production on the service so "
            "query_trace rows and the daily quota are attributed correctly.",
            file=sys.stderr,
        )
    yield


def _docs_kwargs(env: str) -> dict[str, str | None]:
    """OpenAPI surface per environment. Production exposes no schema: /docs,
    /redoc and /openapi.json are all off, so a public URL advertises nothing
    about request shapes. Everywhere else keeps FastAPI's defaults."""
    if env == "production":
        return {"docs_url": None, "redoc_url": None, "openapi_url": None}
    return {}


app = FastAPI(lifespan=lifespan, **_docs_kwargs(app_env()))
app.state.limiter = limiter
app.include_router(classify_router)
app.include_router(ask_router)
app.include_router(history_router)
app.include_router(admin_router)
app.include_router(assess_router)


def _error(status_code: int, code: str, message: str, request_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "request_id": request_id}},
    )


@app.exception_handler(RateLimitExceeded)
def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return _error(
        status.HTTP_429_TOO_MANY_REQUESTS,
        "rate_limited",
        "Too many requests. Please slow down.",
        str(uuid4()),
    )


@app.exception_handler(HTTPException)
def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    # `detail` here is always a code WE chose (see app/api/*), never library or
    # driver text, so echoing it leaks nothing.
    return _error(exc.status_code, str(exc.detail), str(exc.detail), str(uuid4()))


@app.exception_handler(RequestValidationError)
def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return _error(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "validation_error",
        "Request failed validation.",
        str(uuid4()),
    )


@app.exception_handler(Exception)
def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    """Last line of defence. The client gets an opaque id; the real exception
    goes to the server log only.

    This is the handler that keeps DATABASE_URL, OPENAI_API_KEY and SQL strings
    out of HTTP responses - an unhandled DB error would otherwise surface a
    connection string in its message.
    """
    request_id = str(uuid4())
    print(f"[{request_id}] unhandled error: {exc!r}", file=sys.stderr)
    return _error(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "internal_error",
        "Something went wrong.",
        request_id,
    )


@app.get("/health")
def health():
    # `environment` is the deploy smoke test: hit /health on Railway and read
    # "production". Harmless to expose; it is one of three fixed words.
    return {"status": "ok", "environment": app_env()}
