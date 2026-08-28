from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.agent.finance_graph import create_finance_graph
from app.api.agent import router as agent_router
from app.api.finance import router as finance_router


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


@app.get("/health")
def health():
    return {
        "status": "ok"
    }
