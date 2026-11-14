"""Langfuse tracing that is a no-op unless credentials are configured.

`get_tracer()` returns a Langfuse LangChain/LangGraph callback handler (pass it in
`config={"callbacks": [tracer]}`) when `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are set,
and None otherwise. `trace_span` is a decorator that records a span around a function when
tracing is on and calls the function unchanged when it is off. Credentials are read from the
process environment only; `LANGFUSE_HOST` is read by the Langfuse client itself.
"""

from __future__ import annotations

import functools
import inspect
import logging
import os
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


def tracing_enabled() -> bool:
    return bool(os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"))


def get_tracer() -> Any | None:
    """Return a Langfuse callback handler, or None when tracing is not configured."""
    if not tracing_enabled():
        return None
    try:
        from langfuse.langchain import CallbackHandler
    except ImportError:
        logger.warning("Langfuse keys are set but the langchain integration is unavailable")
        return None
    return CallbackHandler()


def trace_span(name_or_func: str | Callable[..., Any] | None = None) -> Any:
    """Decorator: `@trace_span` or `@trace_span("name")`. Sync and async functions."""
    if callable(name_or_func):
        return _wrap(name_or_func, None)
    return lambda func: _wrap(func, name_or_func)


def _observed(func: Callable[..., Any], name: str) -> Callable[..., Any]:
    from langfuse import observe

    return observe(name=name)(func)


def _wrap(func: Any, name: str | None) -> Any:
    span_name = name or func.__name__

    if inspect.iscoroutinefunction(func):

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            if not tracing_enabled():
                return await func(*args, **kwargs)
            return await _observed(func, span_name)(*args, **kwargs)

        return async_wrapper

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if not tracing_enabled():
            return func(*args, **kwargs)
        return _observed(func, span_name)(*args, **kwargs)

    return wrapper
