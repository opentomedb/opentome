"""Unit tests for the KR/CN round (docs/krcn-design.md). Run: python3 tier0/test_krcn.py

No network: synthetic records transcribed from the 2026-09-27 spike's cached responses (each
cites its spike cache file under ~/Claude/scratch/mangarr-session/krcn/cache/), in-memory
catalogues built from schema/schema.sql, and *_OFFLINE=1 as a backstop.
"""
import datetime, json, os, re, sqlite3, sys, tempfile, unicodedata

for _src in ("DNB", "LOC", "BNF"):
    os.environ[_src + "_OFFLINE"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _d in (HERE, os.path.join(ROOT, "schema"), os.path.join(ROOT, "tier1"), os.path.join(ROOT, "tier2"),
           os.path.join(ROOT, "export")):
    sys.path.insert(0, _d)

FAILS = []
Y = datetime.date.today().year


def eq(label, got, want):
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else f"  got={got!r} want={want!r}"))
    if not ok:
        FAILS.append(label)


def schema_db():
    db = sqlite3.connect(":memory:")
    db.executescript(open(os.path.join(ROOT, "schema", "schema.sql"), encoding="utf8").read())
    return db


# ---- Task 1: replay harness --------------------------------------------------------------------
import krcn_replay as R

base = {"dnb:1": ["high", "linked", 1, "rl_a", "w_1"], "dnb:2": ["none", "unlinked", 0, "rl_b", None]}
eq("identical snapshots: no change", R.diff_snapshots(base, dict(base)), {"added": [], "removed": [], "changed": []})
new = {"dnb:1": ["high", "out_of_scope", 0, "rl_a", "w_1"], "dnb:3": ["none", "unlinked", 0, "rl_c", None]}
d = R.diff_snapshots(base, new)
eq("a role and an exported flag changed", d["changed"],
   [("dnb:1", "role", "linked", "out_of_scope"), ("dnb:1", "exported", 1, 0)])
eq("a key added and a key removed", (d["added"], d["removed"]), (["dnb:3"], ["dnb:2"]))
eq("has_hangul: syllables", R.has_hangul("나 혼자만 레벨업"), True)
eq("has_hangul: compatibility jamo", R.has_hangul("ㅋㅋ"), True)
eq("has_hangul: kana / Latin", R.has_hangul("ガンダム Übel Blatt"), False)
eq("fold_v1 is the pre-round fold (Hangul dropped)", R.fold_v1("나 혼자만 레벨업"), "")
eq("fold_v1 kana voicing dropped", R.fold_v1("ガンダム"), R.fold_v1("カンタム"))

# ==== summary ====
print()
if FAILS:
    print("%d FAILED: %s" % (len(FAILS), FAILS))
    sys.exit(1)
print("all krcn tests passed")
