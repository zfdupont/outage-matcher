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
MODEL = "deepseek-chat"
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


@dataclass(frozen=True)
class ChatResult:
    data: dict[str, Any]  # the parsed JSON object the model returned
    content: str  # the raw message text
    usage: TokenUsage


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
        model: str = MODEL,
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
                "response_format": {"type": "json_object"},
            }
        )
        try:
            content = body["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise DeepSeekError(f"unexpected response shape: {str(body)[:200]}") from exc
        used = body.get("usage") or {}
        usage = TokenUsage(
            int(used.get("prompt_tokens") or 0), int(used.get("completion_tokens") or 0), 1
        )
        try:
            data = json.loads(content)
        except ValueError as exc:
            raise DeepSeekError(f"model reply was not valid JSON: {content[:200]!r}") from exc
        if not isinstance(data, dict):
            raise DeepSeekError(f"model reply was not a JSON object: {content[:200]!r}")
        return ChatResult(data, content, usage)
