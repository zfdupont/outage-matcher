"""FastAPI app: `POST /ask` and `GET /health`.

The app takes an agent factory so tests can inject a fake. `outage-matcher serve` passes the
factory for the real agent; the default factory returns None and `/ask` then answers 503.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol

import anthropic
import psycopg
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from outage_matcher.agent.models import RetrievalError
from outage_matcher.api.models import AskRequest, AskResponse

logger = logging.getLogger(__name__)


class Agent(Protocol):
    def ask(self, question: str) -> AskResponse: ...


AgentFactory = Callable[[], Agent | None]


def no_agent() -> Agent | None:
    """Default factory: no agent, so `/ask` answers 503."""
    return None


def _error(status: int, message: str, detail: list[dict[str, str]] | None = None) -> JSONResponse:
    error: dict[str, object] = {"status": status, "message": message}
    if detail:
        error["detail"] = detail
    return JSONResponse({"error": error}, status_code=status)


def create_app(agent_factory: AgentFactory = no_agent) -> FastAPI:
    app = FastAPI(title="Outage Matcher", version="0.1.0")
    # Built on first use so a slow or failing factory cannot stop the app from starting.
    holder: dict[str, Agent | None] = {}

    def get_agent() -> Agent | None:
        if "agent" not in holder:
            holder["agent"] = agent_factory()
        return holder["agent"]

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/ask", response_model=AskResponse)
    def ask(request: AskRequest) -> AskResponse | JSONResponse:
        agent = get_agent()
        if agent is None:
            return _error(503, "agent is not available yet")
        return agent.ask(request.question)

    @app.exception_handler(RequestValidationError)
    async def on_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        problems = [
            {"field": ".".join(str(p) for p in e["loc"][1:]) or "body", "message": e["msg"]}
            for e in exc.errors()
        ]
        return _error(422, "invalid request", problems)

    @app.exception_handler(StarletteHTTPException)
    async def on_http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _error(exc.status_code, str(exc.detail))

    @app.exception_handler(RetrievalError)
    async def on_retrieval_error(_: Request, exc: RetrievalError) -> JSONResponse:
        logger.error("search backend failed: %s", exc)
        return _error(503, "search backend unavailable")

    @app.exception_handler(psycopg.OperationalError)
    async def on_database_error(_: Request, exc: psycopg.OperationalError) -> JSONResponse:
        logger.error("database unavailable: %s", exc)
        return _error(503, "search backend unavailable")

    @app.exception_handler(anthropic.APIError)
    async def on_model_error(_: Request, exc: anthropic.APIError) -> JSONResponse:
        logger.error("model API call failed: %s", exc)
        return _error(502, "model API call failed")

    @app.exception_handler(Exception)
    async def on_unhandled(_: Request, exc: Exception) -> JSONResponse:
        # Log the traceback server side; the client only sees a generic message.
        logger.error("unhandled error", exc_info=exc)
        return _error(500, "internal server error")

    return app
