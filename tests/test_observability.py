import asyncio

import pytest

from outage_matcher import observability
from outage_matcher.observability import get_tracer, trace_span, tracing_enabled


@pytest.fixture
def no_keys(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    # Keep the real client offline: no exporter, no network.
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "false")
    monkeypatch.setenv("LANGFUSE_HOST", "http://127.0.0.1:9")


def test_tracer_is_none_without_keys(no_keys):
    assert tracing_enabled() is False
    assert get_tracer() is None


@pytest.mark.parametrize("missing", ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"])
def test_tracer_is_none_with_only_one_key(no_keys, monkeypatch, missing):
    other = {"LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"} - {missing}
    monkeypatch.setenv(other.pop(), "value")
    assert get_tracer() is None


@pytest.mark.parametrize("value", ["your-key-here", " ", ""])
def test_placeholder_or_blank_keys_do_not_enable_tracing(no_keys, monkeypatch, value):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", value)
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-real")
    assert tracing_enabled() is False
    assert get_tracer() is None
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-real")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", value)
    assert tracing_enabled() is False


def test_tracer_is_langfuse_handler_with_keys(keys):
    from langfuse.langchain import CallbackHandler

    assert tracing_enabled() is True
    assert isinstance(get_tracer(), CallbackHandler)


def test_trace_span_is_passthrough_when_disabled(no_keys, monkeypatch):
    def boom(*a, **kw):
        raise AssertionError("langfuse must not be touched when tracing is off")

    monkeypatch.setattr(observability, "_observed", boom)

    @trace_span
    def add(a, b=1):
        """doc"""
        return a + b

    @trace_span("named")
    def mul(a, b):
        return a * b

    assert add(2, b=3) == 5
    assert mul(2, 3) == 6
    assert add.__name__ == "add"
    assert add.__doc__ == "doc"


def test_trace_span_async_passthrough(no_keys):
    @trace_span("work")
    async def work(x):
        return x * 2

    assert asyncio.run(work(4)) == 8


def test_trace_span_uses_observe_when_enabled(keys, monkeypatch):
    seen = []

    def fake_observed(func, name):
        seen.append(name)
        return func

    monkeypatch.setattr(observability, "_observed", fake_observed)

    @trace_span
    def one():
        return 1

    @trace_span("custom")
    def two():
        return 2

    assert (one(), two()) == (1, 2)
    assert seen == ["one", "custom"]


def test_trace_span_runs_with_real_langfuse_when_enabled(keys):
    @trace_span("real")
    def f(x):
        return x + 1

    assert f(1) == 2


def test_trace_span_propagates_exceptions(no_keys):
    @trace_span
    def bad():
        raise ValueError("nope")

    with pytest.raises(ValueError, match="nope"):
        bad()
