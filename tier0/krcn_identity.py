"""Ids for library-born KR/CN lines and works (docs/krcn-design.md §8-§9, R1; docs/id-scheme.md
Guarantee 4 and "Merges and splits"). Since this round an id is no longer derivable from the natural
key alone: a line or work that shipped keeps its published id, looked up in the carry (the last
published artifact) BEFORE a natural key is minted. Re-running the same build on the same carry
gives the same ids.

The carry names its library-born lines and works in meta 'krcn_ids' (export/to_mangarr.py, plan
ruling P3): {"works": [work ids], "lines": {tome_id: 'dnb' | 'loc' | 'bnf'}}. It holds no LCCN or
ark, so a carried line is found through what its members put into it: volume ISBNs, else volume
numbers within a line of the same source and name.

Adoption (P2) re-keys CATALOGUE rows in stage 3f -- rename_work, adopt_line -- before 4c and 7b, so
neither sees the published id as lost; the internal id never reaches the artifact and no redirect
row is written for it.
"""
import collections, json, os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "schema"))
from load import _id
import carried_ids as CI
import dnb_link as L

BIG = 1 << 40


def read_carry(carry):
    if not carry or not os.path.exists(carry):
        return None
    A = sqlite3.connect("file:%s?mode=ro" % carry, uri=True)
    cols = {r[1] for r in A.execute("PRAGMA table_info(series)")}
    if "tome_id" not in cols:
        return None
    K = {"works": set(), "lines": {}, "series_ids": set(), "work_ids": set(), "int": {},
         "line_work": {}, "line_name": {}, "line_medium": {}, "line_vols": collections.defaultdict(list)}
    try:
        ids = json.loads(A.execute("SELECT value FROM meta WHERE key='krcn_ids'").fetchone()[0])
        K["works"], K["lines"] = set(ids.get("works", [])), dict(ids.get("lines", {}))
    except (sqlite3.OperationalError, TypeError, ValueError):
        pass
    sid_of = {}
    for sid, tid, wid, name, medium in A.execute(
            "SELECT gcd_series_id, tome_id, %s, name, %s FROM series" % (
                "tome_work_id" if "tome_work_id" in cols else "NULL", "medium" if "medium" in cols else "NULL")):
        if not tid:
            continue
        sid_of[sid] = tid
        K["series_ids"].add(tid)
        K["line_work"][tid], K["line_name"][tid], K["line_medium"][tid] = wid, name, medium
        if wid:
            K["work_ids"].add(wid)
    try:
        K["int"] = {t: i for t, i, k in A.execute("SELECT opentome_id, int_id, kind FROM id_map")}
    except sqlite3.OperationalError:
        K["int"] = {t: s for s, t in sid_of.items()}
    for sid, num, isbn in A.execute("SELECT gcd_series_id, volume_number, isbn13 FROM volumes"):
        if sid in sid_of:
            K["line_vols"][sid_of[sid]].append((str(num), isbn))
    A.close()
    return K


def older(ids, K):
    """The older of several published ids: the lower id_map integer (issue order, carried,
    deterministic, §9). A work's integer is the minimum over its carried lines."""
    def key(i):
        if i in K["int"]:
            return (K["int"][i], i)
        lines = [t for t, w in K["line_work"].items() if w == i]
        return (min((K["int"].get(t, BIG) for t in lines), default=BIG), i)
    return min(ids, key=key)


def _num_key(n):
    try:
        return (0, float(n), n)
    except (TypeError, ValueError):
        return (1, 0.0, str(n))


def split_id(carried, key):
    """The id of a part split off a carried line (controller ruling 2026-09-27):
    rl_<hash("split|" + carried id + "|" + the part's own natural key)>."""
    return _id("rl_", "split|%s|%s" % (carried, key))


