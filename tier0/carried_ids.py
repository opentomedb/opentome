"""Carried ids: every id the last published artifact holds keeps resolving (docs/id-scheme.md,
docs/carried-ids.md).

    python3 tier0/carried_ids.py merge    build/opentome.db [carry-artifact]   # stage 4c
    python3 tier0/carried_ids.py redirect build/opentome.db [carry-artifact]   # stage 7b

The carried artifact is rebuild_all.sh's ID_CARRY: the last published manga-metadata.sqlite (CI
downloads it before the rebuild). Ids hash natural keys (schema/load.py), so a corrected fact
that feeds a key -- a work title, a line name -- issues new ids. The contract says the old ones
resolve forever through id_redirect. Two stages keep it, for any market, any entity, any cause:

  merge (4c, after the enrichment, before clean / corrections / resolve)
      [after the enrichment because openBD is cached by whole 80-ISBN batches of the sorted JP
      ISBNs: a merge that drops one ISBN before it shifts every later batch to an uncached URL
      (measured on the Gouttes merge: 363 of 755) -- a request burst, or, offline, dates lost]
      A work the carried artifact published that this build folded into another work (the
      work-identity pass unions articles by title, so a title fix can join two articles)
      brings its lines along, re-keyed under the surviving work. Where such a re-keyed line
      is the SAME edition as one of the survivor's carried lines -- same market and medium,
      a strict majority of the smaller line's ISBNs shared, or, when either has no ISBNs, of
      its dated volumes (number + date) -- it is merged into that carried line: the carried
      line survives byte for byte, a volume number it lacks moves over (re-keyed by number),
      the rest are dropped with their claims. Scope: only the lines of a work that absorbed
      another (this build, or a carried `work` redirect -- the duplicate comes back on every
      build), and only a line the carried artifact does not have. A line both artifacts have
      is never merged here: today's catalogue has ~500 same-work same-edition pairs (JoJo
      printings, "Tomes 31 à aujourd'hui" tails) whose ids are published.

  redirect (7b, after the audit, before the export)
      1. the carried artifact's own id_redirect rows are re-read, so a redirect survives
         every later build (chains collapse at export, stopping at the first id present in
         this build); a row whose OLD id is present again (a reverted re-key) is dropped and
         reported -- it would point a live id away, and close a cycle with the new redirect;
      2. a carried WORK this build lost -> the work now holding a strict majority of its
         volumes' ISBNs (reason duplicate_merge when that work was published, else
         correction), else the work its lines went to;
      3. a carried LINE this build lost -> in its (successor) work, same market + medium, the
         line holding a strict majority of its ISBNs, else of its dated volumes; then the same
         ISBN test market-wide (a line re-attached to another work); else the work's main
         line of that market + medium (reason retired). Two candidates tied at the top is
         AMBIGUOUS at every step: reported as an orphan (the gate fails), never picked;
      4. a carried VOLUME this build lost -> the one volume of its line's successor with its
         ISBN, else the volume of the same number there, else the one volume of its market with
         its ISBN, else the successor LINE (reason retired: the volume is gone, the id still
         resolves to where it belonged). When the LINE was retired (it fell back to its work's
         main line), numbers mean nothing -- the main line's vol 1 is another book -- so only a
         unique ISBN in the market claims it; else it retires to the line.
      Lines and volumes of works in corrections/excluded.json are retired on purpose and get
      no row (an excluded work has no successor). Anything else left without a present
      target is an orphan: reported here, and export/test_artifact.py run_ids fails on it.
      Ids 3e (build_dnb.redirects) already redirected are left as they are.
"""
import collections, datetime, json, os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "schema"))
sys.path.insert(0, os.path.join(ROOT, "tier2"))
from load import _id, MARKET_LANG, LICENCE

NOW = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
MARKET_OF_LANG = {v: k for k, v in MARKET_LANG.items()}
ORIGIN_MARKETS = ("JP", "KR", "CN", "TW")          # to_mangarr.ORIGIN


# ---- the carried artifact -------------------------------------------------------------------

def _cols(db, table):
    return {r[1] for r in db.execute("PRAGMA table_info(%s)" % table)}


