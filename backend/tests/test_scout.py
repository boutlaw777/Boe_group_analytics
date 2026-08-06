from finclone.scout import compute_metrics, passes_filters, sanitize_screen


def _annual(**kwargs):
    """Build an annual dict from concept_fy=value kwargs, e.g. revenue_2024=100."""
    out = {}
    for key, value in kwargs.items():
        concept, fy = key.rsplit("_", 1)
        out[(concept, int(fy))] = value
    return out


def test_compute_metrics_growth_and_margins():
    m = compute_metrics(_annual(
        revenue_2023=100.0, revenue_2024=125.0,
        net_income_2023=20.0, net_income_2024=30.0,
        gross_profit_2024=50.0,
        operating_cash_flow_2024=40.0, capex_2024=10.0,
        stockholders_equity_2024=150.0,
    ))
    assert m["fiscal_year"] == 2024
    assert abs(m["revenue_growth"] - 0.25) < 1e-9
    assert abs(m["net_income_growth"] - 0.5) < 1e-9
    assert abs(m["gross_margin"] - 0.4) < 1e-9
    assert abs(m["net_margin"] - 0.24) < 1e-9
    assert m["free_cash_flow"] == 30.0
    assert abs(m["roe"] - 0.2) < 1e-9


def test_compute_metrics_requires_revenue():
    assert compute_metrics(_annual(net_income_2024=5.0)) is None


def test_passes_filters():
    metrics = {"revenue_growth": 0.25, "net_margin": 0.3}
    assert passes_filters(metrics, [{"metric": "revenue_growth", "op": ">", "value": 0.2}])
    assert not passes_filters(metrics, [{"metric": "revenue_growth", "op": ">", "value": 0.3}])
    # Missing metric fails closed
    assert not passes_filters(metrics, [{"metric": "roe", "op": ">", "value": 0.1}])


def test_sanitize_screen_drops_malformed_filters():
    screen = sanitize_screen({
        "sector": "Made Up Sector",
        "filters": [
            {"metric": "revenue_growth", "op": ">", "value": 0.2},   # valid
            {"metric": "made_up_metric", "op": ">", "value": 1},     # unknown metric
            {"metric": "revenue", "op": "!=", "value": 0},           # bad operator
            {"metric": "revenue", "op": ">", "value": "lots"},       # non-numeric
            "not even a dict",
        ],
        "sort_by": "also_made_up",
    }, sectors=["Software & SaaS"])
    assert screen["sector"] is None
    assert screen["filters"] == [{"metric": "revenue_growth", "op": ">", "value": 0.2}]
    assert screen["sort_by"] is None


def test_sanitize_screen_garbage_input():
    screen = sanitize_screen("total garbage", sectors=[])
    assert screen == {"sector": None, "filters": [], "sort_by": None, "descending": True}


# --- translate_query: fallback to a second provider on a provider failure ---
# Added after the 2026-08-06 DeepSeek balance outage took Scout down (and,
# separately, the KPI/triage pipelines sharing the same account) — Scout is
# one call per user query, so a low-throughput fallback is safe here even
# though it would not be for the bulk sweeps.

import json as _json

import openai
import pytest

import finclone.scout as scout_mod
from finclone.scout import _FALLBACK_WORTHY, _translate_with, translate_query


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, behavior):
        """behavior: an exception instance to raise, or a response payload dict."""
        self.behavior = behavior
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        if isinstance(self.behavior, Exception):
            raise self.behavior
        if isinstance(self.behavior, dict):
            return _FakeResponse(_json.dumps(self.behavior))
        return _FakeResponse(self.behavior)  # raw string: simulates malformed JSON


class _FakeLLM:
    def __init__(self, behavior):
        self.chat = type("Chat", (), {"completions": _FakeCompletions(behavior)})()


def _screen_payload(sector=None):
    return {"sector": sector, "filters": [], "sort_by": None, "descending": True}


def _no_fallback(monkeypatch):
    monkeypatch.setattr(scout_mod, "SCOUT_FALLBACK_API_KEY", "")


def _with_fallback(monkeypatch):
    monkeypatch.setattr(scout_mod, "SCOUT_FALLBACK_API_KEY", "fake-gemini-key")
    monkeypatch.setattr(scout_mod, "SCOUT_FALLBACK_BASE_URL", "https://fake.example/")
    monkeypatch.setattr(scout_mod, "SCOUT_FALLBACK_MODEL", "fake-fallback-model")


def _patch_openai_sequence(monkeypatch, llms):
    """OpenAI(...) constructor returns llms[0] on first call, llms[1] on second."""
    calls = iter(llms)
    monkeypatch.setattr(scout_mod, "OpenAI", lambda **kwargs: next(calls))


def test_translate_with_reports_unparseable_json_as_empty_screen(capsys):
    llm = _FakeLLM("not json at all")
    screen = _translate_with(llm, "fake-model", "software companies", [])
    assert screen["filters"] == []
    assert "unparseable" in capsys.readouterr().out


def test_translate_query_uses_primary_when_it_succeeds(monkeypatch):
    _no_fallback(monkeypatch)
    primary = _FakeLLM(_screen_payload(sector="Software & SaaS"))
    _patch_openai_sequence(monkeypatch, [primary])
    screen = translate_query("software companies", ["Software & SaaS"])
    assert screen["sector"] == "Software & SaaS"
    assert primary.chat.completions.calls == 1


def _status_error(status_code):
    import httpx
    request = httpx.Request("POST", "https://fake.example/")
    response = httpx.Response(status_code, request=request, json={"error": "x"})
    return openai.APIStatusError("boom", response=response, body=None)


def test_translate_query_falls_back_when_primary_fails_and_fallback_configured(monkeypatch):
    _with_fallback(monkeypatch)
    primary = _FakeLLM(_status_error(402))
    fallback = _FakeLLM(_screen_payload(sector="Banking"))
    _patch_openai_sequence(monkeypatch, [primary, fallback])
    screen = translate_query("banks", ["Banking"])
    assert screen["sector"] == "Banking"
    assert fallback.chat.completions.calls == 1


def test_translate_query_raises_when_primary_fails_and_no_fallback_configured(monkeypatch):
    _no_fallback(monkeypatch)
    primary = _FakeLLM(_status_error(402))
    _patch_openai_sequence(monkeypatch, [primary])
    with pytest.raises(openai.APIStatusError):
        translate_query("banks", ["Banking"])


def test_translate_query_does_not_fall_back_on_bad_json_from_primary(monkeypatch):
    """A provider that answered with garbage JSON is not a provider failure —
    retrying on a second provider wouldn't fix that, so it must not fall back,
    just degrade to an empty screen (matching _translate_with's own contract)."""
    _with_fallback(monkeypatch)
    primary = _FakeLLM("garbage, not json")
    fallback = _FakeLLM(_screen_payload(sector="Banking"))
    _patch_openai_sequence(monkeypatch, [primary, fallback])
    screen = translate_query("banks", ["Banking"])
    assert screen["sector"] is None  # empty screen, not the fallback's answer
    assert fallback.chat.completions.calls == 0


def test_rate_limit_and_connection_errors_are_also_fallback_worthy():
    assert openai.RateLimitError in _FALLBACK_WORTHY
    assert openai.APIConnectionError in _FALLBACK_WORTHY
    assert openai.APIStatusError in _FALLBACK_WORTHY
