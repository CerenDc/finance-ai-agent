from fastapi import FastAPI

from app.api.finance import router as finance_router

app = FastAPI(
    title="Finance AI API",
    version="0.1.0"
)

app.include_router(finance_router)


@app.get("/health")
def health():
    return {
        "status": "ok"
    }