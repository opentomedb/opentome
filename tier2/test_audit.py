"""Unit tests for tier2/audit.py. Run: python3 tier2/test_audit.py

A temp catalogue from schema/schema.sql; no build/, no network.
"""
import os, sqlite3, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import audit

FAILS = []


def eq(label, got, want):
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else f"  got={got!r} want={want!r}"))
    if not ok:
        FAILS.append(label)


def catalogue(works):
    """works: [(id, primary_title, ja_title)] -> an open connection. ja_title goes to work_title
    (language ja, kind official), the way stage 1's classes land; None writes no row."""
    path = os.path.join(tempfile.mkdtemp(prefix="opentome-audit-"), "c.db")
    db = sqlite3.connect(path)
    db.executescript(open(os.path.join(ROOT, "schema", "schema.sql"), encoding="utf8").read())
    for wid, title, ja in works:
        db.execute("INSERT INTO work (id, primary_title, created_at, updated_at) VALUES (?,?,'t','t')", (wid, title))
        if ja:
            db.execute("INSERT INTO work_title (work_id, language, title, kind) VALUES (?,'ja',?,'official')", (wid, ja))
    db.commit()
    return db


# Two works with one display title and two Japanese titles are two works (Kei Toume's 黒鉄 and
# Haruto Ikezawa's クロガネ, both "Kurogane", 2026-11-24): not a duplicate ingest.
db = catalogue([("w_1", "Kurogane", "黒鉄"), ("w_2", "Kurogane", "クロガネ")])
eq("same title, different Japanese titles: not a duplicate", audit.duplicate_titles(db), [])

# The same Japanese title twice is the duplicate ingest the check exists for.
db = catalogue([("w_1", "Naruto", "NARUTO -ナルト-"), ("w_2", "Naruto", "NARUTO -ナルト-")])
eq("same title, same Japanese title: a duplicate", audit.duplicate_titles(db), ["naruto"])

# No Japanese title on either side: nothing says they differ, so still a duplicate.
db = catalogue([("w_1", "Doubt", None), ("w_2", "Doubt", None)])
eq("same title, no Japanese titles: a duplicate", audit.duplicate_titles(db), ["doubt"])

# One side has a Japanese title, the other none: nothing says they differ either.
db = catalogue([("w_1", "Doubt", "ダウト"), ("w_2", "Doubt", None)])
eq("same title, Japanese title on one side only: a duplicate", audit.duplicate_titles(db), ["doubt"])

# A work's native_title stands in when it has no Japanese work_title row (the KR/CN works).
db = catalogue([("w_1", "Noblesse", None), ("w_2", "Noblesse", None)])
db.execute("UPDATE work SET native_title='노블레스' WHERE id='w_1'")
db.execute("UPDATE work SET native_title='ノブレス' WHERE id='w_2'")
eq("different native titles, no Japanese rows: not a duplicate", audit.duplicate_titles(db), [])

if FAILS:
    print("FAILED:", FAILS)
    sys.exit(1)
print("all audit checks passed")
