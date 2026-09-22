"""Per-line status for a LICENSED release line (spec 2026-09-21, D2).

A work's status (ended | ongoing, from its Wikipedia infobox) says nothing about an
English or French edition: a licence can stop at 23 of 77 while the original finished.
This rule reads the line's own dates against its original-market counterpart's.

    completed  work ended and the line reached the origin's top volume (today's rule),
               or a finished arc: caught up, and neither market shipped in 24 months
    stalled    at least two volumes behind, nothing shipped in 24 months, origin kept going
    ongoing    shipped within 24 months, or a main line on hiatus / one volume behind
    None       nothing to decide from

`cancelled` is deliberately not derived: it needs a fact (a publisher statement), which
is the corrections path. Origin-market lines never come here -- they keep the work's status.
"""
import datetime

STALLED_MONTHS = 24     # spec §6 decision 1
STALLED_BEHIND = 2      # volumes


def months_before(date_str, today, months):
    """True when date_str (YYYY-MM-DD or YYYY-MM) is more than `months` whole months before today."""
    y, m = int(date_str[:4]), int(date_str[5:7])
    return (today.year - y) * 12 + (today.month - m) > months


def line_status(work_status, is_named, max_vol, last_dated, origin_max, origin_last_dated, today,
                months=STALLED_MONTHS, behind=STALLED_BEHIND):
    # Only YYYY-MM or YYYY-MM-DD strings reach here (the exporter filters precision); a
    # shorter value is treated as unknown rather than crashing the export on one bad row.
    last_dated = last_dated if last_dated and len(last_dated) >= 7 else None
    origin_last_dated = origin_last_dated if origin_last_dated and len(origin_last_dated) >= 7 else None
    quiet = last_dated is None or months_before(last_dated, today, months)
    origin_quiet = origin_last_dated is None or months_before(origin_last_dated, today, months)
    known = origin_max is not None and max_vol is not None
    reached = known and max_vol >= origin_max
    gap = (origin_max - max_vol) if known else None

    # 1. today's rule: the work is over and the licence covered it (or no origin to compare)
    if work_status == "ended" and (reached or origin_max is None):
        return "completed"
    # 2. stalled: well behind, dead for 24 months, while the origin kept publishing
    if (gap is not None and gap >= behind and last_dated and quiet
            and (origin_last_dated is None or origin_last_dated[:7] > last_dated[:7])):
        return "stalled"
    # 3. still shipping
    if not quiet:
        return "ongoing"
    # 4. caught up and quiet on both sides: a finished arc / spin-off. A main line is the
    #    work's own run, so its status (hiatus is still ongoing) decides below.
    if reached and last_dated and origin_quiet and not is_named:
        return "completed"
    # 5. behind by less than `behind`, or on hiatus: the work's word, mapped to a line
    if work_status in ("ongoing", "ended"):
        return "ongoing"
    return None
