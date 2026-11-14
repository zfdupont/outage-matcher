"""Agent configuration read from environment variables (see `.env.example`)."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

DEFAULT_AGENT_MODEL = "claude-haiku-5-5"
DEFAULT_MAX_RETRIES = 2  # graph-level: query rewrites after an irrelevant retrieval
DEFAULT_REQUEST_TIMEOUT = 60.0  # seconds per Anthropic API request
DEFAULT_API_MAX_RETRIES = 2  # SDK-level: automatic retries of failed API requests


@dataclass(frozen=True)
class AgentConfig:
    model: str = DEFAULT_AGENT_MODEL
    max_retries: int = DEFAULT_MAX_RETRIES
    request_timeout: float = DEFAULT_REQUEST_TIMEOUT
    api_max_retries: int = DEFAULT_API_MAX_RETRIES


def _env_number(name: str, cast, default, *, minimum):
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = cast(raw)
    except ValueError:
        raise ValueError(f"{name} must be a number, got {raw!r}") from None
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {value}")
    return value


def load_config() -> AgentConfig:
    """Build the config from AGENT_MODEL, AGENT_MAX_RETRIES, AGENT_REQUEST_TIMEOUT (seconds)
    and AGENT_API_MAX_RETRIES; unset values use the defaults above."""
    load_dotenv()
    return AgentConfig(
        model=os.environ.get("AGENT_MODEL") or DEFAULT_AGENT_MODEL,
        max_retries=_env_number("AGENT_MAX_RETRIES", int, DEFAULT_MAX_RETRIES, minimum=0),
        request_timeout=_env_number(
            "AGENT_REQUEST_TIMEOUT", float, DEFAULT_REQUEST_TIMEOUT, minimum=1
        ),
        api_max_retries=_env_number(
            "AGENT_API_MAX_RETRIES", int, DEFAULT_API_MAX_RETRIES, minimum=0
        ),
    )
