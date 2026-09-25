"""Unit tests for tier0/carried_ids.py (stage 7b redirects). Run: python3 tier0/test_carried_ids.py

No network, no build/: every catalogue is built from schema/schema.sql with schema/load.py (the
loader the corpus stage uses, so ids hash exactly as in a real build), exported with
export/to_mangarr.py into a carried artifact, rebuilt with the change under test, redirected,
exported again against the carry, and checked with export/test_artifact.py's run_ids.
"""
import os, sqlite3, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for d in (HERE, os.path.join(ROOT, "schema"), os.path.join(ROOT, "export"), os.path.join(ROOT, "tier2")):
    sys.path.insert(0, d)
import carried_ids as K
import corrections as corr
from load import load, _id
from to_mangarr import export
import test_artifact as TA

FAILS = []
TMP = tempfile.mkdtemp(prefix="opentome-carried-")
corr.DIR = tempfile.mkdtemp(prefix="opentome-nocorr-")          # no corrections in play


def eq(label, got, want):
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else f"  got={got!r} want={want!r}"))
    if not ok:
        FAILS.append(label)


def catalogue(name, works):
    """works: [(work_key, title, [(market, medium, line, [(number, isbn, date)])])] -> db path."""
    path = os.path.join(TMP, name + ".db")
    db = sqlite3.connect(path)
    db.executescript(open(os.path.join(ROOT, "schema", "schema.sql"), encoding="utf8").read())
    for key, title, lines in works:
        recs = [{"volume": n, "line": line, "medium": med,
                 "markets": {"original": {"market": market, "isbn13": isbn, "date": date,
                                          "date_precision": "day" if date else None}}}
                for market, med, line, vols in lines for n, isbn, date in vols]
        load(db, title, recs, work_key=key)
    db.commit()
    db.close()
    return path


def artifact(db_path, carry=None):
    out = db_path.replace(".db", ".sqlite")
    export(db_path, out, carry)
    return out


def rl(key, market, line, medium="manga"):
    return _id("rl_", _id("w_", key), medium, market, line)


def vols(prefix, n, first=1, date=True):
    return [(str(i), "97840%08d" % (prefix * 1000 + i), "2010-01-%02d" % i if date else None)
            for i in range(first, first + n)]


def ids_ok(art, carry):
    TA.FAILS[:] = []
    TA.run_ids(art, carry)
    return list(TA.FAILS)


# ---- a re-key: the line name that feeds the id changed (the Kindaichi shape) ---------------------
K1 = "fr:Liste des chapitres des Enquêtes (1re partie)"
before = catalogue("rekey1", [(K1, "s Enquêtes (1re partie)", [
    ("JP", "manga", "s Enquêtes (1re partie) (FILE)", vols(1, 3)),
    ("FR", "manga", "s Enquêtes (1re partie) (FILE)", vols(2, 2))])])
carry = artifact(before)
after = catalogue("rekey2", [(K1, "Les Enquêtes (1re partie)", [
    ("JP", "manga", "Les Enquêtes (1re partie) (FILE)", vols(1, 3)),
    ("FR", "manga", "Les Enquêtes (1re partie) (FILE)", vols(2, 2))])])
db = sqlite3.connect(after)
rep = K.redirects(db, carry, excluded=set())
old_jp, new_jp = rl(K1, "JP", "s Enquêtes (1re partie) (FILE)"), rl(K1, "JP", "Les Enquêtes (1re partie) (FILE)")
eq("re-key: the old JP line redirects to the re-keyed one (correction)",
   db.execute("SELECT new_id, entity, reason FROM id_redirect WHERE old_id=?", (old_jp,)).fetchone(),
   (new_jp, "release_line", "correction"))
eq("re-key: every volume follows by number",
   db.execute("SELECT new_id FROM id_redirect WHERE old_id=?", (_id("v_", old_jp, "2"),)).fetchone(),
   (_id("v_", new_jp, "2"),))