def read_carry(carry):
    """The carried artifact's ids, or None when there is none.
    lines {tome_id: (work, market, medium)}; vols {tome_id: (line, number, isbn13, date)};
    redirects [(old, new, entity, reason)]."""
    if not carry or not os.path.exists(carry):
        return None
    A = sqlite3.connect(carry)
    sc, vc = _cols(A, "series"), _cols(A, "volumes")
    if "tome_id" not in sc:
        return None
    lines, by_int = {}, {}
    q = "SELECT gcd_series_id, tome_id, %s, %s, language, %s FROM series" % (
        "tome_work_id" if "tome_work_id" in sc else "NULL",
        "country" if "country" in sc else "NULL",
        "medium" if "medium" in sc else "NULL")
    for sid, tid, wid, country, lang, medium in A.execute(q):
        if tid:
            lines[tid] = (wid, country or MARKET_OF_LANG.get(lang, (lang or "").upper()), medium)
            by_int[sid] = tid
    vols = {}
    if "tome_id" in vc:
        q = "SELECT gcd_series_id, tome_id, volume_number, %s, %s FROM volumes" % (
            "isbn13" if "isbn13" in vc else "NULL", "release_date_raw" if "release_date_raw" in vc else "NULL")
        for sid, vid, num, isbn, date in A.execute(q):
            if vid and sid in by_int:
                vols[vid] = (by_int[sid], str(num), isbn, date)
    red = []
    if "old_tome_id" in _cols(A, "id_redirect"):
        rc = _cols(A, "id_redirect")
        red = A.execute("SELECT old_tome_id, new_tome_id, %s, %s FROM id_redirect" % (
            "entity" if "entity" in rc else "NULL", "reason" if "reason" in rc else "NULL")).fetchall()
    return {"lines": lines, "vols": vols, "redirects": red}


def _table(db, name):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())


def _winner(votes, n):
    """-> (winner, ambiguous). The candidate holding a strict majority of n pieces of evidence and
    more of it than any other; ordered by (-votes, id), never by dict or set order (which follows
    the hash seed). Two candidates tied at the top is AMBIGUOUS: no winner -- the caller reports
    it, the gate fails, a person decides."""
    best = sorted(((v, k) for k, v in votes.items() if v * 2 > n), key=lambda x: (-x[0], x[1]))
    if not best:
        return None, False
    if len(best) > 1 and best[1][0] == best[0][0]:
        return None, True
    return best[0][1], False


# ---- 4c. an absorbed work's duplicate lines ----------------------------------------------------

def _isbn_work_votes(db, C, work):
    """Present work -> how many of the carried work's ISBN'd volumes it holds (same market)."""
    lines = {t for t, (w, _, _) in C["lines"].items() if w == work}
    held = collections.defaultdict(set)
    for isbn, market, wid in db.execute("""SELECT v.isbn13, rl.market, rl.work_id FROM volume v
                                           JOIN release_line rl ON rl.id=v.release_line_id
                                           WHERE v.isbn13 IS NOT NULL"""):
        held[(market, isbn)].add(wid)
    votes, n = collections.Counter(), 0
    for vid, (line, _, isbn, _) in C["vols"].items():
        if line in lines and isbn:
            n += 1
            votes.update(held.get((C["lines"][line][1], isbn), ()))
    return votes, n


def absorbing_works(db, C):
    """{absorbed carried work: present work that holds it now}. A carried work this build does
    not have whose ISBNs sit (strict majority) in one present work; plus every carried `work`
    redirect whose target is present (a merge an earlier build made)."""
    present = {r[0] for r in db.execute("SELECT DISTINCT work_id FROM release_line")}
    out = {}
    for old, new, entity, _ in C["redirects"]:
        if entity == "work" and new in present:
            out[old] = new
    for w in sorted({w for w, _, _ in C["lines"].values() if w} - present - set(out)):
        best, _ = _winner(*_isbn_work_votes(db, C, w))
        if best:                          # a tie is not an absorption; 7b reports it
            out[w] = best
    return out


def _line_evidence(db, rid):
    rows = db.execute("SELECT number, isbn13, release_date FROM volume WHERE release_line_id=?", (rid,)).fetchall()
    return ({i for _, i, _ in rows if i}, {(n, d) for n, _, d in rows if d}, len(rows))


def same_edition(a, b):
    """-> the evidence count when two lines' volumes say they are one edition, else 0: a strict
    majority of the smaller side's ISBNs shared; when either has none, of its dated volumes
    (number + date, at least two)."""
    (ia, da, _), (ib, db_, _) = a, b
    if ia and ib:
        shared = len(ia & ib)
        return shared if shared * 2 > min(len(ia), len(ib)) else 0
    small = min(len(da), len(db_))
    shared = len(da & db_)
    return shared if small >= 2 and shared * 2 > small else 0