def line_ids(lines, K):
    """Rule 1 of the module plan (carry lookup before minting), with the split rule.
    -> {"ambiguous": [], "adopted": n, "split": [(carried id, [minor part keys])]}.

    A built line is a PART of carried line T (same source) when it holds at least one of T's
    volumes (the vote rule below). T is taken only when its parts TOGETHER hold a strict majority
    of T's volumes -- with one part this is the brief's rule, and a lone 2 of 5 still mints.

    Controller ruling 2026-09-27 (splits, docs/id-scheme.md "Merges and splits"):
      1. the part holding the most of T's volumes keeps T, whatever its own natural key; a tie goes
         to the part holding T's lowest volume number, then to the lowest own key;
      2. every other part mints a NEW id, split_id(T, its own key) -- never T, and never its bare
         key hash when that equals T (a line whose key once minted T but that now holds a minority
         or none of T's volumes);
      3. the moved volumes' published ids are left to 7b's general writer (carried_ids.redirects:
         a lost volume goes to the volume now holding its ISBN, else its number).
    So a tie is no longer ambiguous: 'ambiguous' stays empty (kept for the caller's report)."""
    rep = {"ambiguous": [], "adopted": 0, "split": []}
    parts = collections.defaultdict(list)
    by_src = collections.defaultdict(list)
    for t, src in ((K or {}).get("lines") or {}).items():
        by_src[src].append(t)
    for n_, ln in enumerate(lines):
        isb = {i for v in ln["vols"] for i in v["isbns"]}
        bare = {v["number"] for v in ln["vols"] if not v["isbns"]}
        for t in by_src.get(ln["source"], []):
            tv = K["line_vols"].get(t, [])
            if not tv:
                continue
            share = any(i in isb for _, i in tv if i)
            same_name = not any(i for _, i in tv) and L.fold(K["line_name"].get(t) or "", False) == L.fold(ln["name"] or "", False)
            held = {k for k, (n, i) in enumerate(tv) if (i and i in isb) or (not i and n in bare and (share or same_name))}
            if held:
                parts[t].append((held, n_))
    got, minor = collections.defaultdict(list), collections.defaultdict(list)
    for t, ps in parts.items():
        tv = K["line_vols"][t]
        if 2 * len(set().union(*(h for h, _ in ps))) <= len(tv):
            continue                      # T's evidence is mostly gone: nobody takes it (7b decides)
        ps.sort(key=lambda p: (-len(p[0]), min(_num_key(tv[k][0]) for k in p[0]), lines[p[1]]["key"]))
        got[ps[0][1]].append(t)
        for _, m in ps[1:]:
            minor[m].append(t)
        if len(ps) > 1:
            rep["split"].append((t, sorted(lines[m]["key"] for _, m in ps[1:])))
    rep["split"].sort()
    taken = {t for ts in got.values() for t in ts}
    for n_, ln in enumerate(lines):
        ts = got.get(n_, [])
        ln["absorbed_ids"] = []
        if ts:
            ln["tome_id"] = older(ts, K)
            ln["carried"] = True
            ln["absorbed_ids"] = sorted(set(ts) - {ln["tome_id"]})
            rep["adopted"] += 1
        elif minor.get(n_):
            ln["tome_id"] = split_id(older(minor[n_], K), ln["key"])
            ln["carried"] = False
        else:
            mint = _id("rl_", ln["key"])
            if mint in taken:             # its key once minted a carried id another part now keeps
                ln["tome_id"], ln["carried"] = split_id(mint, ln["key"]), False
            else:
                ln["tome_id"] = mint
                ln["carried"] = bool(K) and mint in K["series_ids"]
    owner = collections.defaultdict(list)          # an invariant, not a policy: one id, one line
    for ln in lines:
        for t in [ln["tome_id"]] + ln["absorbed_ids"]:
            owner[t].append(ln["key"])
    clash = sorted((t, sorted(ks)) for t, ks in owner.items() if len(ks) > 1)
    if clash:
        raise AssertionError("krcn_identity.line_ids: one id for several built lines: %r" % clash)
    return rep


def existing_lines(db, market):
    E, e_isbn = {}, {}
    for rid, wid, medium in db.execute("SELECT id, work_id, medium FROM release_line WHERE market=? ORDER BY id",
                                       (market,)):
        E[rid] = {"work": wid, "medium": medium, "vols": {}}
    # ordered: two lines of one market can share an ISBN (printings); the result must not follow row order
    for vid, rid, num, isbn in db.execute("""SELECT v.id, v.release_line_id, v.number, v.isbn13 FROM volume v
                                             JOIN release_line rl ON rl.id=v.release_line_id WHERE rl.market=?
                                             ORDER BY v.release_line_id DESC, v.id DESC""", (market,)):
        E[rid]["vols"][num] = (vid, isbn)
        if isbn:
            e_isbn[isbn] = (rid, vid)     # last wins: the lowest line id, then the lowest volume id
    return E, e_isbn


def attach_roles(lines, E, e_isbn, K):
    """Rule 2 of the module plan (attach in any direction; build_dnb.assign_roles' ISBN test)."""
    K = K or {"series_ids": set(), "int": {}}
    best = collections.defaultdict(list)
    for ln in lines:
        shared = collections.Counter(e_isbn[i][0] for v in ln["vols"] for i in v["isbns"] if i in e_isbn)
        if not shared:
            continue
        x, n = max(shared.items(), key=lambda kv: (kv[1], len(E[kv[0]]["vols"]), kv[0]))
        mine = sum(1 for v in ln["vols"] if v["isbns"])
        theirs = sum(1 for _, i in E[x]["vols"].values() if i)
        if 2 * n >= min(mine, theirs):
            best[x].append((n, ln))
    for x, cands in best.items():
        cands.sort(key=lambda t: (-t[0], t[1]["key"]))
        for k, (_, ln) in enumerate(cands):
            ln["target"], ln["work"] = x, E[x]["work"]
            if k:
                ln["role"] = "sibling"
                continue
            x_carried = x in K["series_ids"]
            if ln["carried"] and (not x_carried or K["int"].get(ln["tome_id"], BIG) < K["int"].get(x, BIG)):
                ln["role"] = "adopting"
            else:
                ln["role"] = "merged"


WORK_REFS = (("work_title", "work_id"), ("work_relation", "from_work_id"), ("work_relation", "to_work_id"),
             ("release_line", "work_id"), ("chapter", "work_id"))