eq("re-key: 2 lines + 5 volumes, no orphan, the work untouched",
   (dict(rep["rows"]), rep["orphans"]),
   ({("release_line", "correction"): 2, ("volume", "correction"): 5}, []))
art = artifact(after, carry)
A, C = sqlite3.connect(art), sqlite3.connect(carry)
old_int = C.execute("SELECT gcd_series_id FROM series WHERE tome_id=?", (old_jp,)).fetchone()[0]
eq("re-key: the re-keyed line keeps the integer a consumer stored",
   A.execute("SELECT gcd_series_id FROM series WHERE tome_id=?", (new_jp,)).fetchone()[0], old_int)
eq("re-key: the artifact's id_redirect carries the old line id",
   A.execute("SELECT new_tome_id, new_series_id FROM id_redirect WHERE old_tome_id=?", (old_jp,)).fetchone(),
   (new_jp, old_int))
eq("re-key: the carried-id gate passes", ids_ok(art, carry), [])
db.close()

# ---- a rerun redirects nothing new; the carried rows are re-read (chains collapse) -----------------
carry2 = art
again = catalogue("rekey3", [(K1, "Les Enquêtes (1re partie)", [
    ("JP", "manga", "Les Enquêtes (1re partie) (FILE)", vols(1, 3)),
    ("FR", "manga", "Les Enquêtes (1re partie) (FILE)", vols(2, 2))])])
db = sqlite3.connect(again)
rep = K.redirects(db, carry2, excluded=set())
eq("next build: nothing lost, nothing written, the 7 carried rows re-read",
   (sum(rep["rows"].values()), rep["carried_rows"], rep["orphans"]), (0, 7, []))
art3 = artifact(again, carry2)
eq("next build: the redirects are still in the artifact",
   sqlite3.connect(art3).execute("SELECT COUNT(*) FROM id_redirect").fetchone()[0], 7)
eq("next build: the gate passes against the re-keyed carry", ids_ok(art3, carry2), [])
lost_rows = os.path.join(TMP, "rekey3-lost.sqlite")
__import__("shutil").copy(art3, lost_rows)
L = sqlite3.connect(lost_rows)
L.execute("DELETE FROM id_redirect WHERE entity='volume'")
L.commit()
L.close()
eq("next build: an artifact that drops the carry's redirect rows fails the gate",
   ids_ok(lost_rows, carry2), ["carried ids (every market: works, lines, volumes) neither present nor redirected"])
db.close()

# chain: a line of the re-keyed carry is re-keyed again -> the oldest id reaches the newest line
chain = catalogue("rekey4", [(K1, "Les Enquêtes (1re partie)", [
    ("JP", "manga", "Les Enquêtes (1re partie) - FILE", vols(1, 3)),
    ("FR", "manga", "Les Enquêtes (1re partie) (FILE)", vols(2, 2))])])
db = sqlite3.connect(chain)
K.redirects(db, carry2, excluded=set())
art4 = artifact(chain, carry2)
eq("chain: the first id resolves to the newest line in the artifact",
   sqlite3.connect(art4).execute("SELECT new_tome_id FROM id_redirect WHERE old_tome_id=?", (old_jp,)).fetchone(),
   (rl(K1, "JP", "Les Enquêtes (1re partie) - FILE"),))
eq("chain: the gate passes", ids_ok(art4, carry2), [])
db.close()

# ---- a merged work: its lines re-key under the survivor; the work id is redirected ---------------
WA, WB = "en:Drops of God", "fr:Liste des chapitres des Gouttes de Dieu"
jp = vols(3, 4)
before = catalogue("merge1", [
    (WA, "Drops of God", [("JP", "manga", "Drops of God", jp), ("EN", "manga", "Drops of God", vols(4, 4))]),
    (WB, "s Gouttes de Dieu", [("JP", "manga", "Les Gouttes de Dieu", jp),
                               ("FR", "manga", "Les Gouttes de Dieu", vols(5, 4))])])
