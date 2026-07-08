from finclone.pipeline.crossref import variance


def test_variance_identical_values():
    assert variance(100.0, 100.0) == 0.0


def test_variance_sign_conventions_ignored():
    # SimFin reports capex negative; XBRL positive — magnitudes match => 0
    assert variance(500.0, -500.0) == 0.0


def test_variance_relative_difference():
    assert abs(variance(101.0, 100.0) - 0.01) < 1e-9
    assert variance(150.0, 100.0) == 0.5


def test_variance_zero_reference():
    assert variance(0.0, 0.0) == 0.0
    assert variance(5.0, 0.0) == float("inf")
