from datetime import date

from sqlalchemy import Boolean, Date, Float, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from finclone.db import Base


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    cik: Mapped[str] = mapped_column(String(10), unique=True, index=True)
    ticker: Mapped[str] = mapped_column(String(12), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    sic: Mapped[str | None] = mapped_column(String(4))
    sector: Mapped[str | None] = mapped_column(String(64))

    facts: Mapped[list["FinancialFact"]] = relationship(back_populates="company")


class FinancialFact(Base):
    """One reported value for one concept in one fiscal period, from one filing.

    Point-in-time design: the same (concept, period) appears once per filing that
    reported it. The row with the latest filed_date is the current value; earlier
    rows preserve the originally reported (pre-restatement) values.
    """

    __tablename__ = "financial_facts"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "concept", "fiscal_year", "fiscal_period",
            "accession_number", "derived",
            name="uq_fact_per_filing",
        ),
        Index("ix_fact_lookup", "company_id", "canonical_concept", "fiscal_year", "fiscal_period"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))

    concept: Mapped[str] = mapped_column(String(255))  # raw XBRL tag, e.g. us-gaap:Revenues
    canonical_concept: Mapped[str] = mapped_column(String(64), index=True)  # e.g. revenue
    unit: Mapped[str] = mapped_column(String(32))  # USD, shares, USD/shares
    value: Mapped[float] = mapped_column(Float)

    fiscal_year: Mapped[int]
    fiscal_period: Mapped[str] = mapped_column(String(4))  # Q1, Q2, Q3, Q4, FY
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)

    # Provenance / audit trail
    form: Mapped[str] = mapped_column(String(12))  # 10-K, 10-Q, 8-K, ...
    accession_number: Mapped[str] = mapped_column(String(25))
    filed_date: Mapped[date] = mapped_column(Date)
    source_url: Mapped[str] = mapped_column(String(512))

    # True for values we computed (e.g. Q4 = FY - Q1 - Q2 - Q3) rather than reported
    derived: Mapped[bool] = mapped_column(Boolean, default=False)

    company: Mapped[Company] = relationship(back_populates="facts")


class ScreenMetrics(Base):
    """Precomputed latest-fiscal-year screening metrics for one company.

    Scout reads this cache instead of recomputing metrics per company per
    query — required to keep screens fast now that the SimFin baseline puts
    thousands of companies in the database. Refreshed by every ingest path
    (EDGAR ingest, SimFin bulk)."""

    __tablename__ = "screen_metrics"

    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id"), primary_key=True)
    fiscal_year: Mapped[int]
    metrics_json: Mapped[str] = mapped_column(Text)
    updated: Mapped[date] = mapped_column(Date)


class ApiKey(Base):
    """A developer API key (PDR Module 5 / Phase 4). Only the SHA-256 hash is
    stored; the raw key is returned once at creation."""

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    prefix: Mapped[str] = mapped_column(String(12))  # displayable, e.g. "boe_AbC12..."
    tier: Mapped[str] = mapped_column(String(16), default="free")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    requests: Mapped[int] = mapped_column(default=0)  # lifetime usage counter
    created: Mapped[date] = mapped_column(Date)
    # Set for self-serve portal keys; admin-minted keys have no owner account.
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("dev_accounts.id"), index=True)


class DevAccount(Base):
    """Self-serve developer account (portal signup/login).

    Passwords are scrypt-hashed (stdlib, no extra deps). A login issues an
    opaque bearer token whose SHA-256 hash is stored here — one active
    session per account; logging in again rotates it.
    """

    __tablename__ = "dev_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    token_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    token_expires: Mapped[date | None] = mapped_column(Date)
    created: Mapped[date] = mapped_column(Date)


class Subscription(Base):
    """A dev account's paid plan, mirrored from Stripe (PDR Module 5 billing).

    Stripe is the source of truth; this table caches the current state so the
    API can gate tiers without a Stripe round-trip on every request. Webhooks
    keep it in sync. One row per account (created on first checkout). A separate
    table (not columns on dev_accounts) so create_all provisions it without an
    ALTER on the existing accounts table. `tier` mirrors ApiKey.tier values
    (free/pro/enterprise); on an active paid sub the account's keys are set to
    that tier, and reverted to free when the sub lapses."""

    __tablename__ = "subscriptions"

    account_id: Mapped[int] = mapped_column(
        ForeignKey("dev_accounts.id"), primary_key=True)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(64), index=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(64), index=True)
    tier: Mapped[str] = mapped_column(String(16), default="free")
    # Stripe subscription status: active, trialing, past_due, canceled, ...
    status: Mapped[str] = mapped_column(String(24), default="inactive")
    current_period_end: Mapped[date | None] = mapped_column(Date)
    updated: Mapped[date] = mapped_column(Date)