carry = artifact(before)
after = catalogue("merge2", [
    (WA, "Drops of God", [("JP", "manga", "Drops of God", jp), ("EN", "manga", "Drops of God", vols(4, 4))]),
    (WA, "Drops of God", [("JP", "manga", "Drops of God (Les Gouttes de Dieu)", jp),
                          ("FR", "manga", "Drops of God (Les Gouttes de Dieu)", vols(5, 4))])])
db = sqlite3.connect(after)
rep = K.redirects(db, carry, excluded=set())
eq("merged work: the absorbed work redirects to the survivor (duplicate_merge)",
   db.execute("SELECT new_id, reason FROM id_redirect WHERE old_id=?", (_id("w_", WB),)).fetchone(),
   (_id("w_", WA), "duplicate_merge"))
eq("merged work: the JP line goes to the re-keyed copy when one exists (a new line first)",
   db.execute("SELECT new_id FROM id_redirect WHERE old_id=?", (rl(WB, "JP", "Les Gouttes de Dieu"),)).fetchone(),
   (rl(WA, "JP", "Drops of God (Les Gouttes de Dieu)"),))
art = artifact(after, carry)
eq("merged work: the work redirect reaches the artifact (works count as present)",
   sqlite3.connect(art).execute("SELECT new_tome_id, entity FROM id_redirect WHERE old_tome_id=?",
                                (_id("w_", WB),)).fetchone(), (_id("w_", WA), "work"))
eq("merged work: the gate passes", ids_ok(art, carry), [])
db.close()

# ---- shared ISBNs: the successor is looked for in the line's own work first ----------------------
WK, WO = "en:Kindaichi", "fr:Liste des chapitres des Enquêtes (2e partie)"
shared = vols(6, 3)
before = catalogue("shared1", [(WK, "Kindaichi", [("JP", "manga", "Kindaichi R", shared)]),
                               (WO, "s Enquêtes (2e partie)", [("JP", "manga", "s Enquêtes (2e partie) (R)", shared)])])
carry = artifact(before)
after = catalogue("shared2", [(WK, "Kindaichi", [("JP", "manga", "Kindaichi R", shared)]),
                              (WO, "Les Enquêtes (2e partie)", [("JP", "manga", "Les Enquêtes (2e partie) (R)", shared)])])
db = sqlite3.connect(after)
K.redirects(db, carry, excluded=set())
eq("shared ISBNs: the re-keyed line of the same work wins over another work's line",
   db.execute("SELECT new_id FROM id_redirect WHERE old_id=?", (rl(WO, "JP", "s Enquêtes (2e partie) (R)"),)).fetchone(),
   (rl(WO, "JP", "Les Enquêtes (2e partie) (R)"),))
db.close()

# ---- no ISBNs: a line follows its dated volumes; a vanished volume retires to its line --------------
WN = "en:Undated"
before = catalogue("sig1", [(WN, "Undated", [("JP", "manga", "Undated (Old name)",
                                               [("1", None, "2001-01-01"), ("2", None, "2001-02-01"), ("3", None, "2001-03-01")])])])
carry = artifact(before)
after = catalogue("sig2", [(WN, "Undated", [("JP", "manga", "Undated (New name)",
                                              [("1", None, "2001-01-01"), ("2", None, "2001-02-01")])])])
db = sqlite3.connect(after)
rep = K.redirects(db, carry, excluded=set())
new_line = rl(WN, "JP", "Undated (New name)")
eq("no ISBNs: the line follows its dated volumes",
   db.execute("SELECT new_id, reason FROM id_redirect WHERE old_id=?", (rl(WN, "JP", "Undated (Old name)"),)).fetchone(),
   (new_line, "correction"))
eq("a volume number that is gone retires to the successor line",
   db.execute("SELECT new_id, reason FROM id_redirect WHERE old_id=?",
              (_id("v_", rl(WN, "JP", "Undated (Old name)"), "3"),)).fetchone(), (new_line, "retired"))
art = artifact(after, carry)
eq("no ISBNs: the gate passes (one retirement is within the cap)", ids_ok(art, carry), [])
db.close()

