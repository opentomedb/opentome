"""Round C merges (spec §3.2): stage 4c2, after 4c, before 7b.

    python3 tier0/round_c_merge.py build/opentome.db [carry-artifact]

A continuation tail ("Black Butler (Tomes 31 à aujourd'hui)", kind T) or a duplicate section line
("X (Mangas)" beside "X", kind W2) of the work's own line folds into it with carried_ids.merge_line
when its volumes say so (verdict: extend / duplicate; anything else is kept and listed). Meta
`roundc:merged` records [cand, target, kind, verdict, moved, dropped, source, reason?] for every merge
and every kept candidate (source 'rule' or 'carry'; reason only on kept / carry-conflict rows: 'verdict',
'gap', 'arc', 'not-own-line', or 'verdict:<v>' / 'gap' / 'arc' for a carry-conflict); `roundc:names`
maps each candidate to its pipeline name. extend needs contiguity (the candidate starts at the target's
last number + 1); a candidate wholly above the target with a gap is kept ('gap'). The export writes
the applied ones as artifact meta `round_c_merges` ([cand, target, verdict, kind, name]), and the next
build re-applies those by id (source 'carry') when both ids exist -- a rename can stop the rule
matching, the decision stays. No redirect rows here: 7b redirects every retired line and volume.
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
    return verdict_why(cand_vols, target_vols)[0]


def verdict_why(cand_vols, target_vols):
    """(verdict, reason): reason None when it merges; 'gap' when the candidate's numbers all lie above
    the target's but do not continue them (Gamaran 1-22 and a "(Tomes 31 à aujourd'hui)" tail that
    continues the sequel); 'verdict' for any other kept. extend needs contiguity: the candidate's
    first number is the target's last + 1."""
    if not cand_vols:
        return "kept", "verdict"
    c, t = _norm(cand_vols), _norm(target_vols)
    common = set(c) & set(t)
    if not common and t:
        cn, tn = list(c), list(t)
        if all(isinstance(x, int) for x in cn + tn) and min(cn) > max(tn):
            return ("extend", None) if min(cn) == max(tn) + 1 else ("kept", "gap")
    if not common:
        return "kept", "verdict"
    if all(n in t and (c[n] is None or c[n] == t[n]) for n in c):
        return "duplicate", None
    return "kept", "verdict"


def candidates(lines):
    """[(cand_id, target_id, kind)] sorted; kind 'T' (open-end tail) or 'W2' (round-A word). Only the
    mergeable ones: candidates_all() without the held (reason) rows."""
    return [(c, t, k) for c, t, k, why in candidates_all(lines) if why is None]


def candidates_all(lines):
    """[(cand_id, target_id, kind, reason)] sorted: every line named "<a sibling line's name> (<T or W2
    qualifier>)" in the same work, market and medium. reason None = mergeable; 'arc' = an arc was split
    out of the candidate's rows; 'not-own-line' = the target is not named after the work (spec §3.2:
    both are kept, and listed)."""
    by_name = {}
    for l in lines:
        by_name.setdefault((l["work_id"], l["market"], l["medium"], l["name"]), l["id"])
    out = []
    for l in lines:
        name = l["name"]
        if not name.endswith(")") or " (" not in name:
            continue
        target, q = name[:-1].rsplit(" (", 1)
        if re.match(_OPEN_END, q, re.I):
            kind = "T"
        elif re.match(_W2, q, re.I):
            kind = "W2"
        else:
            continue
        tid = by_name.get((l["work_id"], l["market"], l["medium"], target))
        if tid is None or tid == l["id"]:
            continue
        why = "arc" if l.get("arc_split") else "not-own-line" if target != l["work_title"] else None
        out.append((l["id"], tid, kind, why))
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
    """The carried artifact's meta round_c_merges: [(cand, target, verdict, kind or None)] -- an
    older 3-element row has no kind; a 5th element (the candidate's name) is ignored here -- [] when none."""
    if not carry or not os.path.exists(carry):
        return []
    A = sqlite3.connect(carry)
    try:
        row = A.execute("SELECT value FROM meta WHERE key='round_c_merges'").fetchone()
        return [(r[0], r[1], r[2], r[3] if len(r) > 3 else None) for r in json.loads(row[0])] if row else []
    except (sqlite3.OperationalError, TypeError, ValueError, IndexError):
        return []
    finally:
        A.close()