def rename_work(c, old, new):
    """Every catalogue row of work `old` becomes `new` (adoption, R1 / P2). The work row is copied
    under the new id, the references moved, then the old row deleted -- valid with foreign keys on
    (schema.sql enables them; an in-memory test catalogue keeps them on) or off (the pipeline)."""
    if c.execute("SELECT 1 FROM work WHERE id=?", (new,)).fetchone():
        raise ValueError("rename_work: %s already exists" % new)
    c.execute("""INSERT INTO work (id, primary_title, native_title, year_started, demographic, status, created_at,
                 updated_at) SELECT ?, primary_title, native_title, year_started, demographic, status, created_at,
                 updated_at FROM work WHERE id=?""", (new, old))
    for table, col in WORK_REFS:
        c.execute("UPDATE %s SET %s=? WHERE %s=?" % (table, col, col), (new, old))
    c.execute("DELETE FROM work WHERE id=?", (old,))
    for t in ("claim", "resolution", "override", "external_id"):
        if CI._table(c, t):
            c.execute("UPDATE %s SET entity_id=? WHERE entity='work' AND entity_id=?" % t, (new, old))
    # a redirect (3e) pointing at the renamed id would otherwise point at nothing
    c.execute("UPDATE id_redirect SET new_id=? WHERE new_id=?", (new, old))
    if CI._table(c, "dnb_line"):
        c.execute("UPDATE dnb_line SET link_work=? WHERE link_work=?", (new, old))
        c.execute("UPDATE dnb_line SET truth_work=? WHERE truth_work=?", (new, old))
    if CI._table(c, "krcn_line"):
        c.execute("UPDATE krcn_line SET work=? WHERE work=?", (new, old))


PREC = {"day": 3, "month": 2, "year": 1}


def adopt_line(c, internal, public):
    """Rule 4 of the module plan. -> (volumes moved over, volumes merged into a public volume)."""
    have = {n: v for v, n in c.execute("SELECT id, number FROM volume WHERE release_line_id=?", (public,))}
    moved = merged = 0
    for vid, num, isbn, pc, title, rd, rp, rt in c.execute(
            """SELECT id, number, isbn13, page_count, title, release_date, release_date_precision, release_date_type
               FROM volume WHERE release_line_id=?""", (internal,)).fetchall():
        if num not in have:
            nv = _id("v_", public, num)
            CI.rename_volume(c, vid, nv, public)
            c.execute("UPDATE id_redirect SET new_id=? WHERE new_id=?", (nv, vid))
            moved += 1
            continue
        pv = have[num]
        for t in ("claim", "resolution", "override", "external_id"):
            if CI._table(c, t):
                c.execute("UPDATE OR IGNORE %s SET entity_id=? WHERE entity='volume' AND entity_id=?" % t, (pv, vid))
                c.execute("DELETE FROM %s WHERE entity='volume' AND entity_id=?" % t, (vid,))
        p_isbn, p_pc, p_title, p_rd, p_rp = c.execute(
            "SELECT isbn13, page_count, title, release_date, release_date_precision FROM volume WHERE id=?", (pv,)).fetchone()
        c.execute("UPDATE volume SET isbn13=?, page_count=?, title=? WHERE id=?",
                  (p_isbn or isbn, p_pc if p_pc is not None else pc, p_title or title, pv))
        if rd and PREC.get(rp, 0) > PREC.get(p_rp, 0):
            c.execute("UPDATE volume SET release_date=?, release_date_precision=?, release_date_type=? WHERE id=?",
                      (rd, rp, rt, pv))
        # the public volume's own composition row of the same shape wins (composition's primary key)
        c.execute("UPDATE OR IGNORE composition SET volume_id=? WHERE volume_id=?", (pv, vid))
        c.execute("DELETE FROM composition WHERE volume_id=?", (vid,))
        if CI._table(c, "dnb_member"):
            c.execute("UPDATE dnb_member SET volume_id=? WHERE volume_id=?", (pv, vid))
        c.execute("UPDATE id_redirect SET new_id=? WHERE new_id=?", (pv, vid))
        c.execute("DELETE FROM volume WHERE id=?", (vid,))
        merged += 1
    for t in ("claim", "resolution", "override", "external_id"):
        if CI._table(c, t):
            c.execute("UPDATE OR IGNORE %s SET entity_id=? WHERE entity='release_line' AND entity_id=?" % t, (public, internal))
            c.execute("DELETE FROM %s WHERE entity='release_line' AND entity_id=?" % t, (internal,))
    c.execute("UPDATE composition SET ref_line_id=? WHERE ref_line_id=?", (public, internal))
    c.execute("UPDATE release_line SET parent_id=? WHERE parent_id=?", (public, internal))
    c.execute("UPDATE id_redirect SET new_id=? WHERE new_id=?", (public, internal))
    if CI._table(c, "dnb_line"):
        c.execute("UPDATE dnb_line SET rl_id=? WHERE rl_id=?", (public, internal))
        c.execute("UPDATE dnb_line SET wiki_line=? WHERE wiki_line=?", (public, internal))
    c.execute("DELETE FROM release_line WHERE id=?", (internal,))
    return moved, merged
