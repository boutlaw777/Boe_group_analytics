"""Backfill that restandardizes KPI rows extracted before name resolution.

The merge path is what these cover: KpiFact is unique on
(company, name, period, accession), so renaming a row onto its canonical name
can collide with a row already holding it — the same datapoint recorded twice
under two spellings. Getting that wrong either crashes the backfill or deletes
a distinct measurement, so it is tested rather than trusted.
"""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from finclone.db import Base
from finclone.models import Company, KpiFact
from finclone.pipeline.normalize_kpis import plan_company


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as s:
        yield s


@pytest.fixture()
def hotel(session):
    c = Company(cik="0000000002", ticker="HOT", name="Hotel Co",
                sector="Hospitality", sic="7011")
    session.add(c)
    session.commit()
    return c


def _kpi(company, name, period, value=100.0, unit="USD", accession="0001-25-000001"):
    return KpiFact(
        company_id=company.id, name=name, value=value, value_text=str(value),
        unit=unit, period=period, source_quote="q", form="10-K",
        accession_number=accession, filed_date=date(2025, 11, 1), source_url="u")


def test_drifted_name_is_renamed_to_the_industry_label(session, hotel):
    session.add(_kpi(hotel, "Revenue per available room", "Q3 FY2025"))
    session.commit()
    renames, deletions = plan_company(session, hotel)
    assert not deletions
    assert [(r[1], r[2]) for r in renames] == [
        ("RevPAR (revenue per available room)", "Q3 FY2025")]


def test_two_spellings_of_one_datapoint_merge_to_one_row(session, hotel):
    """The exact duplication the standardization exists to prevent, already in
    the database: both rows quote the same filing for the same quarter."""
    session.add(_kpi(hotel, "RevPAR (revenue per available room)", "Q3 FY2025"))
    session.add(_kpi(hotel, "RevPAR", "Q3 FY2025"))
    session.commit()
    renames, deletions = plan_company(session, hotel)
    assert [d.name for d in deletions] == ["RevPAR"]
    assert not renames


def test_same_metric_in_different_quarters_is_never_merged(session, hotel):
    session.add(_kpi(hotel, "RevPAR", "Q3 FY2025"))
    session.add(_kpi(hotel, "RevPAR", "Q2 FY2025"))
    session.commit()
    renames, deletions = plan_company(session, hotel)
    assert not deletions
    assert len(renames) == 2


def test_same_metric_from_two_filings_is_never_merged(session, hotel):
    """Point-in-time storage: the same period restated in a later filing is a
    separate row by design, and the accession is what keeps them apart."""
    session.add(_kpi(hotel, "RevPAR", "FY2025", accession="0001-25-000001"))
    session.add(_kpi(hotel, "RevPAR", "FY2025", accession="0001-26-000002"))
    session.commit()
    renames, deletions = plan_company(session, hotel)
    assert not deletions
    assert len(renames) == 2


def test_period_and_unit_are_restandardized_too(session, hotel):
    session.add(_kpi(hotel, "Occupancy rate", "Q3 2025", unit="%"))
    session.commit()
    renames, _ = plan_company(session, hotel)
    row, name, period, unit = renames[0]
    assert (name, period, unit) == ("Occupancy rate", "Q3 FY2025", "percent")


def test_unlisted_kpi_keeps_its_name(session, hotel):
    """A KPI outside the industry's target list is still real data; the backfill
    normalizes its period but must not rename it to something it isn't."""
    session.add(_kpi(hotel, "Loyalty program members", "Q3 2025"))
    session.commit()
    renames, deletions = plan_company(session, hotel)
    assert not deletions
    assert renames[0][1] == "Loyalty program members"
    assert renames[0][2] == "Q3 FY2025"


def test_already_standard_rows_are_left_alone(session, hotel):
    session.add(_kpi(hotel, "RevPAR (revenue per available room)", "Q3 FY2025"))
    session.commit()
    assert plan_company(session, hotel) == ([], [])
