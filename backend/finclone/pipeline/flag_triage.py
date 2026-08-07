"""Explain validation flags instead of merely counting them (PDR §3 follow-on).

crossref.py can detect that our SEC-extracted figure disagrees with SimFin; it
cannot say *why*. At a 1% threshold that produced 34k flags across 94% of
companies, all unresolved — a queue no human will ever work through, and one
that reads as "this data is unreliable" rather than "this data is checked."

Triage runs in two stages, cheap first:

  Stage 1 (this module, `--rules`) — arithmetic only. Free, instant, and
  *certain*: an opposite-sign pair of equal magnitude is a convention
  difference by definition, not a judgement call. Measured on the production
  queue this settles ~12% of flags. It is deliberately not tuned to settle
  more: a looser threshold would trade certainty for volume, and the whole
  point of doing this in rules rather than a model is that rules can't be wrong.

  Stage 2 (`--llm`) — everything rules can't reach, where a person would have
  to open the filing and think. Batched per company, since the ~12 flags a
  company carries all come from the same filing.

`resolved_by` records which stage decided, so 'rule' (certain) is never
presented to a client as equivalent to 'model' (judged).
"""

import argparse
import json
import time

import openai
from openai import OpenAI
from sqlalchemy import func, select

from finclone.config import (
    KPI_API_KEY, KPI_BASE_URL, KPI_MODEL, require_bulk_provider)
from finclone.db import get_session, init_db
from finclone.edgar.client import EdgarClient
from finclone.edgar.documents import fetch_filing_text, latest_filing
from finclone.models import Company, ValidationFlag


class _RateLimited(Exception):
    """Provider quota exhausted — stop so a supervisor can resume after reset."""

# An opposite-sign pair whose magnitudes agree this closely is the same number
# written under two conventions (SimFin books capex as a negative cash outflow;
# XBRL's PaymentsToAcquire* is positive). Kept tight: past ~5% the sign is still
# explained but the magnitude gap is a second, unexplained fact, and claiming
# the flag is fully resolved would be wrong. Those go to stage 2.
_CONVENTION_MAX_VARIANCE = 0.05

# Same-sign agreement this close is rounding, a scale difference, or an
# immaterial restatement. Only reachable because crossref flags at 1%.
_IMMATERIAL_MAX_VARIANCE = 0.02

RULE_RESOLUTIONS = ("convention", "immaterial")


def classify(our_value: float | None, reference_value: float | None,
             variance: float | None) -> tuple[str, str] | None:
    """Settle a flag by arithmetic, or return None to defer it to stage 2.

    Returns (resolution, human-readable reason). Never guesses: anything the
    numbers alone don't explain is left untriaged rather than labelled.
    """
    if our_value is None or reference_value is None or variance is None:
        return None
    # A zero on either side makes both the sign test and the ratio meaningless
    # (crossref already records variance as inf when the reference is 0).
    if our_value == 0 or reference_value == 0:
        return None
    spread = abs(variance)
    if spread != spread or spread == float("inf"):  # NaN / inf guard
        return None

    signs_differ = (our_value < 0) != (reference_value < 0)
    if signs_differ and spread <= _CONVENTION_MAX_VARIANCE:
        return ("convention",
                f"Sign-convention difference: both sources report the same "
                f"magnitude with opposite signs (ours {our_value:+,.0f} vs "
                f"reference {reference_value:+,.0f}; magnitudes agree within "
                f"{spread:.1%}). Not a discrepancy — no action needed.")
    if not signs_differ and spread <= _IMMATERIAL_MAX_VARIANCE:
        return ("immaterial",
                f"Immaterial: same sign and magnitudes agree within "
                f"{spread:.1%} (ours {our_value:,.0f} vs reference "
                f"{reference_value:,.0f}) — rounding or a minor restatement.")
    return None


def run_rules(limit: int | None = None, redo: bool = False) -> dict[str, int]:
    """Apply stage-1 rules to untriaged flags. Idempotent."""
    counts = {"examined": 0, "convention": 0, "immaterial": 0, "deferred": 0}
    with get_session() as session:
        query = select(ValidationFlag)
        if not redo:
            query = query.where(ValidationFlag.resolution.is_(None))
        if limit:
            query = query.limit(limit)
        flags = list(session.scalars(query))
        for flag in flags:
            counts["examined"] += 1
            verdict = classify(flag.our_value, flag.reference_value, flag.variance)
            if verdict is None:
                counts["deferred"] += 1
                continue
            resolution, reason = verdict
            flag.resolution = resolution
            flag.reason = reason[:512]
            flag.resolved_by = "rule"
            flag.resolved = True
            counts[resolution] += 1
        session.commit()
    return counts


