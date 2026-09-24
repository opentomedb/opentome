"""Test the calibration rule's branches with synthetic claims.

The rule is the product's differentiator and, on real data so far, only its
'agree' paths have executed. Untested branches in the code that decides what
to trust is exactly the wrong place to have them.
"""
import os, sqlite3, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from resolve import resolve, classify_dates, _compatible

CASES = [
    # (name, claim values by source, expected basis)
    ("identical",        {"wikipedia": "2020-04-21", "openbd": "2020-04-21"}, "agreed"),
    ("coarser openBD",   {"wikipedia": "2020-04-21", "openbd": "2020-04"},    "agreed_coarse"),
    ("7-day offset",     {"wikipedia": "2020-04-21", "publisher": "2020-04-14"}, "semantic_variance"),
    ("28-day offset",    {"wikipedia": "2020-04-21", "publisher": "2020-03-24"}, "semantic_variance"),
    ("42-day offset",    {"wikipedia": "2023-10-03", "publisher": "2023-08-22"}, "semantic_variance"),
    ("161-day (23wk)",   {"wikipedia": "2021-12-28", "publisher": "2021-07-20"}, "escalated"),
    ("826-day (118wk)",  {"wikipedia": "2018-01-30", "publisher": "2015-10-27"}, "escalated"),
    # sub-week, non-week-multiple: near-agreement of unexplained cause.
    # 46% of French conflicts looked like this -- the week-multiple rule encodes
    # US Tuesday street dates and France has no equivalent weekly grid.
    ("4-day (sub-week)",  {"wikipedia": "2018-08-18", "publisher": "2018-08-14"}, "minor_variance"),
    ("10-day non-week",   {"wikipedia": "2020-04-21", "publisher": "2020-04-11"}, "conflict"),
    ("100-day non-week",  {"wikipedia": "2020-04-21", "publisher": "2020-01-12"}, "conflict"),
    ("single source",    {"wikipedia": "2020-04-21"},                          "single_source"),
]

VALUE_CASES = [
    # DNB ranks above Wikipedia, but its 008 year is the coarsest date there is: a
    # late-December release catalogued under the next year must not beat the day date.
    ("dnb year vs wikipedia day, years differ", {"dnb": "2020", "wikipedia": "2019-12-20"}, "2019-12-20"),
    ("dnb year agrees with wikipedia day",      {"dnb": "2019", "wikipedia": "2019-12-20"}, "2019-12-20"),
    ("dnb year alone",                          {"dnb": "2019"},                            "2019"),
]


def run():
    fails = 0
    db = sqlite3.connect(":memory:")
    db.executescript(open(os.path.join(os.path.dirname(HERE), "schema", "schema.sql")).read())
    for i, (name, claims, expect) in enumerate(CASES):
        vid = f"v_test{i:08d}"
        for src, val in claims.items():
            db.execute("""INSERT INTO claim(entity,entity_id,field,value,source,licence,retrieved_at)
                          VALUES('volume',?,'release_date',?,?,'open','2026-01-01')""",
                       (vid, val, src))
    db.commit()
    resolve(db)
    print(f"{'case':<20}{'expected':<20}{'got':<20}{'conf':>6}")
    print("-"*68)
    for i, (name, claims, expect) in enumerate(CASES):
        vid = f"v_test{i:08d}"
        r = db.execute("SELECT basis, confidence FROM resolution WHERE entity_id=?",
                       (vid,)).fetchone()
        got, conf = r if r else ("<none>", 0)
        ok = got == expect
        fails += not ok
        print(f"{name:<20}{expect:<20}{got:<20}{conf:>6.2f}  {'' if ok else '<-- FAIL'}")
    print("-"*68)
    # the VALUE that wins, where precedence and precision disagree
    for name, claims, want in VALUE_CASES:
        vid = "v_val" + name[:20]
        for src, val in claims.items():
            db.execute("""INSERT INTO claim(entity,entity_id,field,value,source,licence,retrieved_at)
                          VALUES('volume',?,'release_date',?,?,'open','2026-01-01')""", (vid, val, src))
    db.commit()
    resolve(db)
    for name, claims, want in VALUE_CASES:
        got = db.execute("SELECT value FROM resolution WHERE entity_id=?", ("v_val" + name[:20],)).fetchone()[0]
        ok = got == want
        fails += not ok
        print(f"{name:<40}{want:<14}{got:<14}  {'' if ok else '<-- FAIL'}")
    n = len(CASES) + len(VALUE_CASES)
    print(f"{n-fails}/{n} passed")
    return fails

if __name__ == "__main__":
    sys.exit(1 if run() else 0)
