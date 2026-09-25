#!/usr/bin/env python3
"""Unit tests for export/to_mangarr.py's pure functions -- no database, no network.
Run: python3 export/test_to_mangarr.py
"""
import os, sqlite3, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "tier2"))
sys.path.insert(0, os.path.join(ROOT, "schema"))
sys.path.insert(0, os.path.join(ROOT, "tier0"))
from to_mangarr import title_for_export, pick_origin, export
import corrections as corr

FAILS = []


def eq(label, got, want):
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else f"  got={got!r} want={want!r}"))
    if not ok:
        FAILS.append(label)


def run():
    # ---- title_for_export: redundancy (2026-09-23 follow-up) --------------
    # A LicensedTitle like "Mushoku Tensei: Jobless Reincarnation (Light Novel)
    # Vol. 14" survived the old redundancy check: the bracketed qualifier
    # between the name and the number wasn't in _REDUNDANT_SUFFIX's shape.
    NAME = "Mushoku Tensei: Jobless Reincarnation"
    TITLE = NAME + " (Light Novel) Vol. 14"
    eq("bracketed qualifier + 'Vol.' + number is now redundant",
       title_for_export(TITLE, NAME, True), None)
    eq("bracketed qualifier + bare number is now redundant",
       title_for_export(NAME + " (Light Novel) 14", NAME, True), None)
    eq("a real subtitle after the bracket still survives (not just digits)",
       title_for_export(NAME + " (Light Novel): A Real Subtitle", NAME, True),
       NAME + " (Light Novel): A Real Subtitle")

    # ---- regressions: unaffected by the widened suffix ---------------------
    eq("plain redundant name+number (pre-existing behaviour)",
       title_for_export("X 5", "X", True), None)
    eq("prefix lead-in still strips (a different regex, _PREFIX_LEAD_IN)",
       title_for_export("Sword Art Online 1: Aincrad", "Sword Art Online", True), "Aincrad")
    eq("a real subtitle with no bracket still survives",
       title_for_export("Sword Art Online: Aincrad", "Sword Art Online", True),
       "Sword Art Online: Aincrad")
    eq("trusted titles still round-trip verbatim, redundant shape or not",
       title_for_export(TITLE, NAME, True, trusted=True), TITLE)
    eq("markup is still refused regardless of trusted",
       title_for_export("{{x}}", NAME, True, trusted=True), None)
    eq("number-only is still refused regardless of trusted",
       title_for_export("14", NAME, True, trusted=True), None)

    # ---- pick_origin (2026-09-23 follow-up: lifted from a closure inside
    # export() to module level, so it's independently testable and a
    # corrections-driven medium override can be exercised without a database).
    # Denma's real dates (build/opentome.db, 2026-09-22): JP's main line shipped
    # 2008-10-14, KR's 2015-01-20 (a late collected edition of an ongoing web
    # serialization). Tagged plain 'manga' upstream, Denma has no medium hint, so
    # step 2 (earliest date) picks JP -- the accepted, documented defect
    # (HANDOFF.md 2026-09-21). A corrections/lines.json medium override that
    # retags Denma's lines 'manhwa' routes it through step 1 instead.
    DENMA_MARKETS = {"JP", "KR"}
    DENMA_DATES = {"JP": "2008-10-14", "KR": "2015-01-20"}
    eq("Denma (medium 'manga', no hint): JP wins on date -- the accepted defect",
       pick_origin("manga", DENMA_MARKETS, DENMA_DATES), "JP")
    eq("Denma retagged 'manhwa' (medium override applied): KR wins on the hint",
       pick_origin("manhwa", DENMA_MARKETS, DENMA_DATES), "KR")
    eq("manhwa hint wins even when the JP date is earlier",
       pick_origin("manhwa", {"JP", "KR"}, {"JP": "2000-01-01", "KR": "2015-01-20"}), "KR")
    eq("manhua hint prefers CN over TW", pick_origin("manhua", {"TW", "CN"}, {}), "CN")
    eq("no hint, no dates: falls back to the fixed JP>KR>CN>TW order",
       pick_origin("manga", {"TW", "KR"}, {}), "KR")
    eq("no candidate markets at all: None", pick_origin("manga", set(), {}), None)

    # ---- origin_line pin, end to end (2026-09-24, Roxy Gets Serious): two
    # same-work, same-medium JP lines -- a main line and a spin-off whose
    # line_name claim cannot exact-match an EN line's own name (mirrors the
    # real JP Roxy line's French cross-parsed name). Without a pin, an EN
    # line resolves to the JP MAIN line (the defect); with one, to the spin-off.
    pinned_rid, unpinned_rid, orig_of, gcd_of = fixture_origin_line_pin()
    eq("origin_line pin: resolves to the pinned JP spin-off",
       orig_of[pinned_rid], gcd_of["rl_jp_spinoff"])
    eq("origin_line pin: not the JP main line",
       orig_of[pinned_rid] == gcd_of["rl_jp_main"], False)
    eq("no pin: an EN line with no name match falls back to the JP main line (the defect, reproduced)",
       orig_of[unpinned_rid], gcd_of["rl_jp_main"])

    # ---- a redirected line keeps its consumer-facing integer (2026-09-24, DNB) --------
    # A DNB line whose source key changed (a parent record appeared) gets a new rl_ id and
    # an id_redirect row; the integer a Mangarr stored for the old id must follow it.
    sid, rtype, red, idmap = fixture_redirect_carry()
    eq("a redirected line carries the old line's integer id", sid, 424242)
    eq("release_date_type ships with a dated volume", rtype, "projected")
    eq("the artifact's id_redirect resolves the retired id (chained) to the line that exists",
       red.get("rl_older"), ("rl_new", "release_line", None))
    eq("a successor that already had an integer keeps it; the retired integer resolves through id_redirect",
       red.get("rl_twin"), ("rl_new", "release_line", 555555))
    eq("a retired integer stays reserved in id_map", idmap.get("rl_twin"), (555555, "retired"))

    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        sys.exit(1)
    print("to_mangarr ok")