def drop_volume(c, vid):
    for t in ("claim", "resolution", "override", "external_id"):
        if _table(c, t):
            c.execute("DELETE FROM %s WHERE entity='volume' AND entity_id=?" % t, (vid,))
    c.execute("DELETE FROM composition WHERE volume_id=?", (vid,))
    if _table(c, "dnb_member"):
        c.execute("UPDATE dnb_member SET volume_id=NULL WHERE volume_id=?", (vid,))
    c.execute("DELETE FROM volume WHERE id=?", (vid,))


def rename_volume(c, vid, new_vid, line):
    c.execute("UPDATE volume SET id=?, release_line_id=? WHERE id=?", (new_vid, line, vid))
    for t in ("claim", "resolution", "override", "external_id"):
        if _table(c, t):
            c.execute("UPDATE %s SET entity_id=? WHERE entity='volume' AND entity_id=?" % t, (new_vid, vid))
    c.execute("UPDATE composition SET volume_id=? WHERE volume_id=?", (new_vid, vid))
    if _table(c, "dnb_member"):
        c.execute("UPDATE dnb_member SET volume_id=? WHERE volume_id=?", (new_vid, vid))


def merge_line(c, dup, keep):
    """Fold line `dup` into line `keep`: keep's own volumes are untouched; a number keep lacks
    moves over as v_<hash(keep, number)>; every reference to dup points at keep.
    -> (volumes moved, volumes dropped)."""
    # A licensed line finds its origin-market counterpart by the exact line name
    # (to_mangarr.origin_line). The French article's FR "Mariage" line named its JP twin, which
    # this merge removes; without a pin it would fall back to the JP MAIN line (44 volumes, not
    # 26) and export `ongoing` instead of `completed` (measured). So the lines that paired with
    # dup by name get an origin_line claim naming keep -- the corrections' mechanism, derived.
    wid, medium, market = c.execute("SELECT work_id, medium, market FROM release_line WHERE id=?", (dup,)).fetchone()
    name = (c.execute("""SELECT value FROM claim WHERE entity='release_line' AND entity_id=? AND field='line_name'
                         ORDER BY rowid""", (dup,)).fetchone() or [None])[0]
    if name and market in ORIGIN_MARKETS:
        for (lid,) in c.execute("""SELECT rl.id FROM release_line rl JOIN claim n ON n.entity='release_line'
                                   AND n.entity_id=rl.id AND n.field='line_name'
                                   WHERE rl.work_id=? AND rl.medium=? AND rl.market<>? AND LOWER(TRIM(n.value))=?
                                   AND NOT EXISTS (SELECT 1 FROM claim o WHERE o.entity='release_line'
                                                   AND o.entity_id=rl.id AND o.field='origin_line')""",
                                (wid, medium, market, name.strip().lower())).fetchall():
            c.execute("""INSERT OR IGNORE INTO claim(entity,entity_id,field,value,source,source_url,licence,retrieved_at)
                         VALUES('release_line',?,'origin_line',?,'opentome',NULL,?,?)""", (lid, keep, LICENCE["opentome"], NOW))
    have = {n for (n,) in c.execute("SELECT number FROM volume WHERE release_line_id=?", (keep,))}
    moved = dropped = 0
    for vid, num in c.execute("SELECT id, number FROM volume WHERE release_line_id=?", (dup,)).fetchall():
        if num in have:
            drop_volume(c, vid)
            dropped += 1
        else:
            rename_volume(c, vid, _id("v_", keep, num), keep)
            moved += 1
    c.execute("UPDATE composition SET ref_line_id=? WHERE ref_line_id=?", (keep, dup))
    c.execute("UPDATE release_line SET parent_id=CASE WHEN id=? THEN NULL ELSE ? END WHERE parent_id=?",
              (keep, keep, dup))
    for t in ("claim", "resolution", "override", "external_id"):
        if _table(c, t):
            c.execute("DELETE FROM %s WHERE entity='release_line' AND entity_id=?" % t, (dup,))
    if _table(c, "dnb_line"):
        c.execute("UPDATE dnb_line SET rl_id=? WHERE rl_id=?", (keep, dup))
    c.execute("DELETE FROM release_line WHERE id=?", (dup,))
    return moved, dropped