def run(db_path, carry_path=None):
    """Stage 4c2. -> the meta list [[cand, target, kind, verdict, moved, dropped, source(, reason)]]:
    source 'rule' or 'carry'; verdict extend / duplicate (merged), kept, or carry-conflict (a carried
    merge this build's data refuses); reason for kept / carry-conflict."""
    db = sqlite3.connect(db_path, timeout=60)
    c = db.cursor()
    exists = lambda rid: c.execute("SELECT 1 FROM release_line WHERE id=?", (rid,)).fetchone() is not None
    # verdict() compares numbers by value after _vnum ("01" == "1") while merge_line compares the raw
    # strings: this assumes the catalogue's volume numbers are canonical (no zero padding) -- counted
    padded = sorted({l for l, n in c.execute("SELECT release_line_id, number FROM volume")
                     if re.match(r"0\d", str(n))})
    lines = _lines(c)
    arc = {l["id"] for l in lines if l["arc_split"]}
    done, merged = [], set()
    kind_of = {}
    for cand, target, kind, why in candidates_all(lines):
        kind_of[(cand, target)] = kind
        if cand in merged or not exists(cand) or not exists(target):
            continue
        if why:
            done.append([cand, target, kind, "kept", 0, 0, "rule", why])
            continue
        # volumes read now, not up front: an earlier merge into the same target changed them
        v, why = verdict_why(_vols(c, cand), _vols(c, target))
        if v in ("extend", "duplicate"):
            moved, dropped = merge_line(c, cand, target)
            merged.add(cand)
            done.append([cand, target, kind, v, moved, dropped, "rule"])
        else:
            done.append([cand, target, kind, v, 0, 0, "rule", why])
    key = lambda rid: c.execute("SELECT work_id, market, medium FROM release_line WHERE id=?", (rid,)).fetchone()
    for cand, target, cv, ckind in read_carry(carry_path):
        # an earlier build's decision, by id: both ids are here (the ids hash work, medium, market and
        # name, so they are still the same pair) and the rule has not merged it this run. The own-line
        # test is waived (the work's title may have changed); this build's data must still allow it:
        # no arc split out of the candidate, and the verdict on today's volumes merges.
        if cand in merged or cand == target or not exists(cand) or not exists(target) or key(cand) != key(target):
            continue
        kind = kind_of.get((cand, target)) or ckind
        done = [d for d in done if d[0] != cand]           # this record replaces the rule's row
        if cand in arc:
            done.append([cand, target, kind, "carry-conflict", 0, 0, "carry", "arc"])
            continue
        v, why = verdict_why(_vols(c, cand), _vols(c, target))
        if v not in ("extend", "duplicate"):
            done.append([cand, target, kind, "carry-conflict", 0, 0, "carry", "gap" if why == "gap" else "verdict:" + v])
            continue
        moved, dropped = merge_line(c, cand, target)
        merged.add(cand)
        done.append([cand, target, kind, v, moved, dropped, "carry"])
    c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('roundc:merged',?)", (json.dumps(done),))
    # each candidate's pipeline name (read before any merge): the export's report and its
    # round_c_merges rows name a merged-away line by it
    name_of = {l["id"]: l["name"] for l in lines}
    c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('roundc:names',?)",
              (json.dumps({d[0]: name_of[d[0]] for d in done if d[0] in name_of}, sort_keys=True),))
    db.commit()
    db.close()
    n = lambda f: sum(1 for d in done if f(d))
    print("round C merge: %d extend, %d duplicate, %d kept, %d re-applied" % (
        n(lambda d: d[6] == "rule" and d[3] == "extend"), n(lambda d: d[6] == "rule" and d[3] == "duplicate"),
        n(lambda d: d[3] == "kept"), n(lambda d: d[6] == "carry" and d[3] in ("extend", "duplicate"))))
    conflicts = [d for d in done if d[3] == "carry-conflict"]
    if conflicts:
        print("  carried merges this build refuses (carry-conflict): %d: %s" % (
            len(conflicts), [(d[0], d[1], d[7]) for d in conflicts[:10]]))
    if padded:
        print("  WARNING: %d line(s) with zero-padded volume numbers (verdict assumes canonical numbers): %s"
              % (len(padded), padded[:10]))
    return done


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] else None)