# a line with no evidence at all retires to its work's main line of the market
before = catalogue("ret1", [(WN, "Undated", [("JP", "manga", "Undated", vols(7, 3)),
                                             ("JP", "manga", "Undated (Arc)", [("1", None, None), ("2", None, None)])])])
carry = artifact(before)
after = catalogue("ret2", [(WN, "Undated", [("JP", "manga", "Undated", vols(7, 3))])])
db = sqlite3.connect(after)
K.redirects(db, carry, excluded=set())
eq("no successor line: retired to the work's main line of that market",
   db.execute("SELECT new_id, reason FROM id_redirect WHERE old_id=?", (rl(WN, "JP", "Undated (Arc)"),)).fetchone(),
   (rl(WN, "JP", "Undated"), "retired"))
db.close()

# ---- an excluded work is retired on purpose; any other vanished work is an orphan ----------------
WX, WG = "en:Excluded", "en:Gone"
before = catalogue("gone1", [(WN, "Undated", [("JP", "manga", "Undated", vols(8, 2))]),
                             (WX, "Excluded", [("EN", "manga", "Excluded", vols(9, 2))]),
                             (WG, "Gone", [("EN", "manga", "Gone", vols(10, 2))])])
carry = artifact(before)
after = catalogue("gone2", [(WN, "Undated", [("JP", "manga", "Undated", vols(8, 2))])])
db = sqlite3.connect(after)
rep = K.redirects(db, carry, excluded={_id("w_", WX)})
eq("excluded work: no rows, counted as retired on purpose", (rep["excluded"], sum(rep["rows"].values())), (3, 0))
eq("a work gone for no known reason: its work, line and volumes are orphans",
   sorted(rep["orphans"]), sorted([_id("w_", WG), rl(WG, "EN", "Gone"),
                                   _id("v_", rl(WG, "EN", "Gone"), "1"), _id("v_", rl(WG, "EN", "Gone"), "2")]))
db.close()

# ---- 4c: an absorbed work's duplicate lines merge into the survivor's published line --------------
def gouttes(name, merged):
    """WA 'Drops of God' (JP + EN, plus a pre-existing same-edition JP pair sharing 3 of 4 ISBNs with
    the main line, 2 of 4 with the French article's); WB the French
    article (JP + FR, FR volume 1 an omnibus pointing at its JP line, a JP arc under it). JP vol 3
    carries a different ISBN on each side (the English article's error); WB's JP line has a vol 5
    WA's lacks. merged: the French article loads into WA, as a fixed work_title makes it."""
    path = os.path.join(TMP, name + ".db")
    db = sqlite3.connect(path)
    db.executescript(open(os.path.join(ROOT, "schema", "schema.sql"), encoding="utf8").read())
    jp = [(str(i), "9784063724%03d" % i, "2005-0%d-2%d" % (i, i)) for i in range(1, 5)]
    wa = [{"volume": n, "line": "Drops of God", "medium": "manga",
           "markets": {"original": {"market": "JP", "isbn13": i if n != "3" else "9784063724002",
                                    "date": d, "date_precision": "day"}}} for n, i, d in jp]
    wa += [{"volume": n, "line": "Drops of God (Tankōbon)", "medium": "manga",
            "markets": {"original": {"market": "JP", "isbn13": {"3": "9784063724002", "4": "9784063724104"}.get(n, i),
                                     "date": d, "date_precision": "day"}}} for n, i, d in jp]
    wa += [{"volume": str(n), "line": "Drops of God", "medium": "manga",
            "markets": {"original": {"market": "EN", "isbn13": "978197%07d" % n, "date": "2019-01-0%d" % n,
                                     "date_precision": "day"}}} for n in (1, 2)]
    load(db, "Drops of God", wa, work_key=WA)
    line = "Drops of God (Les Gouttes de Dieu)" if merged else "Les Gouttes de Dieu"
    wb = [{"volume": n, "line": line, "medium": "manga",
           "markets": {"original": {"market": "JP", "isbn13": i, "date": d, "date_precision": "day"}}}
          for n, i, d in jp + [("5", "9784063724005", "2005-09-25")]]
    wb[0]["markets"]["licensed"] = {"market": "FR", "number": "1", "isbn13": "9782352940001",
                                    "date": "2008-01-01", "date_precision": "day", "contains": [1, 2]}
    wb += [{"volume": "1", "line": line + " (Arc)", "arc_of": line, "medium": "manga",
            "markets": {"original": {"market": "JP", "isbn13": "9784063729999", "date": "2012-01-01",
                                     "date_precision": "day"}}}]
    load(db, "Drops of God" if merged else "s Gouttes de Dieu", wb, work_key=WA if merged else WB)
    db.commit()
    db.close()
    return path


