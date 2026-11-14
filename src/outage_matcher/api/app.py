"""FastAPI app: `POST /ask` and `GET /health`.

The app takes an agent factory so tests can inject a fake. Until the real agent is wired in
(M4), the default factory returns None and `/ask` answers 503.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from outage_matcher.api.models import AskRequest, AskResponse

logger = logging.getLogger(__name__)


class Agent(Protocol):
    def ask(self, question: str) -> AskResponse: ...


AgentFactory = Callable[[], Agent | None]


def no_agent() -> Agent | None:
    """Default factory until the real agent is wired in."""
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

    @app.exception_handler(Exception)
    async def on_unhandled(_: Request, exc: Exception) -> JSONResponse:
        # Log the traceback server side; the client only sees a generic message.
        logger.error("unhandled error", exc_info=exc)
        return _error(500, "internal server error")

    return app
