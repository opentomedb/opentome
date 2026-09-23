#!/usr/bin/env python3
"""Unit tests for export/to_mangarr.py's pure functions -- no database, no network.
Run: python3 export/test_to_mangarr.py
"""
import os, shutil, sqlite3, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from to_mangarr import title_for_export, pick_origin, export

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAILS = []


def eq(label, got, want):
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else f"  got={got!r} want={want!r}"))
    if not ok:
        FAILS.append(label)


def _build_fixture_db(path):
    """A minimal real pipeline DB (schema/schema.sql), just enough for export()
    to run end to end: one work, its 'Aincrad' Wikipedia-redirect alias (a
    work_title row, kind='alias' -- what tier0/main_titles.py's redirects()
    writes), a main EN light_novel line whose volume 1 is titled 'Aincrad'
    (the collision), and an UNRELATED same-work EN manga line whose own
    volume does NOT collide (the regression: it must keep the alias)."""
    db = sqlite3.connect(path)
    db.executescript(open(os.path.join(ROOT, "schema", "schema.sql"), encoding="utf8").read())
    NOW = "2026-09-23T00:00:00+00:00"
    db.execute("INSERT INTO work(id,primary_title,created_at,updated_at) VALUES(?,?,?,?)",
              ("w_alias_test", "Sword Art Online (Test)", NOW, NOW))
    db.execute("INSERT INTO work_title(work_id,language,title,kind) VALUES(?,?,?,?)",
              ("w_alias_test", "en", "Aincrad", "alias"))
    db.execute("""INSERT INTO release_line(id,work_id,medium,market,language,created_at,updated_at)
                  VALUES(?,?,?,?,?,?,?)""",
              ("rl_ln_main", "w_alias_test", "light_novel", "EN", "en", NOW, NOW))
    db.execute("""INSERT INTO volume(id,release_line_id,number,title,created_at,updated_at)
                  VALUES(?,?,?,?,?,?)""",
              ("v_ln_1", "rl_ln_main", "1", "Aincrad", NOW, NOW))
    db.execute("""INSERT INTO release_line(id,work_id,medium,market,language,created_at,updated_at)
                  VALUES(?,?,?,?,?,?,?)""",
              ("rl_manga_other", "w_alias_test", "manga", "EN", "en", NOW, NOW))
    db.execute("""INSERT INTO volume(id,release_line_id,number,title,created_at,updated_at)
                  VALUES(?,?,?,?,?,?)""",
              ("v_manga_1", "rl_manga_other", "1", "First Blood", NOW, NOW))
    db.commit()
    db.close()


def fixture_alias_hygiene():
    tmp = tempfile.mkdtemp(prefix="opentome-alias-hygiene-")
    try:
        src = os.path.join(tmp, "opentome.db")
        out = os.path.join(tmp, "manga-metadata.sqlite")
        _build_fixture_db(src)
        r = export(src, out)
        eq("alias hygiene: dropped exactly the one colliding alias", r["aliases_dropped"], 1)
        odb = sqlite3.connect(out)
        ln_aliases = {a.lower() for (a,) in odb.execute(
            """SELECT alias FROM series_alias sa JOIN series s USING(gcd_series_id)
               WHERE s.tome_id='rl_ln_main'""")}
        eq("alias hygiene: 'Aincrad' dropped from the colliding (main) line",
           "aincrad" in ln_aliases, False)
        eq("alias hygiene: the line's own name is kept regardless",
           "sword art online (test)" in ln_aliases, True)
        manga_aliases = {a.lower() for (a,) in odb.execute(
            """SELECT alias FROM series_alias sa JOIN series s USING(gcd_series_id)
               WHERE s.tome_id='rl_manga_other'""")}
        eq("alias hygiene: an unrelated same-work line with no collision of "
           "its own still gets the alias", "aincrad" in manga_aliases, True)
        odb.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


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

    # ---- alias hygiene (2026-09-23 follow-up) ------------------------------
    # A work-level alias (a Wikipedia redirect: tier0/main_titles.py's
    # redirects(), stored as work_title(kind='alias')) can equal one of the
    # work's own volume titles. 'Aincrad' is both a Sword Art Online redirect
    # (attached to every MAIN line of the work) and the title of SAO's English
    # light-novel volume 1 -- so it stops distinguishing anything. Exercised
    # through a real export() run (not a unit-level fake) because the
    # collision set (a line's own volume titles + its origin's) only exists
    # in the OUTPUT tables, after every line has been written.
    fixture_alias_hygiene()

    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        sys.exit(1)
    print("to_mangarr ok")


if __name__ == "__main__":
    run()
