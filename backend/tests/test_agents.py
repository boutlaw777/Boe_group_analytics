"""Agent runtime and tools (BOE Analytics M2): the tool-calling loop, its
execution log, and the tool contracts that must agree with the pipeline
modules they wrap (kpi_extract's KPI validation, flag_triage's verdict
vocabulary)."""

from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from finclone.agents.runtime import Tool, run_agent, start_run
from finclone.agents.tools import (
    consult_parsing_agent_tool,
    existing_kpis_tool,
    fetch_excerpt_tool,
    our_fact_tool,
    record_kpi_tool,
    record_verdict_tool,
)
from finclone.db import Base
from finclone.models import AgentRun, AgentStep, Company, FinancialFact, KpiFact, ValidationFlag


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as s:
        yield s


@pytest.fixture()
def company(session):
    c = Company(cik="0000000001", ticker="TEST", name="Test Co", sector="Software & SaaS")
    session.add(c)
    session.commit()
    return c


# --- fake OpenAI-compatible client, for exercising run_agent's loop --------

class _FakeFunctionCall:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class _FakeToolCall:
    def __init__(self, id, name, arguments):
        self.id = id
        self.function = _FakeFunctionCall(name, arguments)


class _FakeMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


class _FakeResponse:
    def __init__(self, message):
        self.choices = [type("Choice", (), {"message": message})()]


class _FakeCompletions:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


class _FakeLLM:
    def __init__(self, responses):
        self.chat = type("Chat", (), {"completions": _FakeCompletions(responses)})()


def _tool_call_response(name, arguments, call_id="call_1"):
    return _FakeResponse(_FakeMessage(tool_calls=[_FakeToolCall(call_id, name, arguments)]))


def _final_response(text):
    return _FakeResponse(_FakeMessage(content=text))


# --- run_agent: the loop ----------------------------------------------------

def test_agent_calls_a_tool_then_finishes(session):
    echo = Tool(name="echo", description="echo x",
               parameters={"type": "object", "properties": {"x": {"type": "string"}}},
               fn=lambda x: {"echoed": x})
    llm = _FakeLLM([
        _tool_call_response("echo", '{"x": "hi"}'),
        _final_response("all done"),
    ])
    run = start_run(session, role="test", company_id=None, goal="say hi")
    result = run_agent(llm, "fake-model", "system", "say hi", [echo],
                       session=session, run=run, max_steps=5)

    assert result.status == "done"
    assert result.outcome == "all done"
    assert result.steps == 1

    steps = list(session.scalars(select(AgentStep).where(AgentStep.run_id == run.id)))
    assert len(steps) == 1
    assert steps[0].tool == "echo"
    assert "hi" in steps[0].result_json

    stored = session.get(AgentRun, run.id)
    assert stored.status == "done"
    assert stored.outcome == "all done"
    assert stored.finished is not None


def test_agent_stops_at_max_steps_without_a_final_answer(session):
    noop = Tool(name="noop", description="does nothing",
               parameters={"type": "object", "properties": {}}, fn=lambda: {"ok": True})
    llm = _FakeLLM([_tool_call_response("noop", "{}", call_id=f"c{i}") for i in range(3)])
    run = start_run(session, role="test", company_id=None, goal="loop forever")
    result = run_agent(llm, "fake-model", "system", "loop forever", [noop],
                       session=session, run=run, max_steps=3)

    assert result.status == "max_steps"
    assert result.steps == 3
    assert session.get(AgentRun, run.id).status == "max_steps"


def test_unknown_tool_call_is_logged_as_an_error_not_a_crash(session):
    llm = _FakeLLM([
        _tool_call_response("does_not_exist", "{}"),
        _final_response("recovered"),
    ])
    run = start_run(session, role="test", company_id=None, goal="x")
    result = run_agent(llm, "fake-model", "system", "x", [],
                       session=session, run=run, max_steps=5)

    assert result.status == "done"
    step = session.scalar(select(AgentStep).where(AgentStep.run_id == run.id))
    assert "unknown tool" in step.result_json


def test_tool_exception_is_caught_and_reported_to_the_model(session):
    boom = Tool(name="boom", description="raises",
               parameters={"type": "object", "properties": {}},
               fn=lambda: (_ for _ in ()).throw(ValueError("bad state")))
    llm = _FakeLLM([
        _tool_call_response("boom", "{}"),
        _final_response("handled it"),
    ])
    run = start_run(session, role="test", company_id=None, goal="x")
    result = run_agent(llm, "fake-model", "system", "x", [boom],
                       session=session, run=run, max_steps=5)

    assert result.status == "done"
    step = session.scalar(select(AgentStep).where(AgentStep.run_id == run.id))
    assert "ValueError" in step.result_json