def merge_absorbed(db, carry, ambiguous=None):
    """Stage 4c. -> [(absorbed work, work, merged line, kept line, moved, dropped)]; a line two
    published lines match equally is not merged and goes to `ambiguous` (a list) when given."""
    C = read_carry(carry)
    if not C:
        return []
    c = db.cursor()
    done = []
    for old_w, w in sorted(absorbing_works(db, C).items()):
        lines = c.execute("SELECT id, market, medium FROM release_line WHERE work_id=? ORDER BY id", (w,)).fetchall()
        carried = [(r, m, d) for r, m, d in lines if r in C["lines"]]
        for rid, market, medium in lines:
            if rid in C["lines"]:
                continue
            ev = _line_evidence(c, rid)
            best = []
            for s, sm, sd in carried:
                if (sm, sd) == (market, medium):
                    es = _line_evidence(c, s)
                    n = same_edition(ev, es)
                    if n:
                        best.append((-n, -es[2], s))
            best.sort()
            if len(best) > 1 and best[0][0] == best[1][0]:
                # two published lines hold the same evidence: which one survives is not ours to
                # guess -- no merge; 7b then finds the tie too and reports the id as an orphan
                if ambiguous is not None:
                    ambiguous.append((old_w, w, rid, [b[2] for b in best if b[0] == best[0][0]]))
            elif best:
                keep = best[0][2]
                moved, dropped = merge_line(c, rid, keep)
                done.append((old_w, w, rid, keep, moved, dropped))
    db.commit()
    return done


# ---- 7b. redirects -------------------------------------------------------------------------------