def dangling(db):
    rl = "(SELECT id FROM release_line)"
    v = "(SELECT id FROM volume)"
    return db.execute(f"""SELECT
        (SELECT COUNT(*) FROM volume WHERE release_line_id NOT IN {rl}) +
        (SELECT COUNT(*) FROM composition WHERE volume_id NOT IN {v}) +
        (SELECT COUNT(*) FROM composition WHERE ref_line_id IS NOT NULL AND ref_line_id NOT IN {rl}) +
        (SELECT COUNT(*) FROM release_line WHERE parent_id IS NOT NULL AND parent_id NOT IN {rl}) +
        (SELECT COUNT(*) FROM claim WHERE entity='release_line' AND entity_id NOT IN {rl}) +
        (SELECT COUNT(*) FROM claim WHERE entity='volume' AND entity_id NOT IN {v})""").fetchone()[0]


S_JP, S_TK = rl(WA, "JP", "Drops of God"), rl(WA, "JP", "Drops of God (Tankōbon)")
N_JP, OLD_JP = rl(WA, "JP", "Drops of God (Les Gouttes de Dieu)"), rl(WB, "JP", "Les Gouttes de Dieu")
carry = artifact(gouttes("g1", merged=False))
path = gouttes("g2", merged=True)
db = sqlite3.connect(path)
keep_rows = db.execute("SELECT * FROM volume WHERE release_line_id=? ORDER BY id", (S_JP,)).fetchall()
keep_claims = db.execute("""SELECT * FROM claim WHERE entity_id IN (SELECT id FROM volume WHERE release_line_id=?)
                            ORDER BY entity_id, field""", (S_JP,)).fetchall()
done = K.merge_absorbed(db, carry)
eq("merge: the re-keyed JP line folds into the survivor's published JP line (4 dropped, vol 5 moved)",
   done, [(_id("w_", WB), _id("w_", WA), N_JP, S_JP, 1, 4)])
eq("merge: the published line's own volumes are untouched",
   db.execute("SELECT * FROM volume WHERE release_line_id=? AND number<>'5' ORDER BY id", (S_JP,)).fetchall(), keep_rows)
eq("merge: ... and so are their claims",
   db.execute("""SELECT * FROM claim WHERE entity_id IN (SELECT id FROM volume WHERE release_line_id=? AND number<>'5')
                 ORDER BY entity_id, field""", (S_JP,)).fetchall(), keep_claims)
eq("merge: the volume it lacked moves over, re-keyed by number, with its claims",
   db.execute("SELECT COUNT(*) FROM claim WHERE entity_id=?", (_id("v_", S_JP, "5"),)).fetchone()[0], 2)
eq("merge: the omnibus composition and the arc's parent now point at the survivor",
   (db.execute("SELECT DISTINCT ref_line_id FROM composition WHERE ref_line_id IS NOT NULL").fetchall(),
    db.execute("SELECT parent_id FROM release_line WHERE parent_id IS NOT NULL").fetchall()), ([(S_JP,)], [(S_JP,)]))
eq("merge: no reference to the merged line or its volumes is left", dangling(db), 0)
N_FR = rl(WA, "FR", "Drops of God (Les Gouttes de Dieu)")
eq("merge: the FR line that paired with the merged JP line by name is pinned to the survivor",
   db.execute("SELECT value, source FROM claim WHERE entity_id=? AND field='origin_line'", (N_FR,)).fetchone(),
   (S_JP, "opentome"))
