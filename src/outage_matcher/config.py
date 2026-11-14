"""Agent configuration read from environment variables (see `.env.example`)."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

DEFAULT_AGENT_MODEL = "claude-haiku-5-5"
DEFAULT_MAX_RETRIES = 2


@dataclass(frozen=True)
class AgentConfig:
    model: str = DEFAULT_AGENT_MODEL
    max_retries: int = DEFAULT_MAX_RETRIES


def load_config() -> AgentConfig:
    """Build the config: AGENT_MODEL overrides the model, AGENT_MAX_RETRIES the retry cap."""
    load_dotenv()
    model = os.environ.get("AGENT_MODEL") or DEFAULT_AGENT_MODEL
    raw = os.environ.get("AGENT_MAX_RETRIES")
    if raw is None or raw == "":
        return AgentConfig(model=model)
    try:
        retries = int(raw)
    except ValueError:
        raise ValueError(f"AGENT_MAX_RETRIES must be an integer, got {raw!r}") from None
    if retries < 0:
        raise ValueError(f"AGENT_MAX_RETRIES must be >= 0, got {retries}")
    return AgentConfig(model=model, max_retries=retries)
