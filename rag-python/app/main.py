from __future__ import annotations

import logging

import uvicorn
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse

from .agent_orchestrator import AgentOrchestrator
from .callbacks import JavaCallbackClient
from .config import Settings
from .embedding import EmbeddingService
from .es_store import ElasticsearchStore
from .ingest_worker import IngestWorker
from .llm import LlmAnswerService
from .models import RagQueryRequest
from .security import internal_token_header, require_internal_token

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

settings = Settings.load()
es_store = ElasticsearchStore(settings)
embedding_service = EmbeddingService(settings)
llm_service = LlmAnswerService(settings)
callback_client = JavaCallbackClient(settings)
agent_orchestrator = AgentOrchestrator(
    embedding_service=embedding_service,
    es_store=es_store,
    llm_service=llm_service,
    default_top_k=settings.query_default_top_k,
    max_top_k=settings.query_max_top_k,
)
ingest_worker = IngestWorker(
    settings=settings,
    es_store=es_store,
    embedding_service=embedding_service,
    callback_client=callback_client,
)

app = FastAPI(title="PaiSmart Python RAG", version="1.0.0")


@app.on_event("startup")
async def on_startup() -> None:
    await ingest_worker.start()
    logger.info(
        "Python RAG service started. host=%s port=%s ingestTopic=%s",
        settings.host,
        settings.port,
        settings.kafka_ingest_topic,
    )


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await ingest_worker.stop()


@app.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
async def ready() -> JSONResponse:
    ready_state = {
        "es": False,
        "kafkaIngestTopic": settings.kafka_ingest_topic,
    }
    try:
        ready_state["es"] = es_store.ping()
    except Exception:
        ready_state["es"] = False
    status_code = 200 if ready_state["es"] else 503
    return JSONResponse(status_code=status_code, content=ready_state)


@app.post("/internal/v1/query")
async def internal_query(
    request: RagQueryRequest,
    x_internal_token: str | None = Depends(internal_token_header),
) -> dict:
    require_internal_token(settings.internal_token, x_internal_token)
    response = await agent_orchestrator.answer(request)
    return response.model_dump()


def run() -> None:
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    run()