eq("merge: the pre-existing same-edition pair (both published) is left alone",
   db.execute("SELECT COUNT(*) FROM release_line WHERE id=?", (S_TK,)).fetchone()[0], 1)
rep = K.redirects(db, carry, excluded=set())
eq("merge: the old JP line redirects to the survivor (duplicate_merge)",
   db.execute("SELECT new_id, reason FROM id_redirect WHERE old_id=?", (OLD_JP,)).fetchone(), (S_JP, "duplicate_merge"))
eq("merge: its vol 3 follows by NUMBER (its ISBN is on the survivor's vol 3 only on one side)",
   db.execute("SELECT new_id FROM id_redirect WHERE old_id=?", (_id("v_", OLD_JP, "3"),)).fetchone(),
   (_id("v_", S_JP, "3"),))
eq("merge: its vol 5 follows to the moved volume",
   db.execute("SELECT new_id FROM id_redirect WHERE old_id=?", (_id("v_", OLD_JP, "5"),)).fetchone(),
   (_id("v_", S_JP, "5"),))
eq("merge: no orphan", rep["orphans"], [])
db.close()
art = artifact(path, carry)
A, C = sqlite3.connect(art), sqlite3.connect(carry)
s_int = C.execute("SELECT gcd_series_id FROM series WHERE tome_id=?", (S_JP,)).fetchone()[0]
o_int = C.execute("SELECT gcd_series_id FROM series WHERE tome_id=?", (OLD_JP,)).fetchone()[0]
eq("merge: the survivor keeps its integer; the merged line's integer resolves to it",
   (A.execute("SELECT gcd_series_id FROM series WHERE tome_id=?", (S_JP,)).fetchone()[0],
    A.execute("SELECT old_series_id, new_series_id FROM id_redirect WHERE old_tome_id=?", (OLD_JP,)).fetchone()),
   (s_int, (o_int, s_int)))
eq("merge: ... so the FR line's origin is the survivor, not whatever the name fallback finds",
   A.execute("SELECT orig_series_id FROM series WHERE tome_id=?", (N_FR,)).fetchone()[0], s_int)
eq("merge: the gate passes", ids_ok(art, carry), [])

# the next build: the French article comes back as a duplicate every time; the carried work
# redirect is what says the merge was made, so it merges again and no new id ships
path3 = gouttes("g3", merged=True)
db = sqlite3.connect(path3)
eq("next build: merged again through the carried work redirect",
   [(d[2], d[3]) for d in K.merge_absorbed(db, art)], [(N_JP, S_JP)])
K.redirects(db, art, excluded=set())
db.close()
art3 = artifact(path3, art)
eq("next build: the same line ids as the build before",
   sorted(r[0] for r in sqlite3.connect(art3).execute("SELECT tome_id FROM series")),
   sorted(r[0] for r in A.execute("SELECT tome_id FROM series")))
eq("next build: the gate passes", ids_ok(art3, art), [])

# scope: a new line that repeats a published line of a work that absorbed nothing stays a line
path4 = gouttes("g4", merged=False)
db = sqlite3.connect(path4)
load(db, "Drops of God", [{"volume": "1", "line": "Drops of God (Reprint)", "medium": "manga",
                           "markets": {"original": {"market": "JP", "isbn13": "9784063724001",
                                                    "date": "2005-01-21", "date_precision": "day"}}}], work_key=WA)
eq("scope: no absorbed work, no merge", K.merge_absorbed(db, carry), [])
db.close()

# ---- the gate (export/test_artifact.py run_ids), every market ------------------------------------
def tiny(name, series, volumes, redirects=(), excluded=()):
    path = os.path.join(TMP, "gate-" + name + ".sqlite")
    A = sqlite3.connect(path)
    A.executescript("""CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE series (gcd_series_id INTEGER, tome_id TEXT, tome_work_id TEXT, language TEXT);
        CREATE TABLE volumes (gcd_series_id INTEGER, tome_id TEXT);
        CREATE TABLE id_redirect (old_tome_id TEXT, new_tome_id TEXT);""")
    A.executemany("INSERT INTO series VALUES(?,?,?,?)", series)
    A.executemany("INSERT INTO volumes VALUES(?,?)", volumes)
    A.executemany("INSERT INTO id_redirect VALUES(?,?)", redirects)
    A.execute("INSERT INTO meta VALUES('excluded_works', ?)", (__import__("json").dumps(list(excluded)),))
    A.commit()
    return path