# --- stage 2: model judgement --------------------------------------------

# Verdicts stage 2 may return. `unexplained` exists so the model has an honest
# way out: the queue spans fiscal years back to 2018 while we can only hand it
# the latest filing, so for older years it often *cannot* verify anything. An
# escape hatch that routes to a human is far better than a confident label
# invented to fill the field.
LLM_RESOLUTIONS = ("convention", "immaterial", "restatement", "real_issue", "unexplained")

#: Resolutions a person still needs to look at.
NEEDS_REVIEW = ("real_issue", "unexplained")

# Filing prose for each canonical concept, for chunk pre-filtering. The concept
# names are our own snake_case identifiers and appear nowhere in a filing.
# Issuers name the same line item differently, so each concept needs the
# alternates too: Apple's balance sheet says "Term debt", and searching only for
# "long-term debt" found 0 hits in its 10-Q — which silently skipped the company.
_CONCEPT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "revenue": ("revenue", "net sales", "total sales"),
    "cost_of_revenue": ("cost of revenue", "cost of sales", "cost of goods"),
    "gross_profit": ("gross profit", "gross margin"),
    "operating_income": ("operating income", "income from operations", "operating loss",
                         "loss from operations"),
    "net_income": ("net income", "net loss", "net earnings"),
    "research_development": ("research and development",),
    "total_assets": ("total assets",),
    "total_liabilities": ("total liabilities",),
    "stockholders_equity": ("stockholders' equity", "shareholders' equity", "total equity",
                            "stockholders’ equity", "shareholders’ equity"),
    "long_term_debt": ("long-term debt", "long term debt", "term debt", "notes payable",
                       "senior notes", "borrowings"),
    "operating_cash_flow": ("operating activities", "cash provided by operating",
                            "cash used in operating"),
    "capex": ("capital expenditure", "purchases of property", "property and equipment",
              "additions to property", "payments for property"),
}

# Used when no concept keyword matches at all. These appear in essentially every
# filing's financial statements, so they locate the statement pages generically.
_STATEMENT_KEYWORDS: tuple[str, ...] = (
    "consolidated balance sheet", "consolidated statements", "total assets",
    "total liabilities", "in millions", "in thousands",
)

_TRIAGE_CHUNK_SIZE = 15_000     # characters, matching kpi_extract
# Fewer chunks than KPI extraction: triage needs enough statement context to
# recognise a definition or restatement, not an exhaustive read, and this is
# multiplied across ~2,800 companies.
_TRIAGE_MAX_CHUNKS = 3
# Flags per model call. A company carries ~12 but the worst has 72, and each
# verdict needs a sentence of reasoning, so batch to stay inside max_tokens.
_FLAGS_PER_CALL = 15

_LLM_SYSTEM = """You are reconciling a financial data platform's SEC-extracted \
figures against an independent reference source (SimFin). For each disagreement \
you decide WHY the two differ.

Both figures may be correct: the sources use different sign conventions, \
different definitions of a line item, or reflect a later restatement. Your job \
is to say which, so a human only reviews what genuinely needs review.

Assign exactly one verdict per flag:
- "convention": a sign or definitional difference. The underlying figure agrees; \
the sources just record it differently (e.g. capital spending as a negative cash \
outflow vs a positive amount spent, or one source including items the other excludes).
- "immaterial": the gap is too small to matter — rounding, or a scale difference.
- "restatement": one source reflects figures the company later revised.
- "real_issue": likely a genuine extraction error worth a human's attention.
- "unexplained": you cannot determine the cause from the evidence provided.

You must also state what your verdict rests on, in a "basis" field:
- "filing_text": you found the relevant figures or disclosure in the excerpt \
and your verdict follows from reading it.
- "reasoning": the figures are not in the excerpt, and your verdict is inferred \
from the line item, the signs, and the size of the gap.

CRITICAL constraints:
- You are given ONE filing, usually the most recent. Many flags concern earlier \
fiscal years whose figures are NOT in that text. Never claim to have verified a \
number you cannot see — if you did not see it, the basis is "reasoning".
- Do not hedge inside a confident verdict. If your reason would contain "I \
cannot verify", "cannot confirm", or "likely", then either the basis is \
"reasoning" or the resolution is "unexplained". Say which plainly; do not label \
a flag settled and then undercut it in prose.
- If you cannot settle a flag at all, return "unexplained". Do not guess a \
verdict to fill the field — an honest "unexplained" routes it to a person, a \
wrong "convention" hides a real error.
- Reason must be one or two sentences, specific to that line item, and under 400 \
characters.

Respond with JSON only:
{"verdicts": [{"id": <flag id>, "resolution": "<one of the five>", \
"basis": "filing_text" | "reasoning", "reason": "<why>"}]}
Include every id you were given, exactly once."""