class ApiKeyUsage(Base):
    """Per-day request count per key — feeds the portal's usage graphs."""

    __tablename__ = "api_key_usage"
    __table_args__ = (
        UniqueConstraint("key_id", "day", name="uq_key_usage_day"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    key_id: Mapped[int] = mapped_column(ForeignKey("api_keys.id"), index=True)
    day: Mapped[date] = mapped_column(Date)
    count: Mapped[int] = mapped_column(default=0)


class CrossrefCheck(Base):
    """When a company was last cross-referenced against SimFin.

    The --all sweep skips recently-checked companies so it advances through the
    universe across SimFin's daily-quota windows instead of restarting from A
    each run (a company with zero variance produces no ValidationFlag, so flags
    alone can't distinguish 'checked and clean' from 'never checked')."""

    __tablename__ = "crossref_checks"

    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), primary_key=True)
    checked: Mapped[date] = mapped_column(Date)


class ValidationFlag(Base):
    """A value whose SEC-extracted number disagrees with the reference source
    (SimFin) by more than the variance threshold — queued for human review (PDR §3)."""

    __tablename__ = "validation_flags"
    __table_args__ = (
        UniqueConstraint("company_id", "canonical_concept", "fiscal_year",
                         name="uq_validation_flag"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    canonical_concept: Mapped[str] = mapped_column(String(64))
    fiscal_year: Mapped[int]
    our_value: Mapped[float] = mapped_column(Float)
    reference_value: Mapped[float] = mapped_column(Float)
    variance: Mapped[float] = mapped_column(Float)  # |ours - ref| / |ref|
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)


class SheetTemplate(Base):
    """A user-defined Data Sheet layout (PDR Module 4: MCP).

    config is JSON: {"rows": [
        {"type": "concept", "label": "Revenue", "concept": "revenue"},
        {"type": "formula", "label": "Adjusted EBITDA",
         "expression": "operating_income + stock_based_compensation"},
        {"type": "spacer"}
    ]}
    Applied dynamically during openpyxl generation via ?template_id= on the
    datasheet endpoint.
    """

    __tablename__ = "sheet_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    description: Mapped[str] = mapped_column(String(512), default="")
    config: Mapped[str] = mapped_column(Text)  # JSON


class SeenFiling(Base):
    """Filings the monitor has already processed, so a new 8-K without XBRL
    data doesn't re-trigger ingestion on every polling cycle."""

    __tablename__ = "seen_filings"
    __table_args__ = (
        UniqueConstraint("company_id", "accession_number", name="uq_seen_filing"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    accession_number: Mapped[str] = mapped_column(String(25))
    form: Mapped[str] = mapped_column(String(12))
    filed_date: Mapped[date] = mapped_column(Date)


class KpiFact(Base):
    """A niche KPI extracted by the LLM from MD&A/footnotes (not in XBRL).

    Unlike FinancialFact these are unaudited model output — source_quote holds
    the verbatim filing text the value came from so a human can verify it.
    """

    __tablename__ = "kpi_facts"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "name", "period", "accession_number",
            name="uq_kpi_per_filing",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)

    name: Mapped[str] = mapped_column(String(128))  # e.g. "RevPAR", "ARR"
    value: Mapped[float | None] = mapped_column(Float)  # numeric when parseable
    value_text: Mapped[str] = mapped_column(String(128))  # as written, e.g. "$1.2 billion"
    unit: Mapped[str] = mapped_column(String(64))  # e.g. "USD", "rooms", "%"
    period: Mapped[str] = mapped_column(String(64))  # as reported, e.g. "FY2025", "Q3 2025"

    # Audit trail
    source_quote: Mapped[str] = mapped_column(String(1024))  # verbatim filing text
    form: Mapped[str] = mapped_column(String(12))
    accession_number: Mapped[str] = mapped_column(String(25))
    filed_date: Mapped[date] = mapped_column(Date)
    source_url: Mapped[str] = mapped_column(String(512))

    company: Mapped[Company] = relationship()
