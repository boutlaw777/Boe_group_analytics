"""Scout — natural-language screening (PDR Module 3).

Pipeline: DeepSeek translates the analyst's question into a structured screen
(JSON: sector + metric filters + sort). Our code computes every metric from
the database and applies the filters — the LLM never produces numbers, only
the query structure, so results remain fully auditable.
"""

import json
import time

from openai import OpenAI
from sqlalchemy import select
from sqlalchemy.orm import Session

from finclone.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, SCOUT_MODEL
from finclone.models import Company, KpiFact, ScreenMetrics
from finclone.pipeline.crossref import _our_annual_values

# Metrics the screener understands. Base values come from the latest fiscal
# year; growth compares against the prior year; ratios are derived.
BASE_CONCEPTS = (
    "revenue", "cost_of_revenue", "gross_profit", "research_development",
    "operating_income", "net_income", "eps_diluted", "operating_cash_flow",
    "capex", "stock_based_compensation", "cash_and_equivalents",
    "total_assets", "total_liabilities", "stockholders_equity", "long_term_debt",
)
DERIVED_METRICS = (
    "revenue_growth", "net_income_growth", "gross_margin", "operating_margin",
    "net_margin", "free_cash_flow", "fcf_margin", "roe",
)
METRIC_NAMES: tuple[str, ...] = BASE_CONCEPTS + DERIVED_METRICS

_OPS = {">", ">=", "<", "<="}

_SYSTEM_TEMPLATE = """You translate an analyst's natural-language stock screen \
into a JSON filter specification. You never compute or guess financial values — \
you only produce the query structure.

Available metrics: {metrics}
Available sectors: {sectors}

Respond with JSON only, in exactly this shape:
{{
  "sector": "one of the available sectors, or null",
  "filters": [{{"metric": "metric_name", "op": ">", "value": 0.2}}],
  "sort_by": "metric_name or null",
  "descending": true
}}

Rules:
- op is one of >, >=, <, <=.
- Percentages become decimals (20% -> 0.2). Dollar amounts are absolute USD \
(50 billion -> 50000000000).
- Growth and margin metrics are decimals: revenue_growth 0.2 means +20% YoY.
- Only use the available metrics and sectors. If a criterion cannot be \
expressed with them, omit it — never invent metric names.
- If the query implies a ranking ("most profitable", "largest"), set sort_by \
and use an empty or minimal filter list."""


def compute_metrics(annual: dict[tuple[str, int], float]) -> dict[str, float] | None:
    """Latest-fiscal-year metrics for one company, derived from its annual facts."""
    revenue_years = sorted(fy for (concept, fy) in annual if concept == "revenue")
    if not revenue_years:
        return None
    latest = revenue_years[-1]
    prior = latest - 1

    def v(concept: str, fy: int = latest) -> float | None:
        return annual.get((concept, fy))

    metrics: dict[str, float] = {"fiscal_year": latest}
    for concept in BASE_CONCEPTS:
        value = v(concept)
        if value is not None:
            metrics[concept] = value

    for concept, name in (("revenue", "revenue_growth"), ("net_income", "net_income_growth")):
        cur, prev = v(concept), v(concept, prior)
        if cur is not None and prev:
            metrics[name] = cur / prev - 1

    revenue = metrics.get("revenue")
    if revenue:
        for concept, name in (("gross_profit", "gross_margin"),
                              ("operating_income", "operating_margin"),
                              ("net_income", "net_margin")):
            if concept in metrics:
                metrics[name] = metrics[concept] / revenue

    ocf, capex = metrics.get("operating_cash_flow"), metrics.get("capex")
    if ocf is not None and capex is not None:
        fcf = ocf - abs(capex)
        metrics["free_cash_flow"] = fcf
        if revenue:
            metrics["fcf_margin"] = fcf / revenue

    equity = metrics.get("stockholders_equity")
    if equity and "net_income" in metrics:
        metrics["roe"] = metrics["net_income"] / equity

    return metrics


def sanitize_screen(parsed: object, sectors: list[str]) -> dict:
    """Validate the LLM-produced screen spec; drop anything malformed."""
    if not isinstance(parsed, dict):
        return {"sector": None, "filters": [], "sort_by": None, "descending": True}
    sector = parsed.get("sector")
    if sector not in sectors:
        sector = None
    filters = []
    for f in parsed.get("filters", []) if isinstance(parsed.get("filters"), list) else []:
        if (isinstance(f, dict) and f.get("metric") in METRIC_NAMES
                and f.get("op") in _OPS and isinstance(f.get("value"), (int, float))):
            filters.append({"metric": f["metric"], "op": f["op"], "value": float(f["value"])})
    sort_by = parsed.get("sort_by")
    if sort_by not in METRIC_NAMES:
        sort_by = None
    return {"sector": sector, "filters": filters, "sort_by": sort_by,
            "descending": bool(parsed.get("descending", True))}


