import pytest

from outage_matcher import config


@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch):
    monkeypatch.setattr(config, "load_dotenv", lambda: False)
    monkeypatch.delenv("AGENT_MODEL", raising=False)
    monkeypatch.delenv("AGENT_MAX_RETRIES", raising=False)


def test_defaults():
    cfg = config.load_config()
    assert cfg.model == "claude-haiku-5-5"
    assert cfg.max_retries == 2


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("AGENT_MODEL", "claude-other")
    monkeypatch.setenv("AGENT_MAX_RETRIES", "0")
    cfg = config.load_config()
    assert (cfg.model, cfg.max_retries) == ("claude-other", 0)


@pytest.mark.parametrize("bad", ["x", "-1"])
def test_bad_retries_rejected(monkeypatch, bad):
    monkeypatch.setenv("AGENT_MAX_RETRIES", bad)
    with pytest.raises(ValueError, match="AGENT_MAX_RETRIES"):
        config.load_config()
