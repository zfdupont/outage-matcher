"""Minimal DeepSeek chat client (OpenAI-compatible API) used for gold generation and judging."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
from dotenv import load_dotenv

BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-flash"  # the one id containing "flash" in GET /models (2026-11-14)
# The flash model reasons by default, which spends max_tokens and ignores temperature; plain
# replies keep temperature 0 meaningful for the judge. Recorded in result files from now on.
THINKING: dict[str, str] = {"type": "disabled"}
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})


class DeepSeekError(RuntimeError):
    """The API call failed or returned something that is not the requested JSON object."""


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0

    def plus(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.calls + other.calls,
        )

    def describe(self) -> str:
        return (
            f"{self.calls} calls, {self.input_tokens} input tokens, "
            f"{self.output_tokens} output tokens"
        )


class InvalidReplyError(DeepSeekError):
    """The call succeeded but the reply is not the requested JSON object (for example cut off at
    max_tokens). Unlike transport errors, asking again can help. `usage` is what the call cost."""

    def __init__(self, message: str, usage: TokenUsage | None = None) -> None:
        super().__init__(message)
        self.usage = usage or TokenUsage()


@dataclass(frozen=True)
class ChatResult:
    data: dict[str, Any]  # the parsed JSON object the model returned
    content: str  # the raw message text
    usage: TokenUsage


def model_id() -> str:
    """DEEPSEEK_MODEL from the environment or .env, else the default flash model."""
    load_dotenv()
    return (os.environ.get("DEEPSEEK_MODEL") or "").strip() or DEFAULT_MODEL


def api_key() -> str | None:
    """DEEPSEEK_API_KEY from the environment or .env; empty or `your-...` placeholder is unset."""
    load_dotenv()
    key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    return None if not key or key.startswith("your-") else key


class DeepSeekClient:
    def __init__(
        self,
        key: str,
        *,
        model: str = DEFAULT_MODEL,
        base_url: str = BASE_URL,
        http: httpx.Client | None = None,
        timeout: float = 90.0,
        max_retries: int = 3,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.model = model
        self.max_retries = max_retries
        self._sleep = sleep
        self._http = http or httpx.Client(timeout=timeout)
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._headers = {"Authorization": f"Bearer {key}"}

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        last = "no attempt made"
        for attempt in range(self.max_retries + 1):
            if attempt:
                self._sleep(2.0**attempt)
            try:
                response = self._http.post(self._url, json=payload, headers=self._headers)
            except httpx.TransportError as exc:
                last = f"{type(exc).__name__}: {exc}"
                continue
            if response.status_code in RETRY_STATUS:
                last = f"HTTP {response.status_code}"
                continue
            if response.status_code != 200:
                raise DeepSeekError(f"HTTP {response.status_code}: {response.text[:200]}")
            try:
                return response.json()
            except ValueError as exc:
                raise DeepSeekError(f"response was not JSON: {exc}") from exc
        raise DeepSeekError(f"gave up after {self.max_retries + 1} attempts ({last})")

    def chat_json(
        self, messages: list[dict[str, str]], *, temperature: float = 0.0, max_tokens: int = 1024
    ) -> ChatResult:
        """One chat completion in JSON mode. The prompt must itself ask for a JSON object."""
        body = self._post(
            {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "thinking": THINKING,
                "response_format": {"type": "json_object"},
            }
        )
        used = body.get("usage") or {}
        usage = TokenUsage(
            int(used.get("prompt_tokens") or 0), int(used.get("completion_tokens") or 0), 1
        )
        try:
            content = body["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise InvalidReplyError(f"unexpected response shape: {str(body)[:200]}", usage) from exc
        try:
            data = json.loads(content)
        except ValueError as exc:
            raise InvalidReplyError(
                f"model reply was not valid JSON: {content[:200]!r}", usage
            ) from exc
        if not isinstance(data, dict):
            raise InvalidReplyError(f"model reply was not a JSON object: {content[:200]!r}", usage)
        return ChatResult(data, content, usage)