def test_malformed_tool_arguments_default_to_empty_dict(session):
    """Bad JSON in tool_call.arguments must not crash the run."""
    got = {}
    record = Tool(name="record", description="records what it saw",
                 parameters={"type": "object", "properties": {}},
                 fn=lambda **kwargs: got.update(kwargs) or {"ok": True})
    llm = _FakeLLM([
        _tool_call_response("record", "not valid json"),
        _final_response("done"),
    ])
    run = start_run(session, role="test", company_id=None, goal="x")
    run_agent(llm, "fake-model", "system", "x", [record], session=session, run=run, max_steps=5)
    assert got == {}


# --- consult_parsing_agent: the cross-agent handoff -------------------------

def test_consult_creates_a_nested_run_linked_to_the_parent(session, company):
    text = "The company defines RevPAR as revenue per available room."
    llm = _FakeLLM([
        _tool_call_response("fetch_filing_excerpt", '{"keywords": ["RevPAR"]}'),
        _final_response("RevPAR is defined as revenue per available room."),
    ])
    filing = {"form": "10-K", "accession_number": "0001-24-1", "filed_date": "2024-02-01",
              "primary_document": "doc.htm"}
    parent = start_run(session, role="reconciliation", company_id=company.id, goal="parent goal")
    tool = consult_parsing_agent_tool(llm, "fake-model", session, parent, company, filing, text)

    result = tool.fn(question="How does the filing define RevPAR?")

    assert "revenue per available room" in result["answer"]
    child = session.scalar(select(AgentRun).where(AgentRun.role == "parsing-consult"))
    assert child is not None
    assert child.parent_run_id == parent.id
    assert child.status == "done"


def test_consult_rejects_an_empty_question(session, company):
    tool = consult_parsing_agent_tool(_FakeLLM([]), "fake-model", session,
                                      start_run(session, role="reconciliation",
                                               company_id=company.id, goal="g"),
                                      company, {}, "")
    assert "error" in tool.fn(question="   ")


# --- fetch_filing_excerpt ---------------------------------------------------

def test_excerpt_prefers_keyword_dense_sections():
    filler = "irrelevant boilerplate text about nothing in particular. " * 400
    relevant = "RevPAR increased 5% to $120. Occupancy was 72%. RevPAR growth continued. " * 50
    tool = fetch_excerpt_tool(filler + relevant + filler)
    result = tool.fn(keywords=["RevPAR", "occupancy"], max_chunks=2)
    assert result["chunks"]
    assert all("RevPAR" in c for c in result["chunks"])


def test_excerpt_requires_keywords():
    tool = fetch_excerpt_tool("some filing text")
    assert "error" in tool.fn(keywords=[])
    assert "error" in tool.fn(keywords="not a list")


def test_excerpt_reports_no_match_instead_of_silently_empty():
    tool = fetch_excerpt_tool("nothing relevant here " * 1000)
    result = tool.fn(keywords=["RevPAR"])
    assert result["chunks"] == []
    assert "note" in result


# --- record_kpi: must agree with kpi_extract's own validation --------------

def _filing():
    return {"form": "10-K", "accession_number": "0001-24-1", "filed_date": "2024-02-01"}


def test_record_kpi_stores_a_valid_record(session, company):
    tool = record_kpi_tool(session, company, _filing(), "https://sec.gov/x")
    result = tool.fn(name="RevPAR", value=120.5, value_text="$120.50", unit="USD",
                     period="FY2024", quote="RevPAR was $120.50")
    assert result["status"] == "recorded"
    row = session.get(KpiFact, result["id"])
    assert row.name == "RevPAR"
    assert row.company_id == company.id


def test_record_kpi_rejects_missing_quote(session, company):
    tool = record_kpi_tool(session, company, _filing(), "https://sec.gov/x")
    result = tool.fn(name="RevPAR", value=120.5, value_text="$120.50", unit="USD",
                     period="FY2024", quote="")
    assert "error" in result
    assert session.scalar(select(KpiFact)) is None


