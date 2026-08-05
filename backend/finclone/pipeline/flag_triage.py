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

from sqlalchemy import func, select

from finclone.db import get_session, init_db
from finclone.models import ValidationFlag

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
                        help="apply arithmetic rules to untriaged flags")
    parser.add_argument("--redo", action="store_true",
                        help="with --rules: re-examine already-triaged flags too")
    parser.add_argument("--limit", type=int, default=None,
                        help="with --rules: stop after this many flags")
    parser.add_argument("--summary", action="store_true",
                        help="print the current triage state and exit")
    args = parser.parse_args()
    if not (args.rules or args.summary):
        parser.error("pass --rules or --summary")
    init_db()

    if args.rules:
        counts = run_rules(limit=args.limit, redo=args.redo)
        print(f"examined {counts['examined']} flags: "
              f"{counts['convention']} convention, "
              f"{counts['immaterial']} immaterial, "
              f"{counts['deferred']} deferred to stage 2")
        print()
    _print_summary()


if __name__ == "__main__":
    main()