def fixture_redirect_carry():
    tmp = tempfile.mkdtemp(prefix="opentome-redirect-")
    src_path, out_path, carry = (os.path.join(tmp, n) for n in ("pipeline.db", "artifact.sqlite", "carry.sqlite"))
    db = sqlite3.connect(src_path)
    db.executescript(open(os.path.join(ROOT, "schema", "schema.sql"), encoding="utf8").read())
    db.execute("INSERT INTO work(id,primary_title,created_at,updated_at) VALUES('w_r','Redirect Work','x','x')")
    db.execute("""INSERT INTO release_line(id,work_id,medium,market,language,created_at,updated_at)
                 VALUES('rl_new','w_r','manga','DE','de','x','x')""")
    db.execute("""INSERT INTO volume(id,release_line_id,number,isbn13,release_date,release_date_precision,
                  release_date_type,created_at,updated_at)
                  VALUES('v_new1','rl_new','1','9783753935874','2026-11','month','projected','x','x')""")
    db.execute("INSERT INTO id_redirect VALUES('rl_old','rl_new','release_line','correction','x')")
    db.execute("INSERT INTO id_redirect VALUES('rl_older','rl_old','release_line','correction','x')")
    db.execute("INSERT INTO id_redirect VALUES('rl_twin','rl_new','release_line','duplicate_merge','x')")
    db.commit()
    c = sqlite3.connect(carry)
    c.execute("CREATE TABLE id_map (opentome_id TEXT PRIMARY KEY, int_id INTEGER UNIQUE NOT NULL, kind TEXT NOT NULL)")
    c.execute("INSERT INTO id_map VALUES('rl_old', 424242, 'release_line')")
    c.execute("INSERT INTO id_map VALUES('rl_twin', 555555, 'release_line')")
    c.commit()
    real_dir = corr.DIR
    corr.DIR = tempfile.mkdtemp(prefix="opentome-nocorr-")      # no corrections in play
    try:
        export(src_path, out_path, carry)
    finally:
        corr.DIR = real_dir
    out = sqlite3.connect(out_path)
    sid = out.execute("SELECT gcd_series_id FROM series WHERE tome_id='rl_new'").fetchone()[0]
    rtype = out.execute("SELECT release_date_type FROM volumes WHERE tome_id='v_new1'").fetchone()[0]
    red = {o: (n, e, oi) for o, n, e, oi in out.execute(
        "SELECT old_tome_id, new_tome_id, entity, old_series_id FROM id_redirect")}
    idmap = {o: (i, k) for o, i, k in out.execute("SELECT opentome_id, int_id, kind FROM id_map")}
    return sid, rtype, red, idmap