def test_record_kpi_is_idempotent_on_rerun(session, company):
    tool = record_kpi_tool(session, company, _filing(), "https://sec.gov/x")
    first = tool.fn(name="RevPAR", value=120.5, value_text="$120.50", unit="USD",
                    period="FY2024", quote="RevPAR was $120.50")
    second = tool.fn(name="RevPAR", value=120.5, value_text="$120.50", unit="USD",
                     period="FY2024", quote="RevPAR was $120.50")
    assert second["status"] == "already recorded"
    assert second["id"] == first["id"]
    assert session.scalar(select(KpiFact).limit(1)) is not None
    assert len(list(session.scalars(select(KpiFact)))) == 1


def test_existing_kpis_tool_lists_what_is_already_stored(session, company):
    session.add(KpiFact(company_id=company.id, name="ARR", value=1e9, value_text="$1B", unit="USD",
                        period="FY2024", source_quote="ARR reached $1B", form="10-K",
                        accession_number="0001", filed_date=date(2024, 2, 1),
                        source_url="https://sec.gov/x"))
    session.commit()
    tool = existing_kpis_tool(session, company)
    result = tool.fn()
    assert result["kpis"] == [{"name": "ARR", "period": "FY2024", "value_text": "$1B"}]


# --- get_our_fact ------------------------------------------------------------

def _fact(company_id, concept, value, fy, fp="FY"):
    return FinancialFact(
        company_id=company_id, concept=f"us-gaap:{concept}", canonical_concept=concept,
        unit="USD", value=value, fiscal_year=fy, fiscal_period=fp, start_date=None,
        end_date=date(fy, 12, 31), form="10-K", accession_number=f"0001-{fy}",
        filed_date=date(fy + 1, 2, 1), source_url=f"https://sec.gov/{fy}",
    )


def test_our_fact_returns_stored_value_and_provenance(session, company):
    session.add(_fact(company.id, "revenue", 1000.0, 2024))
    session.commit()
    tool = our_fact_tool(session, company)
    result = tool.fn(concept="revenue", fiscal_year=2024)
    assert result["value"] == 1000.0
    assert result["source_url"] == "https://sec.gov/2024"


def test_our_fact_missing_value_is_an_error_not_a_crash(session, company):
    tool = our_fact_tool(session, company)
    result = tool.fn(concept="revenue", fiscal_year=1999)
    assert "error" in result


# --- record_verdict: must agree with flag_triage's vocabulary and close rule

@pytest.fixture()
def flag(session, company):
    f = ValidationFlag(company_id=company.id, canonical_concept="capex", fiscal_year=2024,
                       our_value=100.0, reference_value=-101.0, variance=0.01)
    session.add(f)
    session.commit()
    return f


def test_record_verdict_rejects_a_flag_id_outside_the_batch(session, flag):
    tool = record_verdict_tool(session, {flag.id})
    result = tool.fn(flag_id=flag.id + 999, resolution="convention", basis="filing_text",
                     reason="x")
    assert "error" in result
    assert flag.resolution is None


def test_record_verdict_rejects_unknown_resolution(session, flag):
    tool = record_verdict_tool(session, {flag.id})
    result = tool.fn(flag_id=flag.id, resolution="probably fine", basis="filing_text", reason="x")
    assert "error" in result


def test_record_verdict_requires_a_reason(session, flag):
    tool = record_verdict_tool(session, {flag.id})
    result = tool.fn(flag_id=flag.id, resolution="convention", basis="filing_text", reason="  ")
    assert "error" in result


def test_record_verdict_degrades_bad_basis_to_reasoning(session, flag):
    tool = record_verdict_tool(session, {flag.id})
    tool.fn(flag_id=flag.id, resolution="convention", basis="verified!", reason="sign differs")
    assert flag.resolved_by == "agent-inferred"
    assert flag.resolved is False


@pytest.mark.parametrize("resolution,basis,expect_closed", [
    ("convention", "filing_text", True),
    ("immaterial", "filing_text", True),
    ("real_issue", "filing_text", False),
    ("unexplained", "filing_text", False),
    ("convention", "reasoning", False),
])
def test_record_verdict_close_rule_matches_flag_triage(session, flag, resolution, basis,
                                                        expect_closed):
    tool = record_verdict_tool(session, {flag.id})
    tool.fn(flag_id=flag.id, resolution=resolution, basis=basis, reason="explained")
    assert flag.resolved is expect_closed
    assert flag.resolved_by == ("agent" if basis == "filing_text" else "agent-inferred")
