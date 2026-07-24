"""FinClone base REST API (Phase 1).

Endpoints per PDR Module 5: /companies and /companies/{ticker}/financials,
with SEC audit URLs on every number. Auth, rate limiting, and the remaining
endpoints land in Phase 4.
"""

import json
import sys
import time
from datetime import date as _date

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from finclone.api import auth as api_auth
from finclone.api import portal
from finclone.db import get_session, init_db
from finclone.models import (ApiKey, ApiKeyUsage, Company, FinancialFact, KpiFact,
                             SheetTemplate, ValidationFlag)
from finclone.pipeline.ingest import current_facts

# Paths served without an API key even when enforcement is on
# (/auth and /me are the developer portal — they use their own bearer tokens)
_PUBLIC_PATHS = ("/", "/health", "/docs", "/openapi.json", "/redoc", "/admin",
                 "/auth", "/me")


async def require_api_key(
    request: Request,
    x_api_key: str | None = Header(None, alias="X-API-Key"),
) -> None:
    """Validate the X-API-Key header and enforce tier rate limits (PDR Module 5).

    Enforcement is opt-in: set FINCLONE_REQUIRE_API_KEY=true. Admin and docs
    routes stay public (admin has its own token check). Plain download links
    (Data Sheets, bulk zips) can't carry headers, so ?api_key= is accepted as
    a fallback.
    """
    if not api_auth.require_enabled():
        # Open mode still counts usage for a key that's voluntarily presented,
        # so the portal's graphs work in local/dev deployments too.
        if x_api_key:
            _count_key_usage(x_api_key)
        return
    # Behind a prefix-stripping proxy (uvicorn --root-path /api), the ASGI
    # path still includes the prefix — strip it so path checks match the
    # app's own routes in every deployment.
    path = request.url.path
    root = request.scope.get("root_path", "")
    if root and path.startswith(root):
        path = path[len(root):] or "/"
    if path == "/" or any(path.startswith(p) and p != "/" for p in _PUBLIC_PATHS):
        return
    # Data-sheet downloads stay public even under enforcement: the website's
    # download buttons are plain browser links, which can't carry a key
    # without exposing it to every visitor.
    if path.startswith("/datasheets") or (
            path.startswith("/companies/") and path.endswith("/datasheet")):
        return
    if not x_api_key:
        x_api_key = request.query_params.get("api_key")
    if not x_api_key:
        raise HTTPException(401, "Missing X-API-Key header")
    session = get_session()
    try:
        key = session.scalar(select(ApiKey).where(ApiKey.key_hash == api_auth.hash_key(x_api_key)))
        if key is None or not key.active:
            raise HTTPException(401, "Invalid or revoked API key")
        retry_in = api_auth.limiter.check(str(key.id), key.tier)
        if retry_in is not None:
            raise HTTPException(
                429, f"Rate limit exceeded for tier '{key.tier}' — retry in {retry_in:.0f}s")
        try:
            key.requests += 1
            _record_usage(session, key.id)
            session.commit()
        except Exception:
            # Usage counters are best-effort — a read-only database (e.g.
            # Supabase quota enforcement) must never break authentication.
            session.rollback()
    finally:
        session.close()


def _record_usage(session: Session, key_id: int) -> None:
    """Daily usage row for the portal graphs (single worker, so the
    read-then-write is race-free enough at this scale)."""
    today = _date.today()
    usage = session.scalar(select(ApiKeyUsage).where(
        ApiKeyUsage.key_id == key_id, ApiKeyUsage.day == today))
    if usage is None:
        session.add(ApiKeyUsage(key_id=key_id, day=today, count=1))
    else:
        usage.count += 1


def _count_key_usage(raw_key: str) -> None:
    """Best-effort usage counting when enforcement is off."""
    session = get_session()
    try:
        key = session.scalar(select(ApiKey).where(ApiKey.key_hash == api_auth.hash_key(raw_key)))
        if key is not None and key.active:
            key.requests += 1
            _record_usage(session, key.id)
            session.commit()
    except Exception:
        session.rollback()
    finally:
        session.close()


