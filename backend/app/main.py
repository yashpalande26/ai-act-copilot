from fastapi import FastAPI

from app.api.classify import router as classify_router

app = FastAPI()
app.include_router(classify_router)


@app.get("/health")
def health():
    return {"status": "ok"}