#: How a verdict was arrived at. Only a filing-text verdict can close a flag.
BASES = ("filing_text", "reasoning")


def _keywords_for_concepts(concepts) -> list[str]:
    out: list[str] = []
    for concept in concepts:
        for keyword in _CONCEPT_KEYWORDS.get(concept, (concept.replace("_", " "),)):
            if keyword not in out:
                out.append(keyword)
    return out


def _select_chunks(text: str, keywords: list[str], max_chunks: int) -> list[str]:
    """Highest-scoring filing chunks by keyword hits. Mirrors kpi_extract's
    pre-filter so a 300-page filing doesn't go to the model whole."""
    lowered = [k.lower() for k in keywords]
    overlap = 500
    step = _TRIAGE_CHUNK_SIZE - overlap
    scored: list[tuple[int, str]] = []
    for start in range(0, len(text), step):
        chunk = text[start:start + _TRIAGE_CHUNK_SIZE]
        low = chunk.lower()
        score = sum(low.count(k) for k in lowered)
        if score:
            scored.append((score, chunk))
    scored.sort(key=lambda pair: -pair[0])
    return [chunk for _, chunk in scored[:max_chunks]]


def select_excerpt(text: str, concepts, ticker: str = "") -> str:
    """The filing text to send, degrading gracefully rather than giving up.

    Returning nothing when no concept keyword matches is the worst outcome: the
    company is skipped silently and its flags stay untriaged forever, which is
    exactly what happened to AAPL (its 10-Q says "Term debt", so a search for
    "long-term debt" scored zero). A company whose flags all share one concept
    has no other keyword to fall back on, so widen the search instead of
    bailing — the model can still judge conventions from the figures, and will
    answer "unexplained" honestly if the text doesn't help.
    """
    chunks = _select_chunks(text, _keywords_for_concepts(concepts), _TRIAGE_MAX_CHUNKS)
    if not chunks:
        chunks = _select_chunks(text, list(_STATEMENT_KEYWORDS), _TRIAGE_MAX_CHUNKS)
        if chunks:
            print(f"    {ticker}: no concept keyword matched — using statement pages")
    if not chunks and text.strip():
        chunks = [text[:_TRIAGE_CHUNK_SIZE]]
        print(f"    {ticker}: no keyword matched at all — using start of filing")
    return "\n\n---\n\n".join(chunks)


def _clean_verdicts(payload: object,
                    valid_ids: set[int]) -> dict[int, tuple[str, str, str]]:
    """Validate model output before it becomes a stored explanation.

    Returns {flag_id: (resolution, basis, reason)}. JSON mode guarantees syntax,
    not shape or honesty: drop unknown ids, unrecognised resolutions and empty
    reasons rather than storing them.

    An unrecognised or missing basis degrades to "reasoning", never to
    "filing_text" — the permissive default would let a malformed response close
    a flag, and closing hides it.
    """
    if not isinstance(payload, dict):
        return {}
    out: dict[int, tuple[str, str, str]] = {}
    for raw in payload.get("verdicts", []) or []:
        if not isinstance(raw, dict):
            continue
        try:
            flag_id = int(raw.get("id"))
        except (TypeError, ValueError):
            continue
        if flag_id not in valid_ids or flag_id in out:
            continue
        resolution = str(raw.get("resolution") or "").strip().lower()
        reason = str(raw.get("reason") or "").strip()
        if resolution not in LLM_RESOLUTIONS or not reason:
            continue
        basis = str(raw.get("basis") or "").strip().lower()
        if basis not in BASES:
            basis = "reasoning"
        out[flag_id] = (resolution, basis, reason[:512])
    return out