def _require_admin(x_admin_token: str | None = Header(None, alias="X-Admin-Token")) -> None:
    token = api_auth.admin_token()
    if not token:
        raise HTTPException(503, "Admin API disabled — set FINCLONE_ADMIN_TOKEN in backend\\.env")
    if x_admin_token != token:
        raise HTTPException(401, "Invalid admin token")


if sys.platform == "win32":
    # Windows asyncio (Proactor) prints a harmless ConnectionResetError
    # traceback whenever a client drops its connection after a completed
    # request (WinError 10054). Purely cosmetic — swallow it so server logs
    # stay readable. Requests are unaffected either way.
    from functools import wraps

    from asyncio.proactor_events import _ProactorBasePipeTransport

    def _quiet_connection_reset(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            try:
                return func(self, *args, **kwargs)
            except ConnectionResetError:
                pass
        return wrapper

    _ProactorBasePipeTransport._call_connection_lost = _quiet_connection_reset(
        _ProactorBasePipeTransport._call_connection_lost
    )

app = FastAPI(title="BOE Analytics API", version="0.1.0",
              dependencies=[Depends(require_api_key)])

# Dev CORS: lets the Excel add-in task pane (https://localhost:3100) call the
# API from the browser. Lock allow_origins down before production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Self-serve developer portal: /auth/*, /me/* (bearer-token authenticated)
app.include_router(portal.router)


@app.on_event("startup")
def _startup() -> None:
    init_db()


def _session() -> Session:
    session = get_session()
    try:
        yield session
    finally:
        session.close()


def _get_company(session: Session, ticker: str) -> Company:
    company = session.scalar(select(Company).where(Company.ticker == ticker.upper()))
    if company is None:
        raise HTTPException(404, f"Company not ingested: {ticker.upper()}")
    return company


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/docs")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


# /companies scans the whole universe to classify SEC vs baseline coverage —
# too slow to run per page view at thousands of companies. The list only
# changes on ingest, so a short TTL cache keeps the landing/dashboard instant.
_COMPANIES_TTL_SECONDS = 60
_companies_cache: tuple[float, list[dict]] | None = None


@app.get("/companies")
def list_companies(session: Session = Depends(_session)) -> list[dict]:
    """All covered companies. source="sec" means filing-level SEC extraction;
    "baseline" means standardized SimFin baseline data (pre-SEC upgrade)."""
    global _companies_cache
    if _companies_cache and time.monotonic() - _companies_cache[0] < _COMPANIES_TTL_SECONDS:
        return _companies_cache[1]
    sec_ids = set(session.scalars(
        select(FinancialFact.company_id)
        .where(FinancialFact.accession_number != "simfin-baseline")
        .distinct()
    ))
    result = [
        {"ticker": c.ticker, "name": c.name, "cik": c.cik, "sector": c.sector,
         "source": "sec" if c.id in sec_ids else "baseline"}
        for c in session.scalars(select(Company).order_by(Company.ticker))
    ]
    _companies_cache = (time.monotonic(), result)
    return result


@app.get("/companies/{ticker}")
def get_company(ticker: str, session: Session = Depends(_session)) -> dict:
    c = _get_company(session, ticker)
    return {"ticker": c.ticker, "name": c.name, "cik": c.cik, "sic": c.sic, "sector": c.sector}


@app.get("/companies/{ticker}/financials")
def get_financials(
    ticker: str,
    concept: str | None = Query(None, description="Canonical concept, e.g. revenue"),
    fiscal_year: int | None = None,
    fiscal_period: str | None = Query(None, description="Q1-Q4 or FY"),
    point_in_time: str = Query("latest", pattern="^(latest|original|all)$"),
    session: Session = Depends(_session),
) -> list[dict]:
    """Time series of financial facts with full audit provenance.

    point_in_time=latest returns current (post-restatement) values;
    original returns as-first-reported values; all returns every vintage.
    """
    company = _get_company(session, ticker)
    stmt = select(FinancialFact).where(FinancialFact.company_id == company.id)
    if concept:
        stmt = stmt.where(FinancialFact.canonical_concept == concept)
    if fiscal_year:
        stmt = stmt.where(FinancialFact.fiscal_year == fiscal_year)
    if fiscal_period:
        stmt = stmt.where(FinancialFact.fiscal_period == fiscal_period.upper())
    rows = list(session.scalars(stmt))

    if point_in_time == "all":
        selected = rows
    else:
        grouped: dict[tuple, list[FinancialFact]] = {}
        for f in rows:
            grouped.setdefault((f.canonical_concept, f.fiscal_year, f.fiscal_period), []).append(f)
        if point_in_time == "latest":
            selected = [f for facts in grouped.values() if (f := current_facts(facts))]
        else:  # original: earliest SEC filing for each period (a SimFin
            # baseline row is standardized data, not an as-reported vintage)
            selected = []
            for facts in grouped.values():
                sec = [f for f in facts
                       if f.accession_number != "simfin-baseline"] or facts
                selected.append(min(sec, key=lambda f: f.filed_date))

    selected.sort(key=lambda f: (f.canonical_concept, f.fiscal_year, f.fiscal_period))
    return _facts_to_json(selected)


@app.get("/companies/{ticker}/kpis")
def get_kpis(ticker: str, session: Session = Depends(_session)) -> list[dict]:
    """LLM-extracted niche KPIs (RevPAR, ARR, ...) with verbatim source quotes."""
    company = _get_company(session, ticker)
    rows = session.scalars(
        select(KpiFact).where(KpiFact.company_id == company.id).order_by(KpiFact.name)
    )
    return [
        {
            "name": k.name,
            "value": k.value,
            "value_text": k.value_text,
            "unit": k.unit,
            "period": k.period,
            "source_quote": k.source_quote,
            "form": k.form,
            "filed_date": k.filed_date.isoformat(),
            "source_url": k.source_url,
        }
        for k in rows
    ]


@app.get("/companies/{ticker}/datasheet")
def download_datasheet(
    ticker: str,
    period: str = Query("annual", pattern="^(annual|quarterly)$"),
    template_id: int | None = Query(None, description="Apply a custom MCP template"),
    concepts: str | None = Query(
        None, description="Comma-separated canonical concepts to include, e.g. revenue,net_income"),
    year_from: int | None = Query(None, ge=1990, le=2100),
    year_to: int | None = Query(None, ge=1990, le=2100),
    quarters: str | None = Query(
        None, description="Comma-separated quarters for the quarterly view, e.g. Q1,Q4"),
    session: Session = Depends(_session),
) -> Response:
    """Download the auditable Excel Data Sheet (PDR Module 1).

    Blue numbers are as-reported and hyperlink to their SEC filing;
    black cells are live Excel formulas. Pass template_id to apply a
    custom layout (PDR Module 4: MCP), or the picker params (concepts,
    year_from/year_to, quarters) to narrow the sheet.
    """
    from finclone.sheets.datasheet import generate_datasheet
    from finclone.sheets.templates import generate_from_template

    concept_set = {c.strip() for c in concepts.split(",") if c.strip()} if concepts else None
    quarter_set = None
    if quarters:
        quarter_set = {q.strip().upper() for q in quarters.split(",") if q.strip()}
        if not quarter_set <= {"Q1", "Q2", "Q3", "Q4"}:
            raise HTTPException(422, "quarters must be a comma-separated subset of Q1,Q2,Q3,Q4")

    company = _get_company(session, ticker)
    if template_id is not None:
        template = session.get(SheetTemplate, template_id)
        if template is None:
            raise HTTPException(404, f"Template not found: {template_id}")
        content = generate_from_template(
            session, company, json.loads(template.config), template.name, period=period
        )
        filename = f"{company.ticker}_{template.name.replace(' ', '_')}_{period}.xlsx"
    else:
        content = generate_datasheet(
            session, company, period=period, concepts=concept_set,
            year_from=year_from, year_to=year_to, quarters=quarter_set,
        )
        filename = f"{company.ticker}_datasheet_{period}.xlsx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/companies/{ticker}/validation")
