"""LLM provider decoupling and the DeepSeek spend guard (2026-08-08).

KPI extraction and flag triage used to share KPI_API_KEY/KPI_BASE_URL/
KPI_MODEL, so setting GEMINI_API_KEY (to move KPI extraction to the free
tier) silently moved flag triage there too. TRIAGE_* is the fix — always
pinned to DeepSeek, same pattern as SCOUT_MODEL. These tests exist to prove
the decoupling actually holds, not just that the constants are defined.
"""

import importlib

import httpx
import pytest

import finclone.config as config


# --- decoupling: TRIAGE_* must never follow the Gemini toggle --------------

def test_triage_pinned_to_deepseek_even_when_gemini_key_is_set(monkeypatch):
    """The whole point of this module: enabling Gemini for KPI extraction
    must not silently redirect flag triage there too."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-deepseek")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini-key")
    importlib.reload(config)
    try:
        assert config.TRIAGE_API_KEY == "sk-test-deepseek"
        assert config.TRIAGE_MODEL == "deepseek-chat"
        assert config.TRIAGE_BASE_URL == config.DEEPSEEK_BASE_URL
        # And confirm KPI_API_KEY genuinely DOES follow Gemini here — if it
        # didn't, this test would be proving nothing about decoupling.
        assert config.KPI_API_KEY == "fake-gemini-key"
    finally:
        monkeypatch.undo()
        importlib.reload(config)


def test_triage_pinned_to_deepseek_when_gemini_key_is_unset(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-deepseek")
    # Explicit empty string, not delenv: load_dotenv() on reload only fills in
    # keys ABSENT from os.environ, so a deleted key would be silently
    # repopulated from the local backend/.env file's real GEMINI_API_KEY.
    monkeypatch.setenv("GEMINI_API_KEY", "")
    importlib.reload(config)
    try:
        assert config.TRIAGE_API_KEY == "sk-test-deepseek"
        assert config.KPI_API_KEY == "sk-test-deepseek"  # both DeepSeek here
    finally:
        monkeypatch.undo()
        importlib.reload(config)


# --- require_triage_provider: explicit opt-in before spending real credit --

def test_require_triage_provider_raises_without_allow_flag(monkeypatch):
    monkeypatch.setattr(config, "TRIAGE_API_KEY", "sk-test")
    monkeypatch.setattr(config, "ALLOW_DEEPSEEK_BULK", False)
    with pytest.raises(SystemExit):
        config.require_triage_provider()


def test_require_triage_provider_passes_with_allow_flag(monkeypatch):
    monkeypatch.setattr(config, "TRIAGE_API_KEY", "sk-test")
    monkeypatch.setattr(config, "ALLOW_DEEPSEEK_BULK", True)
    config.require_triage_provider()  # must not raise


def test_require_triage_provider_raises_without_any_key(monkeypatch):
    monkeypatch.setattr(config, "TRIAGE_API_KEY", "")
    monkeypatch.setattr(config, "ALLOW_DEEPSEEK_BULK", True)
    with pytest.raises(SystemExit):
        config.require_triage_provider()


# --- deepseek_balance_remaining: never raises, degrades to None -----------

class _FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=self)

    def json(self):
        return self._payload


def test_balance_remaining_parses_usd_balance(monkeypatch):
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResponse(
        {"balance_infos": [{"currency": "USD", "total_balance": "7.42"}]}))
    assert config.deepseek_balance_remaining() == 7.42


def test_balance_remaining_ignores_non_usd_entries(monkeypatch):
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResponse(
        {"balance_infos": [{"currency": "CNY", "total_balance": "50.00"}]}))
    assert config.deepseek_balance_remaining() is None


def test_balance_remaining_returns_none_without_a_key(monkeypatch):
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "")
    assert config.deepseek_balance_remaining() is None


def test_balance_remaining_returns_none_on_http_error(monkeypatch):
    """A transient failure must degrade to None, not raise — the caller
    treats None as 'unknown, keep going', not as a reason to crash the run."""
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResponse({}, status=500))
    assert config.deepseek_balance_remaining() is None


def test_balance_remaining_returns_none_on_malformed_payload(monkeypatch):
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResponse(
        {"balance_infos": [{"currency": "USD", "total_balance": "not-a-number"}]}))
    assert config.deepseek_balance_remaining() is None


def test_balance_remaining_returns_none_on_network_failure(monkeypatch):
    def _raise(*a, **k):
        raise httpx.ConnectError("no route")
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setattr(httpx, "get", _raise)
    assert config.deepseek_balance_remaining() is None