gate_carry = tiny("gc", [(1, "rl_fr", "w_a", "fr"), (2, "rl_ja", "w_a", "ja"), (3, "rl_x", "w_x", "en")],
                  [(1, "v_fr%03d" % i) for i in range(150)] + [(2, "v_ja1",), (3, "v_x1")])
keep = [(1, "rl_fr", "w_a", "fr"), (2, "rl_ja", "w_a", "ja")]
eq("gate: a French line id gone without a redirect fails (not only German ids count now)",
   ids_ok(tiny("g1", keep[1:], [(2, "v_ja1")]), gate_carry)[:1],
   ["carried ids (every market: works, lines, volumes) neither present nor redirected"])
eq("gate: a work id gone without a redirect fails",
   "carried ids (every market: works, lines, volumes) neither present nor redirected" in ids_ok(
       tiny("g2", [(1, "rl_fr", "w_b", "fr"), (2, "rl_ja", "w_b", "ja")], [(1, "v_fr%03d" % i) for i in range(150)]
            + [(2, "v_ja1")], redirects=[("rl_x", "rl_ja"), ("v_x1", "rl_ja")]), gate_carry), True)
eq("gate: an excluded work takes its line and volumes with it",
   ids_ok(tiny("g3", keep, [(1, "v_fr%03d" % i) for i in range(150)] + [(2, "v_ja1")], excluded=["w_x"]),
          gate_carry), [])
eq("gate: 150 French volumes retired to their line in one build fails the every-market cap",
   ids_ok(tiny("g4", keep, [(2, "v_ja1")], redirects=[("v_fr%03d" % i, "rl_fr") for i in range(150)],
               excluded=["w_x"]), gate_carry),
   ["more than %d carried volumes retired in one build (every market)" % TA.MAX_RETIRED_VOLUMES])
eq("gate: ... while 150 volumes redirected to volumes (a re-key) do not count as retired",
   ids_ok(tiny("g5", [(1, "rl_fr2", "w_a", "fr"), (2, "rl_ja", "w_a", "ja")],
               [(1, "v_fr2%03d" % i) for i in range(150)] + [(2, "v_ja1")],
               redirects=[("rl_fr", "rl_fr2")] + [("v_fr%03d" % i, "v_fr2%03d" % i) for i in range(150)],
               excluded=["w_x"]), gate_carry), [])

eq("gate: a carried integer that is neither a series nor an old_series_id fails",
   "carried series integers neither a series nor an id_redirect.old_series_id" in ids_ok(
       tiny("g6", [(7, "rl_fr", "w_a", "fr"), (2, "rl_ja", "w_a", "ja")],
            [(7, "v_fr%03d" % i) for i in range(150)] + [(2, "v_ja1")], excluded=["w_x"]), gate_carry), True)

# ---- C1: a missing carry fails CI unless the cold start is deliberate -----------------------------
import subprocess
nocarry = catalogue("nocarry", [(WN, "Undated", [("JP", "manga", "Undated", vols(11, 2))])])
env0 = {k: v for k, v in os.environ.items() if k not in ("CI", "OPENTOME_CI", "OPENTOME_COLD_START")}
run = lambda stage, **env: subprocess.run(
    [sys.executable, os.path.join(HERE, "carried_ids.py"), stage, nocarry, os.path.join(TMP, "missing.sqlite")],
    env=dict(env0, **env), capture_output=True, text=True).returncode
