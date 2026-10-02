#!/usr/bin/env python3
"""Round C merges (spec §3.2). Run: python3 tier0/test_round_c_merge.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import round_c_merge as m
FAILS = []
def eq(label, got, want):
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else f"  got={got!r} want={want!r}"))
    if not ok: FAILS.append(label)

def V(rng, isbn=True): return {n: ("978%010d" % n if isbn else None) for n in rng}
eq("extend: 31-35 after 1-30", m.verdict(V(range(31, 36)), V(range(1, 31))), "extend")
eq("duplicate: same numbers, same ISBNs", m.verdict(V(range(31, 36)), V(range(1, 36))), "duplicate")
eq("duplicate: candidate without ISBNs", m.verdict(V(range(1, 4), False), V(range(1, 10))), "duplicate")
eq("kept: same number, different ISBN", m.verdict({1: "9780000000099"}, V(range(1, 10))), "kept")
eq("kept: a gap below the target's top", m.verdict(V(range(5, 8)), {1: None, 2: None, 10: None}), "kept")
eq("kept: empty candidate", m.verdict({}, V(range(1, 4))), "kept")
eq("kept: non-int candidate number", m.verdict({"A": None}, V(range(1, 4))), "kept")
eq("duplicate: string numbers", m.verdict({"1": None}, {"1": "x"}), "duplicate")
def L(i, name, wt="Black Butler", arc=False, medium="manga", market="FR"):
    return {"id": i, "work_id": "w", "work_title": wt, "market": market, "medium": medium, "name": name, "arc_split": arc}
eq("T candidate", m.candidates([L("t", "Black Butler (Tomes 31 à aujourd'hui)"), L("b", "Black Butler")]), [("t", "b", "T")])
eq("W2 candidate", m.candidates([L("t", "Black Butler (Mangas)"), L("b", "Black Butler")]), [("t", "b", "W2")])
NOL = [L("t", "Kuro (Tomes 31 à aujourd'hui)"), L("b", "Kuro")]
ARCL = [L("t", "Black Butler (Tomes 31 à aujourd'hui)", arc=True), L("b", "Black Butler")]
eq("not the work's own line -> none", m.candidates(NOL), [])
eq("not the work's own line -> candidates_all lists it held", m.candidates_all(NOL), [("t", "b", "T", "not-own-line")])
eq("arc split out of the group -> none", m.candidates(ARCL), [])
eq("arc split out of the group -> candidates_all lists it held", m.candidates_all(ARCL), [("t", "b", "T", "arc")])
eq("candidates_all: a mergeable one has no reason",
   m.candidates_all([L("t", "Black Butler (Mangas)"), L("b", "Black Butler")]), [("t", "b", "W2", None)])
eq("other market -> none", m.candidates([L("t", "Black Butler (Tomes 31 à aujourd'hui)"), L("b", "Black Butler", market="JP")]), [])
eq("nested parens: last ' (' splits", m.candidates([L("t", "X (Y) (Mangas)", wt="X (Y)"), L("b", "X (Y)", wt="X (Y)")]), [("t", "b", "W2")])


# ---- the stage on a tiny catalogue (run(db, carry)) -------------------------------------------------
# helpers copied from tier0/test_carried_ids.py (never import a test file)
import json, sqlite3, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for d in (os.path.join(ROOT, "schema"), os.path.join(ROOT, "export"), os.path.join(ROOT, "tier2")):
    sys.path.insert(0, d)
import corrections as corr
from load import load, _id
os.environ.pop("OPENTOME_COLD_START", None)
TMP = tempfile.mkdtemp(prefix="opentome-roundc-")
corr.DIR = tempfile.mkdtemp(prefix="opentome-nocorr-")          # no corrections in play


def catalogue(name, works):
    """works: [(work_key, title, [(market, medium, line, [(number, isbn, date)])])] -> db path.
    A line tuple may carry a 5th item: the line it is an arc of (arc_of)."""
    path = os.path.join(TMP, name + ".db")
    db = sqlite3.connect(path)
    db.executescript(open(os.path.join(ROOT, "schema", "schema.sql"), encoding="utf8").read())
    for key, title, lines in works:
        recs = [dict({"volume": n, "line": ln[2], "medium": ln[1],
                      "markets": {"original": {"market": ln[0], "isbn13": isbn, "date": date,
                                               "date_precision": "day" if date else None}}},
                     **({"arc_of": ln[4]} if len(ln) > 4 else {}))
                for ln in lines for n, isbn, date in ln[3]]
        load(db, title, recs, work_key=key)
    db.commit()
    db.close()
    return path


def rl(key, market, line, medium="manga"):
    return _id("rl_", _id("w_", key), medium, market, line)


def vols(prefix, n, first=1, date=True):
    return [(str(i), "97840%08d" % (prefix * 1000 + i), "2010-01-%02d" % (i % 28 + 1) if date else None)
            for i in range(first, first + n)]


def carry_with(merges):
    path = tempfile.mktemp(suffix=".sqlite", dir=TMP)
    A = sqlite3.connect(path)
    A.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)")
    A.execute("INSERT INTO meta VALUES('round_c_merges', ?)", (json.dumps(merges),))
    A.commit()
    A.close()
    return path


def state(path, line):
    db = sqlite3.connect(path)
    have = db.execute("SELECT 1 FROM release_line WHERE id=?", (line,)).fetchone() is not None
    nums = sorted(int(n) for (n,) in db.execute("SELECT number FROM volume WHERE release_line_id=?", (line,)))
    meta = json.loads((db.execute("SELECT value FROM meta WHERE key='roundc:merged'").fetchone() or ["null"])[0])
    db.close()
    return have, nums, meta


BB = "fr:Black Butler"
TAIL = "Black Butler (Tomes 31 à aujourd'hui)"
main, tail = rl(BB, "FR", "Black Butler"), rl(BB, "FR", TAIL)

# extend: 1-30 + a tail 31-35
p = catalogue("extend", [(BB, "Black Butler", [("FR", "manga", "Black Butler", vols(1, 30)),
                                                ("FR", "manga", TAIL, vols(1, 5, 31))])])
m.run(p)
have, nums, meta = state(p, tail)
eq("extend: the tail line is gone", have, False)
eq("extend: the main line holds 35 numbers", state(p, main)[1], list(range(1, 36)))
eq("extend: meta lists the merge", meta, [[tail, main, "T", "extend", 5, 0, "rule"]])

# duplicate: the tail repeats 31-35 with the main line's ISBNs
p = catalogue("dup", [(BB, "Black Butler", [("FR", "manga", "Black Butler", vols(1, 35)),
                                             ("FR", "manga", TAIL, vols(1, 5, 31))])])
m.run(p)
eq("duplicate: tail gone, main keeps 35, meta records 0 moved 5 dropped",
   (state(p, tail)[0], state(p, main)[1], state(p, tail)[2]),
   (False, list(range(1, 36)), [[tail, main, "T", "duplicate", 0, 5, "rule"]]))

# kept: a W2 line whose vol 1 has another ISBN
W2 = "Black Butler (Mangas)"
w2 = rl(BB, "FR", W2)
p = catalogue("kept", [(BB, "Black Butler", [("FR", "manga", "Black Butler", vols(1, 10)),
                                              ("FR", "manga", W2, vols(2, 3))])])
m.run(p)
eq("kept: the W2 line stays with its volumes, meta lists it 0/0",
   state(p, w2), (True, [1, 2, 3], [[w2, main, "W2", "kept", 0, 0, "rule", "verdict"]]))

# arc: an arc was split out of the tail's rows (release_line.parent_id = the tail) -> not a candidate
ARC = "Black Butler (Arc du cirque)"
p = catalogue("arc", [(BB, "Black Butler", [("FR", "manga", "Black Butler", vols(1, 30)),
                                             ("FR", "manga", TAIL, vols(1, 5, 31)),
                                             ("FR", "manga", ARC, vols(3, 2), TAIL)])])
m.run(p)
eq("arc: the tail stays (an arc came out of it), listed kept/arc", state(p, tail),
   (True, list(range(31, 36)), [[tail, main, "T", "kept", 0, 0, "rule", "arc"]]))

# re-apply 1: the carry recorded the merge; this build's tail is renamed and still a candidate
TAIL2 = "Black Butler (Volumes 31 à aujourd'hui)"
tail2 = rl(BB, "FR", TAIL2)
c1 = carry_with([[tail, main, "extend"]])
p = catalogue("renamed", [(BB, "Black Butler", [("FR", "manga", "Black Butler", vols(1, 30)),
                                                 ("FR", "manga", TAIL2, vols(1, 5, 31))])])
m.run(p, c1)
eq("re-apply: a renamed tail is still a candidate and merges by rule",
   (state(p, tail2)[0], state(p, main)[1], state(p, tail2)[2]),
   (False, list(range(1, 36)), [[tail2, main, "T", "extend", 5, 0, "rule"]]))

# re-apply 2: no rule matches any more (the work's title changed: the target is not the work's own
# line), but both ids exist -> the carry's record merges it
p = catalogue("carry", [(BB, "Kuroshitsuji", [("FR", "manga", "Black Butler", vols(1, 30)),
                                               ("FR", "manga", TAIL, vols(1, 5, 31))])])
m.run(p, c1)
eq("re-apply: no rule matches, the carry record merges by id",
   (state(p, tail)[0], state(p, main)[1], state(p, tail)[2]),
   (False, list(range(1, 36)), [[tail, main, "T", "extend", 5, 0, "carry"]]))

# carry-conflict (a): the carry recorded tail -> main, but this build splits an arc out of the tail
p = catalogue("conflict-arc", [(BB, "Black Butler", [("FR", "manga", "Black Butler", vols(1, 30)),
                                                      ("FR", "manga", TAIL, vols(1, 5, 31)),
                                                      ("FR", "manga", ARC, vols(3, 2), TAIL)])])
m.run(p, c1)
D = sqlite3.connect(p)
eq("carry-conflict (arc): the tail stays, the arc still hangs under it, listed carry-conflict/arc",
   (state(p, tail), D.execute("SELECT parent_id FROM release_line WHERE id=?", (rl(BB, "FR", ARC),)).fetchone()[0]),
   ((True, list(range(31, 36)), [[tail, main, "T", "carry-conflict", 0, 0, "carry", "arc"]]), tail))
D.close()

# carry-conflict (b): main grew to 1-32; the tail's 31-32 carry other ISBNs -> no merge, nothing dropped
p = catalogue("conflict-isbn", [(BB, "Kuroshitsuji", [("FR", "manga", "Black Butler", vols(1, 32)),
                                                       ("FR", "manga", TAIL, vols(5, 5, 31))])])
m.run(p, c1)
D = sqlite3.connect(p)
eq("carry-conflict (verdict): the tail keeps 31-35, main 1-32, 37 volumes in all, listed carry-conflict",
   (state(p, tail), state(p, main)[1], D.execute("SELECT COUNT(*) FROM volume").fetchone()[0]),
   ((True, list(range(31, 36)), [[tail, main, "T", "carry-conflict", 0, 0, "carry", "verdict:kept"]]),
    list(range(1, 33)), 37))
D.close()

# re-apply 3: a carry record whose target is gone does nothing
p = catalogue("gone", [(BB, "Kuroshitsuji", [("FR", "manga", TAIL, vols(1, 5, 31))])])
m.run(p, carry_with([[tail, main, "extend"]]))
eq("re-apply: a record whose target is absent is skipped", state(p, tail), (True, list(range(31, 36)), []))

# zero-padded numbers: counted and printed, never fatal
import contextlib, io
p = catalogue("padded", [(BB, "Black Butler", [("FR", "manga", "Black Butler", [("01", None, None), ("2", None, None)])])])
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    m.run(p)
eq("padded: a zero-padded number is reported", "1 line(s) with zero-padded volume numbers" in buf.getvalue(), True)

# the export writes the applied merges (not the kept ones) as artifact meta round_c_merges
from to_mangarr import export
p = catalogue("export", [(BB, "Black Butler", [("FR", "manga", "Black Butler", vols(1, 30)),
                                                ("FR", "manga", TAIL, vols(1, 5, 31)),
                                                ("FR", "manga", W2, [("1", "9784099999999", None)])])])
m.run(p)
art = p.replace(".db", ".sqlite")
export(p, art, None)
A = sqlite3.connect(art)
eq("export: meta round_c_merges lists applied merges only",
   json.loads((A.execute("SELECT value FROM meta WHERE key='round_c_merges'").fetchone() or ["null"])[0]),
   [[tail, main, "extend", "T"]])
A.close()

# a carry-conflict ships the candidate again on purpose: the export lists it in meta round_c_conflicts
p = catalogue("export-conflict", [(BB, "Kuroshitsuji", [("FR", "manga", "Black Butler", vols(1, 32)),
                                                         ("FR", "manga", TAIL, vols(5, 5, 31))])])
m.run(p, c1)
art = p.replace(".db", ".sqlite")
export(p, art, None)
A = sqlite3.connect(art)
meta = dict(A.execute("SELECT key, value FROM meta"))
eq("export: meta round_c_conflicts lists the refused carried merge, round_c_merges stays absent",
   (json.loads(meta.get("round_c_conflicts", "null")), "round_c_merges" in meta),
   ([[tail, main, "verdict:kept"]], False))
A.close()
print("FAILED: %d" % len(FAILS) if FAILS else "all passed"); sys.exit(1 if FAILS else 0)
