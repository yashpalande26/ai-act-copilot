import sys
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from app.api.ask import router as ask_router
from app.api.classify import router as classify_router
from app.rate_limit import limiter

app = FastAPI()
app.state.limiter = limiter
app.include_router(classify_router)
app.include_router(ask_router)


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
    return {"status": "ok"}