def fixture_origin_line_pin():
    """Build a tiny pipeline DB with two same-work, same-medium JP manga lines --
    a main line and a spin-off whose line_name claim does not match either new
    EN line's own name (exactly the shape of the real Mushoku Tensei JP Roxy
    line, whose line_name is the French string cross-parsed from the FR
    Wikipedia table) -- then run the real corrections.apply_line_corrections()
    and export() against it. Returns (pinned EN rid, unpinned EN rid,
    {tome_id: orig_series_id}, {tome_id: gcd_series_id})."""
    tmp = tempfile.mkdtemp(prefix="opentome-originline-")
    src_path = os.path.join(tmp, "pipeline.db")
    out_path = os.path.join(tmp, "artifact.sqlite")
    db = sqlite3.connect(src_path)
    db.executescript(open(os.path.join(ROOT, "schema", "schema.sql"), encoding="utf8").read())
    db.execute("INSERT INTO work(id,primary_title,created_at,updated_at) VALUES('w_t','Test Work','x','x')")
    db.execute("""INSERT INTO release_line(id,work_id,medium,market,language,created_at,updated_at)
                 VALUES('rl_jp_main','w_t','manga','JP','ja','x','x')""")
    db.execute("""INSERT INTO release_line(id,work_id,medium,market,language,created_at,updated_at)
                 VALUES('rl_jp_spinoff','w_t','manga','JP','ja','x','x')""")
    db.execute("""INSERT INTO claim(entity,entity_id,field,value,source,licence,retrieved_at)
                 VALUES('release_line','rl_jp_spinoff','line_name','Something Else Entirely',
                        'wikipedia','facts_only','x')""")
    for num, date in (("1", "2019-01-01"), ("2", "2019-06-01")):
        db.execute("""INSERT INTO volume(id,release_line_id,number,release_date,release_date_precision,
                                        created_at,updated_at) VALUES(?,?,?,?,'day','x','x')""",
                  ("v_jpmain%s" % num, "rl_jp_main", num, date))
    for num, date in (("1", "2020-01-01"), ("2", "2020-06-01")):
        db.execute("""INSERT INTO volume(id,release_line_id,number,release_date,release_date_precision,
                                        created_at,updated_at) VALUES(?,?,?,?,'day','x','x')""",
                  ("v_jpspin%s" % num, "rl_jp_spinoff", num, date))
    db.commit()

    PINNED = {"work": "w_t", "market": "EN", "medium": "manga", "name": "Test Work Spin-off",
              "publisher": "Example Press", "origin_line": "rl_jp_spinoff",
              "volumes": [{"number": "1", "isbn13": "978-1-64505-000-1", "release_date": "2020-10-06", "contains": [1]},
                          {"number": "2", "isbn13": "9798888779347", "release_date": "2021-02-01", "contains": [2]}],
              "source_url": "https://example.test/pin", "checked": "2026-09-24"}
    UNPINNED = {"work": "w_t", "market": "EN", "medium": "manga", "name": "Test Work Unrelated",
                "publisher": "Example Press",
                "volumes": [{"number": "1", "isbn13": "978-1-64505-100-1", "release_date": "2020-10-06", "contains": [1]}],
                "source_url": "https://example.test/unpinned", "checked": "2026-09-24"}
    corr.apply_line_corrections(db, entries=[PINNED, UNPINNED], verbose=False)
    db.commit(); db.close()

    # export() also applies corrections/aliases.json (load_aliases /
    # load_alias_removals, imported from this same module) against whatever
    # DB it's exporting -- the real repo's aliases target real lines this
    # fixture doesn't have. Point corr.DIR at an empty directory for the
    # export call only; load_aliases/load_alias_removals resolve `DIR` at
    # call time, so to_mangarr.py's already-imported references see it too.
    real_dir, corr.DIR = corr.DIR, tempfile.mkdtemp(prefix="opentome-empty-corrections-")
    try:
        export(src_path, out_path)
    finally:
        corr.DIR = real_dir
    out = sqlite3.connect(out_path)
    pinned_rid = corr._id("rl_", "w_t", "manga", "EN", "Test Work Spin-off")
    unpinned_rid = corr._id("rl_", "w_t", "manga", "EN", "Test Work Unrelated")
    orig_of = dict(out.execute("SELECT tome_id, orig_series_id FROM series"))
    gcd_of = dict(out.execute("SELECT tome_id, gcd_series_id FROM series"))
    out.close()
    return pinned_rid, unpinned_rid, orig_of, gcd_of


if __name__ == "__main__":
    run()