for stage in ("merge", "redirect"):
    eq("no carry, OPENTOME_CI=1: %s fails" % stage, run(stage, OPENTOME_CI="1") != 0, True)
    eq("no carry, CI=true: %s fails" % stage, run(stage, CI="true") != 0, True)
    eq("no carry, OPENTOME_CI=1 + OPENTOME_COLD_START=1: %s passes" % stage,
       run(stage, OPENTOME_CI="1", OPENTOME_COLD_START="1"), 0)
    eq("no carry outside CI: %s warns and passes" % stage, run(stage), 0)
# rebuild_all.sh: the same check, before stage 0 (a copy in a scratch tree, so no real build/ is touched)
scratch = tempfile.mkdtemp(prefix="opentome-rebuild-")
os.makedirs(os.path.join(scratch, "tier0"))
__import__("shutil").copy(os.path.join(HERE, "rebuild_all.sh"), os.path.join(scratch, "tier0", "rebuild_all.sh"))
for d in ("tier2", "export"):
    os.makedirs(os.path.join(scratch, d))
rb = lambda **env: subprocess.run(["bash", os.path.join(scratch, "tier0", "rebuild_all.sh")], env=dict(env0, **env),
                                  capture_output=True, text=True)
r = rb(OPENTOME_CI="1")
eq("rebuild_all.sh in CI without a carry stops before stage 0", (r.returncode, "no carried artifact" in r.stderr,
                                                                  "== 0." in r.stdout), (1, True, False))
r = rb(OPENTOME_CI="1", OPENTOME_COLD_START="1")
eq("... with OPENTOME_COLD_START=1 it goes on (and stage 0 then fails here: no suites in the scratch copy)",
   ("cold id assignment" in r.stdout, "== 0." in r.stdout), (True, True))

# meta.carried_from: the export names its carry; publish.sh refuses an artifact without one
eq("the export records the carry it took ids from",
   sqlite3.connect(art).execute("SELECT value FROM meta WHERE key='carried_from'").fetchone()[0].startswith("opentome-"),
   True)
cold = os.path.join(TMP, "cold.sqlite")
export(nocarry, cold, None)
eq("an export without a carry has no carried_from",
   sqlite3.connect(cold).execute("SELECT value FROM meta WHERE key='carried_from'").fetchone(), None)
pub = tempfile.mkdtemp(prefix="opentome-pub-")
os.makedirs(os.path.join(pub, "export")); os.makedirs(os.path.join(pub, "build"))
__import__("shutil").copy(os.path.join(ROOT, "export", "publish.sh"), os.path.join(pub, "export", "publish.sh"))
P = lambda a, **env: subprocess.run(["bash", os.path.join(pub, "export", "publish.sh"), a], cwd=pub,
                                    env=dict(env0, **env), capture_output=True, text=True)
r = P(cold, PUBLISH="1")
eq("publish.sh refuses an artifact without carried_from", (r.returncode, "carried_from" in r.stderr), (1, True))
r = P(cold)
eq("... its dry run passes and says so", (r.returncode, "NO ID CARRY" in r.stderr), (0, True))
# a stub gh that refuses everything: the test can never reach a real release
fake = tempfile.mkdtemp(prefix="opentome-fakegh-")
with open(os.path.join(fake, "gh"), "w") as f:
    f.write("#!/bin/sh\necho FAKE-GH >&2\nexit 1\n")
os.chmod(os.path.join(fake, "gh"), 0o755)
r = P(cold, PUBLISH="1", OPENTOME_COLD_START="1", GH_TOKEN="x", PATH=fake + ":/usr/bin:/bin")
eq("... a deliberate cold start gets past the refusal (and stops at the stub gh)",
   ("refusing: this build did not carry ids" in r.stderr, "FAKE-GH" in r.stderr, r.returncode), (False, True, 1))

# ---- no carry: nothing to do ---------------------------------------------------------------------
db = sqlite3.connect(after)
eq("no carried artifact: an empty report", K.redirects(db, None, excluded=set())["orphans"], [])
db.close()

print()
if FAILS:
    print("%d FAILED: %s" % (len(FAILS), FAILS))
    sys.exit(1)
print("all carried-id tests passed")