def _ask(llm: OpenAI, prompt: str) -> dict:
    """One model call, with the same backoff contract as kpi_extract."""
    for attempt in range(4):
        try:
            response = llm.chat.completions.create(
                model=KPI_MODEL,
                max_tokens=4096,
                response_format={"type": "json_object"},
                messages=[{"role": "system", "content": _LLM_SYSTEM},
                          {"role": "user", "content": prompt}],
            )
            try:
                return json.loads(response.choices[0].message.content or "{}")
            except json.JSONDecodeError:
                return {}
        except openai.RateLimitError:
            if attempt < 3:
                wait = 20 * (attempt + 1)
                print(f"    rate limited — waiting {wait}s (retry {attempt + 1}/3)")
                time.sleep(wait)
                continue
            raise _RateLimited()
        except openai.APIStatusError as e:
            if e.status_code == 402:
                print("    LLM account has insufficient balance — stopping.")
                raise _RateLimited()
            print(f"    API error {e.status_code}: {e.message}")
            return {}
    return {}


def _prompt_for(ticker: str, filing: dict, excerpt: str, flags: list) -> str:
    lines = [
        f"Company: {ticker}",
        f"Filing provided: {filing['form']} filed {filing['filed_date']} "
        f"(this is the only filing text available to you)",
        "",
        "Disagreements to explain (values are in reported currency units):",
    ]
    for f in flags:
        lines.append(
            f"- id={f.id} concept={f.canonical_concept} fiscal_year={f.fiscal_year} "
            f"ours={f.our_value:+,.0f} reference={f.reference_value:+,.0f} "
            f"magnitude_gap={abs(f.variance):.1%}"
        )
    lines += ["", "Filing excerpt:", "<excerpt>", excerpt, "</excerpt>"]
    return "\n".join(lines)


def triage_company_with_llm(company: Company, flags: list, client: EdgarClient,
                            llm: OpenAI) -> dict[int, tuple[str, str]]:
    """Model verdicts for one company's untriaged flags. Fetches its filing once
    — the whole reason stage 2 batches per company rather than per flag."""
    cik = company.cik
    filing = latest_filing(client.company_submissions(cik))
    text = fetch_filing_text(client, cik, filing)
    excerpt = select_excerpt(text, {f.canonical_concept for f in flags},
                             ticker=company.ticker)
    if not excerpt:
        return {}

    verdicts: dict[int, tuple[str, str]] = {}
    for start in range(0, len(flags), _FLAGS_PER_CALL):
        batch = flags[start:start + _FLAGS_PER_CALL]
        payload = _ask(llm, _prompt_for(company.ticker, filing, excerpt, batch))
        verdicts.update(_clean_verdicts(payload, {f.id for f in batch}))
    return verdicts