def get_validation_flags(ticker: str, session: Session = Depends(_session)) -> list[dict]:
    """Values that disagree with the cross-reference source by >1% (PDR §3) —
    the human-review queue."""
    company = _get_company(session, ticker)
    rows = session.scalars(
        select(ValidationFlag)
        .where(ValidationFlag.company_id == company.id)
        .order_by(ValidationFlag.variance.desc())
    )
    return [
        {
            "concept": v.canonical_concept,
            "fiscal_year": v.fiscal_year,
            "our_value": v.our_value,
            "reference_value": v.reference_value,
            "variance": v.variance,
            "resolved": v.resolved,
        }
        for v in rows
    ]


@app.get("/scout")
def scout_screen(
    q: str = Query(..., min_length=3, description="Natural-language screen"),
    session: Session = Depends(_session),
) -> dict:
    """Scout (PDR Module 3): translate a natural-language screen into filters
    and run it. The LLM only builds the query structure — every number is
    computed from the database."""
    import openai

    from finclone.config import DEEPSEEK_API_KEY
    from finclone.scout import run_screen, translate_query

    if not DEEPSEEK_API_KEY:
        raise HTTPException(503, "DEEPSEEK_API_KEY is not configured on the backend")
    sectors = sorted({c.sector for c in session.scalars(select(Company)) if c.sector})
    try:
        screen = translate_query(q, sectors)
    except openai.APIStatusError as e:
        detail = "DeepSeek account has insufficient balance" if e.status_code == 402 \
            else f"LLM error {e.status_code}"
        raise HTTPException(502, detail)
    except openai.APIError as e:
        raise HTTPException(502, f"LLM error: {e}")
    return {"query": q, "interpretation": screen,
            "results": run_screen(session, screen, use_ttl_cache=True)}