def passes_filters(metrics: dict[str, float], filters: list[dict]) -> bool:
    for f in filters:
        value = metrics.get(f["metric"])
        if value is None:
            return False
        threshold = f["value"]
        op = f["op"]
        ok = ((op == ">" and value > threshold) or (op == ">=" and value >= threshold)
              or (op == "<" and value < threshold) or (op == "<=" and value <= threshold))
        if not ok:
            return False
    return True


def translate_query(query: str, sectors: list[str]) -> dict:
    print(f"[scout] query: {query!r} — asking {SCOUT_MODEL} to translate...")
    started = time.monotonic()
    # Default SDK timeout is 600s x 2 retries — a network blip would pin a
    # server thread for many minutes. Translation normally takes ~2s.
    llm = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL,
                 timeout=30, max_retries=1)
    system = _SYSTEM_TEMPLATE.format(metrics=", ".join(METRIC_NAMES),
                                     sectors=", ".join(sectors) or "(none)")
    response = llm.chat.completions.create(
        model=SCOUT_MODEL,
        max_tokens=1024,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": query},
        ],
    )
    try:
        parsed = json.loads(response.choices[0].message.content or "{}")
    except json.JSONDecodeError:
        print("[scout] LLM returned unparseable JSON — falling back to empty screen")
        parsed = {}
    screen = sanitize_screen(parsed, sectors)
    print(f"[scout] LLM translation took {time.monotonic() - started:.1f}s -> "
          f"sector={screen['sector']!r} filters={screen['filters']} sort_by={screen['sort_by']!r}")
    return screen


# Loading 3,000+ companies plus their metrics cache from the cloud database
# costs a few seconds per screen, and both change only on ingest. The API
# opts into this short-lived snapshot (same pattern as /companies); direct
# callers (tests, scripts) read fresh by default.
_UNIVERSE_TTL_SECONDS = 60
_universe_snapshot: tuple[float, list[Company], dict[int, str]] | None = None


def _load_universe(session: Session, use_ttl_cache: bool) -> tuple[list[Company], dict[int, str]]:
    global _universe_snapshot
    if (use_ttl_cache and _universe_snapshot
            and time.monotonic() - _universe_snapshot[0] < _UNIVERSE_TTL_SECONDS):
        return _universe_snapshot[1], _universe_snapshot[2]
    t0 = time.monotonic()
    companies = list(session.scalars(select(Company)))
    cached = {row.company_id: row.metrics_json
              for row in session.scalars(select(ScreenMetrics))}
    print(f"[scout] {len(companies)} companies + {len(cached)} cached metric rows "
          f"loaded in {time.monotonic() - t0:.1f}s")
    if use_ttl_cache:
        _universe_snapshot = (time.monotonic(), companies, cached)
    return companies, cached


def run_screen(session: Session, screen: dict, use_ttl_cache: bool = False) -> list[dict]:
    """Apply a sanitized screen to every company in the database."""
    companies, cached = _load_universe(session, use_ttl_cache)
    display_metrics = {f["metric"] for f in screen["filters"]}
    if screen["sort_by"]:
        display_metrics.add(screen["sort_by"])
    display_metrics.update({"revenue", "revenue_growth", "net_margin"})

    started = time.monotonic()
    live_computes = 0
    results = []
    for company in companies:
        if screen["sector"] and company.sector != screen["sector"]:
            continue
        raw = cached.get(company.id)
        if raw is not None:
            metrics = json.loads(raw)
        else:
            live_computes += 1  # slow path: one DB round-trip per company
            metrics = compute_metrics(_our_annual_values(company.id))
        if metrics is None or not passes_filters(metrics, screen["filters"]):
            continue
        results.append({
            "ticker": company.ticker,
            "name": company.name,
            "sector": company.sector,
            "fiscal_year": metrics["fiscal_year"],
            "metrics": {name: metrics[name] for name in sorted(display_metrics)
                        if name in metrics},
        })

    sort_key = screen["sort_by"] or "revenue"
    results.sort(key=lambda r: r["metrics"].get(sort_key) or float("-inf"),
                 reverse=screen["descending"])
    print(f"[scout] screened {len(companies)} companies in {time.monotonic() - started:.1f}s "
          f"({len(cached)} cached, {live_computes} computed live) -> {len(results)} matches")
    if live_computes > 25:
        print(f"[scout] WARNING: {live_computes} companies missing from the metrics cache — "
              "run: python -m finclone.scout_cache")
    return results


def search_datapoints(session: Session, term: str) -> list[dict]:
    """PDR's Data Point Search: which companies report a given niche KPI."""
    pattern = f"%{term}%"
    rows = session.scalars(
        select(KpiFact).where(KpiFact.name.ilike(pattern)).order_by(KpiFact.name)
    )
    out: dict[tuple[str, str], dict] = {}
    for k in rows:
        company = session.get(Company, k.company_id)
        key = (company.ticker, k.name)
        if key not in out:
            out[key] = {"ticker": company.ticker, "company": company.name,
                        "kpi": k.name, "latest_period": k.period,
                        "latest_value": k.value_text, "source_url": k.source_url}
    return list(out.values())
