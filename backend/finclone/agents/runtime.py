"""Tool-calling agent loop, shared by every agent role (BOE Analytics M2).

Every LLM call elsewhere in this codebase (kpi_extract, flag_triage, Scout) is
one-shot: build a prompt, get JSON back, done. That's the right shape for a
bulk sweep, but it means the model never chooses what to look at next or when
it has enough — it's a script with a model inside it, not an agent.

This module is the loop that makes the difference: the model is given tools,
picks which to call and with what arguments, sees the result, and decides
whether to call another tool or stop. Every tool call is logged to
AgentRun/AgentStep as it happens — the execution log, separate from the data
audit trail (source_url / source_quote) those tools may write to.
"""

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

import openai
from openai import OpenAI

from finclone.models import AgentRun, AgentStep

_MAX_TOKENS = 2048
# Rate-limit backoff mirrors kpi_extract/flag_triage: retry the same call up
# to 3 times before giving up, since a burst limit resets within seconds.
_MAX_RETRIES = 4


class AgentRateLimited(Exception):
    """The LLM provider's quota is exhausted mid-run."""


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict  # JSON schema for the function's arguments
    fn: Callable[..., dict]  # executes the tool; must return a JSON-serializable dict

    def to_openai(self) -> dict:
        return {"type": "function", "function": {
            "name": self.name, "description": self.description, "parameters": self.parameters}}


@dataclass
class AgentResult:
    outcome: str
    steps: int
    status: str  # done | max_steps | failed


def start_run(session, *, role: str, company_id: int | None, goal: str,
              parent_run_id: int | None = None) -> AgentRun:
    run = AgentRun(role=role, company_id=company_id, goal=goal[:512], status="running",
                   parent_run_id=parent_run_id, started=datetime.now(timezone.utc))
    session.add(run)
    session.commit()
    return run


def _call(llm: OpenAI, model: str, messages: list[dict], tools: list[Tool]):
    for attempt in range(_MAX_RETRIES):
        try:
            return llm.chat.completions.create(
                model=model, max_tokens=_MAX_TOKENS, messages=messages,
                tools=[t.to_openai() for t in tools], tool_choice="auto",
            )
        except openai.RateLimitError:
            if attempt < _MAX_RETRIES - 1:
                time.sleep(20 * (attempt + 1))
                continue
            raise AgentRateLimited("rate limited after retries")
        except openai.APIStatusError as e:
            if e.status_code == 402:
                raise AgentRateLimited("LLM account has insufficient balance")
            raise
    raise AgentRateLimited("rate limited after retries")


def _assistant_message(msg) -> dict:
    out: dict = {"role": "assistant", "content": msg.content}
    if msg.tool_calls:
        out["tool_calls"] = [
            {"id": tc.id, "type": "function",
             "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
            for tc in msg.tool_calls
        ]
    return out


def _invoke_tool(tool_map: dict[str, Tool], tc) -> tuple[dict, dict]:
    """Runs one tool call; never raises — a bad call becomes a result the
    model can see and recover from, not a crashed run."""
    try:
        args = json.loads(tc.function.arguments or "{}")
        if not isinstance(args, dict):
            args = {}
    except json.JSONDecodeError:
        args = {}
    tool = tool_map.get(tc.function.name)
    if tool is None:
        return args, {"error": f"unknown tool {tc.function.name!r}"}
    try:
        return args, tool.fn(**args)
    except TypeError as e:
        return args, {"error": f"bad arguments: {e}"}
    except Exception as e:  # a broken tool call must not kill the whole run
        return args, {"error": f"{type(e).__name__}: {str(e)[:200]}"}


def _log_step(session, run: AgentRun, seq: int, tool_name: str, args: dict, result: dict) -> None:
    session.add(AgentStep(
        run_id=run.id, seq=seq, tool=tool_name,
        args_json=json.dumps(args, default=str)[:4000],
        result_json=json.dumps(result, default=str)[:4000],
    ))
    session.commit()


def _finish(session, run: AgentRun, status: str, outcome: str) -> None:
    run.status = status
    run.outcome = outcome[:4000]
    run.finished = datetime.now(timezone.utc)
    session.commit()


def run_agent(llm: OpenAI, model: str, system: str, goal: str, tools: list[Tool], *,
              session, run: AgentRun, max_steps: int = 8) -> AgentResult:
    """Runs the tool-calling loop to completion, a step cap, or a failure.

    Every branch commits AgentRun.status/outcome before returning or raising,
    so a run's execution log never reads "running" forever.
    """
    tool_map = {t.name: t for t in tools}
    messages: list[dict] = [{"role": "system", "content": system}, {"role": "user", "content": goal}]
    seq = 0
    try:
        for _ in range(max_steps):
            response = _call(llm, model, messages, tools)
            msg = response.choices[0].message
            if not msg.tool_calls:
                outcome = (msg.content or "").strip() or "(agent stopped without a final message)"
                _finish(session, run, "done", outcome)
                return AgentResult(outcome, seq, "done")
            messages.append(_assistant_message(msg))
            for tc in msg.tool_calls:
                seq += 1
                args, result = _invoke_tool(tool_map, tc)
                _log_step(session, run, seq, tc.function.name, args, result)
                messages.append({"role": "tool", "tool_call_id": tc.id,
                                 "content": json.dumps(result, default=str)[:4000]})
        outcome = f"stopped after {max_steps} steps without a final answer"
        _finish(session, run, "max_steps", outcome)
        return AgentResult(outcome, seq, "max_steps")
    except Exception as e:
        _finish(session, run, "failed", f"{type(e).__name__}: {str(e)[:200]}")
        raise
