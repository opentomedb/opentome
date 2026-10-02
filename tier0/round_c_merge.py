"""Round C merges (spec §3.2): stage 4c2, after 4c, before 7b.

    python3 tier0/round_c_merge.py build/opentome.db [carry-artifact]

A continuation tail ("Black Butler (Tomes 31 à aujourd'hui)", kind T) or a duplicate section line
("X (Mangas)" beside "X", kind W2) of the work's own line folds into it with carried_ids.merge_line
when its volumes say so (verdict: extend / duplicate; anything else is kept and listed). Meta
`roundc:merged` records [cand, target, kind, verdict, moved, dropped] for every merge and every kept
candidate; the export writes the applied ones as artifact meta `round_c_merges`, and the next build
re-applies those by id (kind 'carry') when both ids exist -- a rename can stop the rule matching, the
decision stays. No redirect rows here: 7b redirects every retired line and volume.
"""
import json, os, re, sqlite3, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from release_lines import _OPEN_END, _ROUND_A
from carried_ids import merge_line

_W2 = "^(?:" + _ROUND_A + ")$"


def _num(n):
    try:
        return int(n)
    except (TypeError, ValueError):
        return str(n)


def _norm(vols):
    return {_num(n): isbn for n, isbn in vols.items()}


def verdict(cand_vols, target_vols):
    """'extend' | 'duplicate' | 'kept' for a candidate line against its target line."""
    if not cand_vols:
        return "kept"
    c, t = _norm(cand_vols), _norm(target_vols)
    common = set(c) & set(t)
    if not common and t:
        cn, tn = list(c), list(t)
        if all(isinstance(x, int) for x in cn + tn) and min(cn) > max(tn):
            return "extend"
    if not common:
        return "kept"
    if all(n in t and (c[n] is None or c[n] == t[n]) for n in c):
        return "duplicate"
    return "kept"


def candidates(lines):
    """[(cand_id, target_id, kind)] sorted; kind 'T' (open-end tail) or 'W2' (round-A word)."""
    by_name = {}
    for l in lines:
        by_name.setdefault((l["work_id"], l["market"], l["medium"], l["name"]), l["id"])
    out = []
    for l in lines:
        name = l["name"]
        if l.get("arc_split") or not name.endswith(")") or " (" not in name:
            continue
        target, q = name[:-1].rsplit(" (", 1)
        if target != l["work_title"]:
            continue
        if re.match(_OPEN_END, q, re.I):
            kind = "T"
        elif re.match(_W2, q, re.I):
            kind = "W2"
        else:
            continue
        tid = by_name.get((l["work_id"], l["market"], l["medium"], target))
        if tid is not None and tid != l["id"]:
            out.append((l["id"], tid, kind))
    return sorted(out)


# ---- stage 4c2 ------------------------------------------------------------------------------------

def _vnum(n):
    """The catalogue's number as verdict() wants it: an int when all digits, else the string as is
    (never a float -- int() of 11.5 would be 11)."""
    return int(n) if str(n).isdigit() else n


def _vols(c, rid):
    return {_vnum(n): i for n, i in c.execute("SELECT number, isbn13 FROM volume WHERE release_line_id=?", (rid,))}


def _lines(c):
    """The catalogue's lines as candidates() reads them. work_title: the work's primary_title (the
    export's wtitle); name: the first line_name claim by rowid (merge_line's read), else the work
    title (the export's `lname or wtitle`); arc_split: another line has this one as parent_id --
    schema/load.py writes a record's arc_of there, i.e. an arc was split out of this line's rows."""
    return [{"id": rid, "work_id": wid, "market": market, "medium": medium, "work_title": wtitle,
             "name": name or wtitle, "arc_split": bool(arc)}
            for rid, wid, market, medium, wtitle, name, arc in c.execute("""
        SELECT rl.id, rl.work_id, rl.market, rl.medium, w.primary_title,
               (SELECT value FROM claim WHERE entity='release_line' AND entity_id=rl.id
                  AND field='line_name' ORDER BY rowid LIMIT 1),
               EXISTS (SELECT 1 FROM release_line a WHERE a.parent_id=rl.id AND a.id<>rl.id)
        FROM release_line rl JOIN work w ON w.id=rl.work_id ORDER BY rl.id""")]


def read_carry(carry):
    """The carried artifact's meta round_c_merges: [[cand, target, verdict]], [] when none."""
    if not carry or not os.path.exists(carry):
        return []
    A = sqlite3.connect(carry)
    try:
        row = A.execute("SELECT value FROM meta WHERE key='round_c_merges'").fetchone()
        return [tuple(r) for r in json.loads(row[0])] if row else []
    except (sqlite3.OperationalError, TypeError, ValueError):
        return []
    finally:
        A.close()


def run(db_path, carry_path=None):
    """Stage 4c2. -> the meta list [[cand, target, kind, verdict, moved, dropped]]."""
    db = sqlite3.connect(db_path, timeout=60)
    c = db.cursor()
    exists = lambda rid: c.execute("SELECT 1 FROM release_line WHERE id=?", (rid,)).fetchone() is not None
    done, merged = [], set()
    for cand, target, kind in candidates(_lines(c)):
        if cand in merged or not exists(cand) or not exists(target):
            continue
        # volumes read now, not up front: an earlier merge into the same target changed them
        v = verdict(_vols(c, cand), _vols(c, target))
        moved = dropped = 0
        if v in ("extend", "duplicate"):
            moved, dropped = merge_line(c, cand, target)
            merged.add(cand)
        done.append([cand, target, kind, v, moved, dropped])
    key = lambda rid: c.execute("SELECT work_id, market, medium FROM release_line WHERE id=?", (rid,)).fetchone()
    for cand, target, v in read_carry(carry_path):
        # an earlier build's decision, by id: both ids are here (the ids hash work, medium, market and
        # name, so they are still the same pair) and the rule has not merged it this run
        if cand in merged or cand == target or not exists(cand) or not exists(target) or key(cand) != key(target):
            continue
        moved, dropped = merge_line(c, cand, target)
        merged.add(cand)
        done = [d for d in done if d[0] != cand]           # a rule's 'kept' gives way to the record
        done.append([cand, target, "carry", v, moved, dropped])
    c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('roundc:merged',?)", (json.dumps(done),))
    db.commit()
    db.close()
    n = lambda f: sum(1 for d in done if f(d))
    print("round C merge: %d extend, %d duplicate, %d kept, %d re-applied" % (
        n(lambda d: d[2] != "carry" and d[3] == "extend"), n(lambda d: d[2] != "carry" and d[3] == "duplicate"),
        n(lambda d: d[3] == "kept"), n(lambda d: d[2] == "carry")))
    return done


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] else None)
