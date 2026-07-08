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
