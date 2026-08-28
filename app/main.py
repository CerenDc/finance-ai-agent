import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.agent.finance_graph import create_finance_graph
from app.api.agent import router as agent_router
from app.api.finance import router as finance_router


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with create_finance_graph() as graph:
        app.state.finance_graph = graph
        yield


app = FastAPI(
    title="Finance AI API",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(finance_router)
app.include_router(agent_router)


@app.exception_handler(SQLAlchemyError)
async def database_error_handler(_, exc: SQLAlchemyError) -> JSONResponse:
    logger.exception("Finance database operation failed", exc_info=True)
    return JSONResponse(
        status_code=503,
        content={"detail": "Finance database unavailable"},
    )


@app.get("/health")
def health():
    return {
        "status": "ok"
    }