def redirects(db, carry, excluded=None):
    """Stage 7b. -> report dict (counts by entity / reason / market, orphans, exempt)."""
    C = read_carry(carry)
    rep = {"rows": collections.Counter(), "by_market": collections.Counter(), "orphans": [],
           "excluded": 0, "carried_rows": 0, "written": [], "stale": [], "ambiguous": []}
    if not C:
        return rep
    if excluded is None:
        from corrections import load_exclusions
        excluded = set(load_exclusions())
    for o, n, e, r in C["redirects"]:
        rep["carried_rows"] += db.execute("INSERT OR IGNORE INTO id_redirect VALUES(?,?,?,?,?)",
                                          (o, n, e or "release_line", r, NOW)).rowcount
    lines_now = {r: (w, m, d) for r, w, m, d in db.execute("SELECT id, work_id, market, medium FROM release_line")}
    vols_now = {v: (l, n, i) for v, l, n, i in db.execute("SELECT id, release_line_id, number, isbn13 FROM volume")}
    works_now = {w for w, _, _ in lines_now.values()}
    present = set(lines_now) | set(vols_now) | works_now
    # A redirect whose OLD id is present again (a re-key reverted: "s X" -> "Les X" -> "s X") is
    # stale: kept, it would point a live id elsewhere and, with the new redirect, close a cycle.
    stale = [o for (o,) in db.execute("SELECT old_id FROM id_redirect") if o in present]
    db.executemany("DELETE FROM id_redirect WHERE old_id=?", [(o,) for o in stale])
    rep["stale"] = sorted(stale)
    red = dict(db.execute("SELECT old_id, new_id FROM id_redirect"))
    reason_of = dict(db.execute("SELECT old_id, reason FROM id_redirect"))

    def final(i):
        """Follow redirects until an id present in THIS build (or a dead end / a cycle)."""
        seen = set()
        while i in red and i not in present and i not in seen:
            seen.add(i)
            i = red[i]
        return i

    def put(old, new, entity, reason, market):
        db.execute("INSERT OR REPLACE INTO id_redirect VALUES(?,?,?,?,?)", (old, new, entity, reason, NOW))
        red[old], reason_of[old] = new, reason
        rep["rows"][(entity, reason)] += 1
        rep["by_market"][(market, entity)] += 1
        rep["written"].append((old, new, entity, reason))

    def lost(i):
        return i not in present and final(i) not in present

    carried_works = {w for w, _, _ in C["lines"].values() if w}
    exempt_lines = {t for t, (w, _, _) in C["lines"].items() if w in excluded}
    by_isbn = collections.defaultdict(list)          # (market, isbn) -> [volume]
    for v, (l, _, i) in vols_now.items():
        if i:
            by_isbn[(lines_now[l][1], i)].append(v)
    vols_of = collections.defaultdict(list)          # carried line -> [(vid, number, isbn, date)]
    for v, (l, n, i, d) in C["vols"].items():
        vols_of[l].append((v, n, i, d))
    num_in = {(l, n): v for v, (l, n, _) in vols_now.items()}
    dated_in = collections.defaultdict(set)
    for v, l, n, d in db.execute("SELECT id, release_line_id, number, release_date FROM volume WHERE release_date IS NOT NULL"):
        dated_in[l].add((n, d))

    # 2. works, from ISBNs
    for w in sorted(carried_works - excluded):
        if not lost(w):
            continue
        votes, n = collections.Counter(), 0
        for l in (t for t, (lw, _, _) in C["lines"].items() if lw == w):
            for _, _, i, _ in vols_of[l]:
                if i:
                    n += 1
                    votes.update({lines_now[vols_now[v][0]][0] for v in by_isbn.get((C["lines"][l][1], i), ())})
        best, amb = _winner(votes, n)
        if best:
            put(w, best, "work", "duplicate_merge" if best in carried_works else "correction", None)
        elif amb:
            rep["ambiguous"].append(w)

    # 3. lines
    def line_votes(l, cands):
        votes, n = collections.Counter(), 0
        market = C["lines"][l][1]
        for _, _, i, _ in vols_of[l]:
            if i:
                n += 1
                votes.update({vols_now[v][0] for v in by_isbn.get((market, i), ())} & cands)
        return votes, n

    size = collections.Counter(l for l, _, _ in vols_now.values())

    # the main line of a (work, market, medium): the largest, then the id (build_dnb's rule)
    main_of = {}
    for r, k in sorted(lines_now.items(), key=lambda kv: (-size[kv[0]], kv[0])):
        main_of.setdefault(k, r)

    for l in sorted(C["lines"]):
        if not lost(l) or l in exempt_lines:
            continue
        w, market, medium = C["lines"][l]
        wn = w if w in works_now else (final(w) if final(w) in works_now else None)
        succ, how, amb = None, None, False
        if wn:
            cands = {r for r, (rw, m, d) in lines_now.items() if rw == wn and m == market and d == medium}
            succ, amb = _winner(*line_votes(l, cands))
            if not succ and not amb:
                dated = {(n, d) for _, n, _, d in vols_of[l] if d}
                sig = collections.Counter({r: len(dated & dated_in[r]) for r in cands})
                if len(dated) >= 2:
                    succ, amb = _winner(sig, len(dated))
        if not succ and not amb:
            cands = {r for r, (_, m, d) in lines_now.items() if m == market and d == medium}
            succ, amb = _winner(*line_votes(l, cands))
        if amb:
            rep["ambiguous"].append(l)
            rep["orphans"].append(l)
            continue
        if succ:
            how = "duplicate_merge" if succ in C["lines"] else "correction"
        elif wn and (wn, market, medium) in main_of:
            succ, how = main_of[(wn, market, medium)], "retired"
        if succ:
            put(l, succ, "release_line", how, market)
        else:
            rep["orphans"].append(l)

    # 2b. works whose lines had to show the way (no ISBNs of their own)
    for w in sorted(carried_works - excluded):
        if not lost(w):
            continue
        votes = collections.Counter(lines_now[final(l)][0] for l, (lw, _, _) in C["lines"].items()
                                    if lw == w and final(l) in lines_now)
        best, amb = _winner(votes, sum(votes.values()))
        if best and w not in rep["ambiguous"]:
            put(w, best, "work", "duplicate_merge" if best in carried_works else "correction", None)
        else:
            rep["orphans"].append(w)
            if amb and w not in rep["ambiguous"]:
                rep["ambiguous"].append(w)

    # 4. volumes
    for v in sorted(C["vols"]):
        l, n, i, _ = C["vols"][v]
        if not lost(v) or l in exempt_lines:
            continue
        ls = l if l in lines_now else (final(l) if final(l) in lines_now else None)
        market = C["lines"][l][1]
        if not ls:
            rep["orphans"].append(v)
            continue
        line_reason = reason_of.get(l) if l not in lines_now else "correction"
        in_market = by_isbn.get((market, i), ()) if i else ()
        if line_reason == "retired":
            # the line fell back to its work's main line: that line's volume N is a DIFFERENT book
            # (an arc's vol 1 is not the main series' vol 1) -- only a unique ISBN may claim it
            if len(in_market) == 1:
                put(v, in_market[0], "volume", "correction", market)
            else:
                put(v, ls, "volume", "retired", market)
            continue
        vol_reason = "duplicate_merge" if line_reason == "duplicate_merge" else "correction"
        in_line = [x for x in in_market if vols_now[x][0] == ls]
        nv = (in_line[0] if len(in_line) == 1 else None) or num_in.get((ls, n))
        if nv:
            put(v, nv, "volume", vol_reason, market)
        elif len(in_market) == 1:
            put(v, in_market[0], "volume", "correction", market)
        else:
            put(v, ls, "volume", "retired", market)

    rep["excluded"] = sum(1 for t in C["lines"] if t in exempt_lines) + \
        sum(1 for v, (l, _, _, _) in C["vols"].items() if l in exempt_lines)
    # every carried id resolves (or is an excluded work's)
    rep["orphans"] = sorted(set(rep["orphans"]) | {
        i for i in set(C["lines"]) | set(C["vols"]) | (carried_works - excluded)
        if lost(i) and i not in exempt_lines and C["vols"].get(i, (None,))[0] not in exempt_lines})
    db.commit()
    return rep


