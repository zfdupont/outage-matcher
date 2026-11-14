import pytest

from outage_matcher import config


@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch):
    monkeypatch.setattr(config, "load_dotenv", lambda: False)
    monkeypatch.delenv("AGENT_MODEL", raising=False)
    for name in ("AGENT_MAX_RETRIES", "AGENT_REQUEST_TIMEOUT", "AGENT_API_MAX_RETRIES"):
        monkeypatch.delenv(name, raising=False)


def test_defaults():
    cfg = config.load_config()
    assert cfg.model == "claude-haiku-5-5"
    assert cfg.max_retries == 2
    assert cfg.request_timeout == 60.0
    assert cfg.api_max_retries == 2


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


def test_client_settings_from_env(monkeypatch):
    monkeypatch.setenv("AGENT_REQUEST_TIMEOUT", "15.5")
    monkeypatch.setenv("AGENT_API_MAX_RETRIES", "0")
    cfg = config.load_config()
    assert (cfg.request_timeout, cfg.api_max_retries) == (15.5, 0)


@pytest.mark.parametrize(
    ("name", "bad"),
    [
        ("AGENT_REQUEST_TIMEOUT", "soon"),
        ("AGENT_REQUEST_TIMEOUT", "0"),
        ("AGENT_API_MAX_RETRIES", "-1"),
    ],
)
def test_bad_client_settings_rejected(monkeypatch, name, bad):
    monkeypatch.setenv(name, bad)
    with pytest.raises(ValueError, match=name):
        config.load_config()