@app.get("/scout/datapoints")
def scout_datapoints(
    q: str = Query(..., min_length=2, description="KPI name to search for"),
    session: Session = Depends(_session),
) -> list[dict]:
    """PDR's Data Point Search: find companies reporting a niche KPI."""
    from finclone.scout import search_datapoints

    return search_datapoints(session, q)


class TemplateIn(BaseModel):
    name: str
    description: str = ""
    config: dict


def _template_json(t: SheetTemplate) -> dict:
    return {"id": t.id, "name": t.name, "description": t.description,
            "config": json.loads(t.config)}


@app.get("/templates")
def list_templates(session: Session = Depends(_session)) -> list[dict]:
    return [_template_json(t) for t in session.scalars(select(SheetTemplate).order_by(SheetTemplate.name))]


@app.post("/templates", status_code=201)
def create_template(body: TemplateIn, session: Session = Depends(_session)) -> dict:
    """Save a custom Data Sheet layout (PDR Module 4: MCP)."""
    from finclone.sheets.templates import validate_config

    try:
        validate_config(body.config)
    except ValueError as e:
        raise HTTPException(422, str(e))
    if session.scalar(select(SheetTemplate).where(SheetTemplate.name == body.name)):
        raise HTTPException(409, f"A template named {body.name!r} already exists")
    template = SheetTemplate(name=body.name, description=body.description,
                             config=json.dumps(body.config))
    session.add(template)
    session.commit()
    return _template_json(template)


@app.delete("/templates/{template_id}", status_code=204)
def delete_template(template_id: int, session: Session = Depends(_session)) -> None:
    template = session.get(SheetTemplate, template_id)
    if template is None:
        raise HTTPException(404, f"Template not found: {template_id}")
    session.delete(template)
    session.commit()


