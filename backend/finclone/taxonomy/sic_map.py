"""SIC code → FinClone sector mapping.

Baseline industry taxonomy from the SEC's own SIC classification. Sector drives
which industry-specific KPI extractors and Data Sheet tabs apply (Phase 1
milestone 2 extends this with per-sector KPI definitions).
"""

_SIC_RANGES: tuple[tuple[int, int, str], ...] = (
    (100, 999, "Agriculture"),
    (1000, 1499, "Mining"),
    (1300, 1399, "Oil & Gas"),
    (1500, 1799, "Construction"),
    (2000, 2199, "Food & Beverage"),
    (2800, 2899, "Chemicals"),
    (2833, 2836, "Pharmaceuticals & Biotech"),
    (3570, 3579, "Computer Hardware"),
    (3600, 3699, "Electronics & Semiconductors"),
    (3674, 3674, "Semiconductors"),
    (3711, 3716, "Automotive"),
    (2000, 3999, "Manufacturing"),
    (4000, 4799, "Transportation"),
    (4800, 4899, "Telecommunications"),
    (4900, 4999, "Utilities"),
    (5000, 5199, "Wholesale"),
    (5200, 5999, "Retail"),
    (6000, 6099, "Banking"),
    (6100, 6199, "Credit & Lending"),
    (6200, 6299, "Capital Markets"),
    (6300, 6499, "Insurance"),
    (6500, 6599, "Real Estate"),
    (6798, 6798, "REITs"),
    (7000, 7099, "Hospitality"),
    (7370, 7372, "Software & SaaS"),
    (7373, 7379, "IT Services"),
    (7800, 7999, "Media & Entertainment"),
    (8000, 8099, "Healthcare Services"),
)


def sector_for_sic(sic: str | None) -> str | None:
    """More specific ranges win over broad ones (narrowest matching range)."""
    if not sic:
        return None
    try:
        code = int(sic)
    except ValueError:
        return None
    matches = [(hi - lo, name) for lo, hi, name in _SIC_RANGES if lo <= code <= hi]
    if not matches:
        return "Other"
    return min(matches)[1]
