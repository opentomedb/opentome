#!/usr/bin/env python3
"""Per-line status rule (spec 2026-09-21 D2): one case per rule plus the boundaries."""
import datetime, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from line_status import line_status, months_before

TODAY = datetime.date(2026, 9, 21)
FAILS = []


def eq(label, got, want):
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        FAILS.append(label)


def run():
    # months_before: whole months, day ignored
    eq("24 months ago exactly is not 'before'", months_before("2024-09-21", TODAY, 24), False)
    eq("25 months ago is before", months_before("2024-08-01", TODAY, 24), True)
    eq("month precision works", months_before("2024-08", TODAY, 24), True)

    # rule 1 -- work ended and reached: completed (today's rule)
    eq("ended + reached", line_status("ended", True, 34, "2021-10-19", 34, "2021-04-09", TODAY), "completed")
    eq("ended + reached via omnibus reach", line_status("ended", True, 34, "2021-10-19", 34, None, TODAY), "completed")
    eq("ended + no origin known", line_status("ended", True, 5, "2015-01-01", None, None, TODAY), "completed")

    # rule 2 -- stalled: >= 2 behind, quiet 24 months, origin kept going
    eq("Gintama shape", line_status("ended", True, 23, "2011-08-02", 77, "2019-08-02", TODAY), "stalled")
    eq("ongoing work, licence dead", line_status("ongoing", True, 12, "2019-03-05", 30, "2026-05-01", TODAY), "stalled")
    eq("arc line can stall too", line_status("ongoing", False, 2, "2018-01-01", 6, "2020-01-01", TODAY), "stalled")
    eq("one behind is not stalled", line_status("ended", True, 12, "2019-03-05", 13, "2020-01-01", TODAY), "ongoing")
    eq("quiet but origin quieter is not stalled", line_status("ongoing", True, 12, "2020-03-05", 15, "2019-01-01", TODAY), "ongoing")
    eq("behind but shipped recently", line_status("ongoing", True, 12, "2026-03-05", 20, "2026-06-01", TODAY), "ongoing")
    eq("no dates cannot stall", line_status("ongoing", True, 12, None, 20, "2026-06-01", TODAY), "ongoing")
    eq("origin later by month, mixed precision, stalls", line_status("ongoing", True, 12, "2019-03-05", 30, "2019-04", TODAY), "stalled")
    eq("origin same month at day precision is not later", line_status("ongoing", True, 12, "2019-03", 30, "2019-03-28", TODAY), "ongoing")

    # rule 3 -- shipped within 24 months
    eq("recent = ongoing regardless of work status", line_status(None, True, 3, "2025-11-01", None, None, TODAY), "ongoing")

    # rule 4 -- caught up and quiet
    eq("finished arc, both quiet", line_status("ongoing", False, 6, "2015-06-01", 6, "2014-12-01", TODAY), "completed")
    eq("finished arc, origin undated", line_status("ongoing", False, 6, "2015-06-01", 6, None, TODAY), "completed")
    eq("main line on hiatus", line_status("ongoing", True, 28, "2023-06-01", 28, "2023-01-01", TODAY), "ongoing")
    eq("caught up, origin still shipping", line_status("ongoing", False, 6, "2023-06-01", 6, "2026-06-01", TODAY), "ongoing")

    # rule 5 -- nothing decides
    eq("no work status, no dates", line_status(None, True, 3, None, None, None, TODAY), None)
    eq("no work status, quiet, behind by one", line_status(None, True, 3, "2020-01-01", 4, "2021-01-01", TODAY), None)
    eq("no volumes at all", line_status("ongoing", True, None, None, 10, "2026-01-01", TODAY), "ongoing")
    eq("a year-only date is unknown, not a crash", line_status("ongoing", True, 3, "2019", 10, "2026", TODAY), "ongoing")
    eq("exactly two behind can stall", line_status("ongoing", True, 10, "2019-03-05", 12, "2026-01-01", TODAY), "stalled")

    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        sys.exit(1)
    print("line_status ok")


if __name__ == "__main__":
    run()