def _facts_to_json(selected: list[FinancialFact]) -> list[dict]:
    return [
        {
            "concept": f.canonical_concept,
            "xbrl_tag": f.concept,
            "value": f.value,
            "unit": f.unit,
            "fiscal_year": f.fiscal_year,
            "fiscal_period": f.fiscal_period,
            "end_date": f.end_date.isoformat(),
            "form": f.form,
            "filed_date": f.filed_date.isoformat(),
            "derived": f.derived,
            "source_url": f.source_url,
        }
        for f in selected
    ]


# --- API key management (PDR Module 5 / Phase 4) ---------------------------
# Protected by X-Admin-Token (FINCLONE_ADMIN_TOKEN). Raw keys are shown once.

class KeyCreate(BaseModel):
    name: str
    tier: str = "free"


def _key_json(k: ApiKey) -> dict:
    return {"id": k.id, "name": k.name, "prefix": k.prefix, "tier": k.tier,
            "active": k.active, "requests": k.requests, "created": k.created.isoformat()}


@app.post("/admin/keys", dependencies=[Depends(_require_admin)])
def create_api_key(body: KeyCreate, session: Session = Depends(_session)) -> dict:
    """Create an API key. The raw key appears in this response only — store it."""
    if body.tier not in api_auth.TIER_LIMITS:
        raise HTTPException(422, f"tier must be one of {sorted(api_auth.TIER_LIMITS)}")
    raw = api_auth.generate_key()
    key = ApiKey(name=body.name, key_hash=api_auth.hash_key(raw), prefix=raw[:12],
                 tier=body.tier, created=_date.today())
    session.add(key)
    session.commit()
    return {**_key_json(key), "api_key": raw}


@app.get("/admin/keys", dependencies=[Depends(_require_admin)])
def list_api_keys(session: Session = Depends(_session)) -> list[dict]:
    return [_key_json(k) for k in session.scalars(select(ApiKey).order_by(ApiKey.id))]


@app.delete("/admin/keys/{key_id}", dependencies=[Depends(_require_admin)])
def revoke_api_key(key_id: int, session: Session = Depends(_session)) -> dict:
    key = session.get(ApiKey, key_id)
    if key is None:
        raise HTTPException(404, f"Key not found: {key_id}")
    key.active = False
    session.commit()
    return _key_json(key)


# --- Bulk Data Sheets (PDR Module 3: export screened list) ------------------

@app.get("/datasheets")
def download_datasheets_bulk(
    tickers: str = Query(..., description="Comma-separated tickers, e.g. AAPL,MSFT"),
    period: str = Query("annual", pattern="^(annual|quarterly)$"),
    session: Session = Depends(_session),
) -> Response:
    """Bulk-download Data Sheets for a screened list as a single .zip
    (PDR Module 3: export). Unknown tickers are skipped and listed in a
    MANIFEST.txt inside the archive."""
    import io
    import zipfile

    from finclone.sheets.datasheet import generate_datasheet

    wanted = [t.strip().upper() for t in tickers.split(",") if t.strip()][:50]
    if not wanted:
        raise HTTPException(422, "tickers must be a non-empty comma-separated list")

    buffer = io.BytesIO()
    included: list[str] = []
    skipped: list[str] = []
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for t in wanted:
            company = session.scalar(select(Company).where(Company.ticker == t))
            if company is None:
                skipped.append(t)
                continue
            zf.writestr(f"{t}_datasheet_{period}.xlsx",
                        generate_datasheet(session, company, period=period))
            included.append(t)
        manifest = [f"BOE Analytics bulk Data Sheets ({period})",
                    f"Included: {', '.join(included) or 'none'}"]
        if skipped:
            manifest.append(f"Skipped (not ingested): {', '.join(skipped)}")
        zf.writestr("MANIFEST.txt", "\n".join(manifest))

    if not included:
        raise HTTPException(404, f"None of these tickers are ingested: {', '.join(wanted)}")
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="datasheets_{period}.zip"'},
    )