def carry_required():
    """In CI (OPENTOME_CI=1 or CI=true) a build without a carried artifact must fail, unless
    OPENTOME_COLD_START=1 says the cold start is deliberate (docs/carried-ids.md)."""
    ci = os.environ.get("OPENTOME_CI") == "1" or os.environ.get("CI", "").lower() == "true"
    return ci and os.environ.get("OPENTOME_COLD_START") != "1"


def main(argv):
    if len(argv) < 3 or argv[1] not in ("merge", "redirect"):
        raise SystemExit(__doc__)
    db = sqlite3.connect(argv[2], timeout=60)
    carry = argv[3] if len(argv) > 3 and argv[3] else None
    if not read_carry(carry):
        if carry_required():
            raise SystemExit("FAILED: no carried artifact (%r) in CI -- every published id would go "
                             "unredirected. Set OPENTOME_COLD_START=1 only for a deliberate cold start." % carry)
        print("  WARNING: no carried artifact -- nothing to keep resolving (cold id assignment)")
        return
    if argv[1] == "merge":
        amb = []
        done = merge_absorbed(db, carry, amb)
        print("  absorbed-work duplicate lines merged: %d" % len(done))
        for old_w, w, dup, keeps in amb:
            print("    AMBIGUOUS %s -> %s: %s matches %s equally -- not merged (7b reports it)" % (old_w, w, dup, keeps))
        for old_w, w, dup, keep, moved, dropped in done:
            print("    %s -> %s: %s into %s (%d volumes moved, %d dropped)" % (old_w, w, dup, keep, moved, dropped))
        db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('carried:merged',?)", (json.dumps(done),))
        db.commit()
        return
    rep = redirects(db, carry)
    print("  carried id_redirect rows re-read: %d new" % rep["carried_rows"])
    if rep["stale"]:
        print("  dropped %d redirect(s) whose old id is present again (a reverted re-key): %s"
              % (len(rep["stale"]), rep["stale"][:10]))
    print("  redirects written: %d  (%s)" % (sum(rep["rows"].values()), ", ".join(
        "%s/%s %d" % (e, r, n) for (e, r), n in sorted(rep["rows"].items()))))
    if rep["by_market"]:
        print("  by market: %s" % ", ".join("%s %s %d" % (m or "-", e, n) for (m, e), n in sorted(
            rep["by_market"].items(), key=lambda kv: (kv[0][0] or "", kv[0][1]))))
    print("  excluded works' ids retired without a row: %d" % rep["excluded"])
    if rep["ambiguous"]:
        print("  AMBIGUOUS (two successors tied on the evidence -- a person decides): %d: %s"
              % (len(rep["ambiguous"]), rep["ambiguous"][:10]))
    if rep["orphans"]:
        print("  NO SUCCESSOR for %d carried id(s): %s -- export/test_artifact.py will fail"
              % (len(rep["orphans"]), rep["orphans"][:10]))
    db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('carried:redirects',?)", (json.dumps({
        "rows": {"%s/%s" % k: v for k, v in rep["rows"].items()}, "orphans": rep["orphans"],
        "excluded": rep["excluded"], "stale": rep["stale"], "ambiguous": rep["ambiguous"]}),))
    db.commit()


if __name__ == "__main__":
    main(sys.argv)