def run_llm(limit: int | None = None, dry_run: bool = False) -> dict[str, int]:
    """Stage 2 over companies that still have untriaged flags. Resumable: a
    stored verdict takes a flag out of the pool, so a re-run continues."""
    counts = {"companies": 0, "explained": 0, "needs_review": 0, "inferred": 0,
              "unanswered": 0, "failed": 0}
    with get_session() as session:
        company_ids = list(session.scalars(
            select(ValidationFlag.company_id)
            .where(ValidationFlag.resolution.is_(None))
            .group_by(ValidationFlag.company_id)
            .order_by(ValidationFlag.company_id)
        ))
    if limit:
        company_ids = company_ids[:limit]
    print(f"Stage 2: {len(company_ids)} companies with untriaged flags"
          f"{' (dry run — no model calls)' if dry_run else ''}...")

    if not dry_run:
        require_bulk_provider()
    client = EdgarClient()
    llm = OpenAI(api_key=KPI_API_KEY, base_url=KPI_BASE_URL, timeout=90, max_retries=1)

    for i, company_id in enumerate(company_ids, start=1):
        with get_session() as session:
            company = session.get(Company, company_id)
            flags = list(session.scalars(
                select(ValidationFlag)
                .where(ValidationFlag.company_id == company_id,
                       ValidationFlag.resolution.is_(None))
                .order_by(ValidationFlag.canonical_concept, ValidationFlag.fiscal_year)))
            if company is None or not flags:
                continue
            ticker, flag_ids = company.ticker, [f.id for f in flags]
            if dry_run:
                print(f"  {ticker}: would explain {len(flags)} flags")
                counts["companies"] += 1
                continue
            try:
                verdicts = triage_company_with_llm(company, flags, client, llm)
            except _RateLimited:
                print(f"LLM quota exhausted at {ticker} "
                      f"({i - 1}/{len(company_ids)} companies done) — re-run to resume.")
                raise SystemExit(3)
            except Exception as e:  # one company must not stop the sweep
                counts["failed"] += 1
                print(f"  {ticker}: failed ({type(e).__name__}: {str(e)[:120]})")
                continue

            for flag in flags:
                verdict = verdicts.get(flag.id)
                if verdict is None:
                    counts["unanswered"] += 1
                    continue
                resolution, basis, reason = verdict
                flag.resolution = resolution
                flag.reason = reason
                # Distinguish a verdict read out of the filing from one inferred
                # from the numbers. On the first live run the model returned
                # "restatement" for figures it admitted it could not see, and
                # marking those resolved hid speculation as settled fact.
                verified = basis == "filing_text"
                flag.resolved_by = "model" if verified else "model-inferred"
                # A flag closes only when the verdict is both benign AND read
                # from the filing. real_issue / unexplained are the review
                # queue; an inferred verdict belongs there too.
                flag.resolved = verified and resolution not in NEEDS_REVIEW
                counts["explained"] += 1
                if not flag.resolved:
                    counts["needs_review"] += 1
                if not verified:
                    counts["inferred"] += 1
            session.commit()
            counts["companies"] += 1
            print(f"  {ticker}: {len(verdicts)}/{len(flag_ids)} flags explained")
        if i % 25 == 0:
            print(f"--- {i}/{len(company_ids)} companies "
                  f"({counts['explained']} flags explained) ---")
    return counts


def summary() -> list[tuple]:
    """Current triage state of the whole queue, for reporting."""
    with get_session() as session:
        return list(session.execute(
            select(ValidationFlag.resolution,
                   ValidationFlag.resolved_by,
                   func.count())
            .group_by(ValidationFlag.resolution, ValidationFlag.resolved_by)
            .order_by(func.count().desc())
        ))


def _print_summary() -> None:
    rows = summary()
    total = sum(n for *_, n in rows) or 1
    print(f"{'resolution':<16}{'by':<8}{'flags':>8}  share")
    for resolution, by, n in rows:
        label = resolution or "(untriaged)"
        print(f"{label:<16}{by or '-':<8}{n:>8}  {n / total:>5.1%}")
    print(f"{'TOTAL':<24}{total:>8}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Explain validation flags (stage 1: arithmetic rules)")
    parser.add_argument("--rules", action="store_true",
                        help="stage 1: apply arithmetic rules to untriaged flags (free)")
    parser.add_argument("--llm", action="store_true",
                        help="stage 2: ask the model about what rules could not settle "
                             "(costs tokens; run --rules first)")
    parser.add_argument("--redo", action="store_true",
                        help="with --rules: re-examine already-triaged flags too")
    parser.add_argument("--limit", type=int, default=None,
                        help="with --rules: stop after N flags; with --llm: after N companies")
    parser.add_argument("--dry-run", action="store_true",
                        help="with --llm: list the work without making model calls")
    parser.add_argument("--summary", action="store_true",
                        help="print the current triage state and exit")
    args = parser.parse_args()
    if not (args.rules or args.llm or args.summary):
        parser.error("pass --rules, --llm or --summary")
    init_db()

    if args.rules:
        counts = run_rules(limit=args.limit, redo=args.redo)
        print(f"examined {counts['examined']} flags: "
              f"{counts['convention']} convention, "
              f"{counts['immaterial']} immaterial, "
              f"{counts['deferred']} deferred to stage 2")
        print()
    if args.llm:
        if not KPI_API_KEY:
            raise SystemExit("No LLM key set. Add DEEPSEEK_API_KEY to backend\\.env")
        print(f"LLM provider: {KPI_BASE_URL} | model: {KPI_MODEL}")
        counts = run_llm(limit=args.limit, dry_run=args.dry_run)
        print(f"{counts['companies']} companies: {counts['explained']} flags explained "
              f"({counts['needs_review']} still need human review, of which "
              f"{counts['inferred']} were inferred rather than read from the filing), "
              f"{counts['unanswered']} unanswered, {counts['failed']} companies failed")
        print()
    _print_summary()


if __name__ == "__main__":
    main()
