"""Stage 3e: the German market from the Deutsche Nationalbibliothek (docs/dnb-design.md).

    python3 tier0/build_dnb.py build/opentome.db [carry-artifact]

German Wikipedia documents ~35 manga lines with volume tables (docs/german-market.md);
legal deposit puts every German print volume in DNB, CC0. This stage turns DNB's
Japanese-origin print manga and light novels into DE release lines:

  1. records     tier0/dnb_enumerate.py (three channels, cached; zero network on a rerun)
  2. select      Japanese origin; manga or light novel (tier0/dnb_marc.classify); print
                 only (the queries say bbg=A*); bundles, box sets, artbooks, guides and
                 combined "1 - 3" records are not volumes in v1
  3. volumes     ISBN twins merged (a pre-publication record + the deposit copy, or a
                 special edition sharing the ISBN); an ISBN on records with DIFFERENT
                 volume numbers is a box-set ISBN and is dropped from all of them
  4. lines       parent IDN (773$w); else folded series + publisher (+ medium, edition);
                 else folded bare title + publisher; series/title clusters fold into the
                 parent line of the same folded name + publisher + edition. Line id =
                 hash of 'dnb:<parent IDN>' / 'dnb:<lowest member IDN>' -- source data
                 only, so relinking a line to another work never re-keys it
  5. merge       with the German Wikipedia lines: an ISBN shared with a Wikipedia volume
                 attaches to that volume (it gains dnb claims); a DNB line holding the
                 majority of a Wikipedia line's shared ISBNs merges into it and keeps its
                 rl_ id; a second such DNB line is a sibling (same work, own id); a DNB
                 line sharing ISBNs with several Wikipedia lines merges into the one it
                 shares most with, and the others are left as they are
  6. link        tier0/dnb_link.py, title + author only. Merged/sibling lines are the
                 ground truth: the linker runs on them too, and a wrong link there fails
                 export/test_artifact.py
  7. load        high/medium links and ISBN siblings become release lines; low and
                 ambiguous go to build/dnb-review.tsv; the rest stay in the staging tables
  8. redirects   a German line id in the carried artifact that this build no longer has
                 is redirected (id_redirect) to the line now holding most of its ISBNs

Dates (decision 2): 008 year -> 'published', precision 'year', from any deposited
record; an announcement-only volume (every record at leader/17 = '8') takes its 263
planned month as 'projected', precision 'month' -- and when its year is after the
current year it is held back altogether (2027-2030 placeholders, likely cancellations).
Every claim: source 'dnb', licence 'cc0', source_url https://d-nb.info/<IDN>. No
covers, no blurbs (856 is never read).
"""
import collections, datetime, json, os, re, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "schema"))
import dnb_enumerate as E
import dnb_link as L
import dnb_marc as M
import dnb_sru as S
from load import LICENCE, _id

NOW = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
CURRENT_YEAR = datetime.date.today().year
SRC = "dnb"
BUILD = os.path.join(ROOT, "build")

STAGING_DDL = """
CREATE TABLE IF NOT EXISTS dnb_line (       -- one row per DNB line, exported or not
    key TEXT PRIMARY KEY,                   -- 'dnb:<parent IDN>' | 'dnb:<lowest member IDN>'
    rl_id TEXT NOT NULL,                    -- the release line it is (or would be)
    name TEXT, publisher TEXT, medium TEXT, edition TEXT,
    n_volumes INTEGER,
    tier TEXT, via TEXT,                    -- the linker's verdict, whatever the role
    link_work TEXT, candidates TEXT,
    role TEXT NOT NULL,                     -- merged | sibling | linked | review | unlinked | absorbed
    wiki_line TEXT, truth_work TEXT,        -- merged / sibling: the Wikipedia line and its work
    exported INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS dnb_member (     -- one row per DNB volume record kept
    idn TEXT PRIMARY KEY, line_key TEXT, number TEXT, isbn13 TEXT,
    volume_id TEXT,                         -- NULL when the volume did not reach `volume`
    fate TEXT NOT NULL,                     -- created | attached | held_future | dropped_* | line_*
    filled TEXT);                           -- attached: the empty Wikipedia columns it filled (JSON)
"""


def url(idn):
    return "https://d-nb.info/" + idn


def idn_key(i):
    """IDNs are digit strings with an optional X check character; compare as numbers."""
    return (len(i), i)


def pubkey(p):
    return L.fold(re.sub(r"(?i)\b(gmbh|verlag\w*|verl\.?-?ges\.?|verlagsgesellschaften|mbh|manga!?|sa|ag)\b",
                         "", p or ""), False)[:6]


# ---- 2. select --------------------------------------------------------------------

def select(recs):
    """-> (kept volume dicts, Counter of drop reasons)."""
    kept, drop = [], collections.Counter()
    for r in recs.values():
        if M.is_parent(r):
            continue
        if not M.origin_in_scope(r):
            drop["origin_out_of_scope"] += 1
            continue
        cls = M.classify(r)
        if cls not in ("manga", "light_novel"):
            drop["class_" + cls] += 1
            continue
        num, kind, numsrc = M.volume_number(r)
        if kind == "range":
            drop["combined_range"] += 1
            continue
        kept.append({"r": r, "idn": M.idn(r), "medium": cls, "num": num, "numsrc": numsrc,
                     "isbns": M.isbns(r), "ann": M.is_announcement(r),
                     "parent": (M.parent_idns(r) or [None])[0]})
    return kept, drop


# ---- 3. volumes (ISBN twins) ----------------------------------------------------------

def twins(vols):
    """-> (groups, box-set ISBNs). A group is one physical volume: records joined by a
    shared ISBN that is not a box-set ISBN."""
    by_isbn = collections.defaultdict(list)
    for v in vols:
        for i in v["isbns"]:
            by_isbn[i].append(v)
    boxset = {i for i, vs in by_isbn.items() if len({v["num"] for v in vs if v["num"]}) > 1}
    up = {v["idn"]: v["idn"] for v in vols}

    def find(x):
        while up[x] != x:
            up[x] = up[up[x]]
            x = up[x]
        return x
    for i, vs in by_isbn.items():
        if i in boxset:
            continue
        for v in vs[1:]:
            a, b = find(vs[0]["idn"]), find(v["idn"])
            if a != b:
                up[max(a, b, key=idn_key)] = min(a, b, key=idn_key)
    members = collections.defaultdict(list)
    for v in vols:
        members[find(v["idn"])].append(v)
    groups = []
    for ms in members.values():
        ms.sort(key=lambda v: (v["ann"], idn_key(v["idn"])))      # deposited records first
        groups.append(group_of(ms, boxset))
    return groups, boxset


def group_of(ms, boxset):
    p = ms[0]
    r = p["r"]
    isbns = [i for v in ms for i in v["isbns"] if i not in boxset]
    isbns = list(dict.fromkeys(isbns))
    series = next((s for v in ms for s in M.series_statements(v["r"])), None)
    return {
        "members": ms, "primary": p["idn"], "idns": [v["idn"] for v in ms],
        "num": next((v["num"] for v in ms if v["num"]), None),
        "numsrc": next((v["numsrc"] for v in ms if v["num"]), None),
        "medium": p["medium"], "edition": M.edition_marker(r),
        "parent": next((v["parent"] for v in ms if v["parent"]), None),
        "series": series[0] if series else None,
        "isbn": isbns[0] if isbns else None, "isbns": isbns,
        "pages": next((n for n in (M.pages(v["r"]) for v in ms) if n), None),
        "date": group_date(ms),
        "publisher": M.publisher(r), "bare": M.bare_title(r),
    }


def group_date(ms):
    """-> (value, precision, type) | ('HELD', ...) for a future-year announcement | None."""
    deposited = [v for v in ms if not v["ann"]]
    if deposited:
        ys = sorted(y for y in (M.year(v["r"]) for v in deposited) if y)
        return (ys[0], "year", "published") if ys else None
    planned = next((m for m in (M.planned_month(v["r"]) for v in ms) if m), None)
    ys = [int(y) for y in (M.year(v["r"]) for v in ms) if y]
    if planned:
        ys.append(int(planned[:4]))
    if ys and max(ys) > CURRENT_YEAR:
        return ("HELD", None, None)
    return (planned, "month", "projected") if planned else None


# ---- 4. lines ----------------------------------------------------------------------

def raw_key(g):
    ed = g["edition"] or ""
    if g["parent"]:
        return "parent:" + g["parent"]
    if g["series"]:
        return "series:%s|%s|%s|%s" % (L.fold(g["series"], False), pubkey(g["publisher"]), g["medium"], ed)
    if g["num"]:
        return "title:%s|%s|%s|%s" % (L.fold(g["bare"], False), pubkey(g["publisher"]), g["medium"], ed)
    return "single:" + g["primary"]


def cluster(groups, parents):
    """-> {line key: [groups]}, folding series/title clusters into a unique parent line of
    the same folded name + publisher + medium + edition marker (a light novel and its manga
    adaptation often share a title and a publisher)."""
    raw = collections.defaultdict(list)
    for g in groups:
        raw[raw_key(g)].append(g)
    pname = collections.defaultdict(set)
    for k, gs in raw.items():
        if k.startswith("parent:") and k[7:] in parents:
            p = parents[k[7:]]
            media = collections.Counter(g["medium"] for g in gs)
            medium = "light_novel" if media["light_novel"] > media["manga"] else "manga"
            pname[(L.fold(M.clean(M.first(p, "245", "a")), False), pubkey(M.publisher(p)),
                   medium, M.edition_marker(p) or "")].add(k)
    lines = collections.defaultdict(list)
    for k, gs in raw.items():
        target = k
        if k.startswith(("series:", "title:")):
            name, pub, medium, ed = k.split(":", 1)[1].split("|")
            cands = pname.get((name, pub, medium, ed), set())
            if len(cands) == 1:
                target = next(iter(cands))
        lines[target].extend(gs)
    out = {}
    for k, gs in lines.items():
        if k.startswith("parent:"):
            key = "dnb:" + k[7:]
        else:
            key = "dnb:" + min((i for g in gs for i in g["idns"]), key=idn_key)
        out[key] = gs
    return out


def shape_line(key, gs, parents):
    """Number the line's volumes: one group per number (the deposited, lowest-IDN record
    wins), an unnumbered group is volume 1 of a one-volume line and dropped otherwise.
    -> (line dict, [(group, fate)] for the groups that did not make it)"""
    out, lost, seen = [], [], set()
    # the regular edition beats a limited / special one; a deposited volume an announcement;
    # then the first catalogued (a later record of the same number is usually a reprint)
    gs = sorted(gs, key=lambda g: (g["date"] is not None and g["date"][0] == "HELD",
                                   all(v["ann"] for v in g["members"]), g["edition"] is not None,
                                   idn_key(g["primary"])))
    for g in gs:
        num = g["num"]
        if num is None:
            if len(gs) == 1:
                num = "1"
            else:
                lost.append((g, "dropped_unnumbered"))
                continue
        if num in seen:
            lost.append((g, "dropped_duplicate_number"))
            continue
        seen.add(num)
        out.append(dict(g, number=num))
    pidn = key[4:] if key[4:] in parents else None
    p = parents.get(pidn) if pidn else None
    name = (M.clean(M.first(p, "245", "a")) if p is not None else None) \
        or next((g["series"] for g in out if g["series"]), None) \
        or (out[0]["bare"] if out else None)
    pubs = collections.Counter(g["publisher"] for g in out if g["publisher"])
    media = collections.Counter(g["medium"] for g in out)
    recs = ([p] if p is not None else []) + [v["r"] for g in out for v in g["members"]]
    titles, orig = [], []
    for r in recs:
        orig += M.original_titles(r)
        titles += M.original_titles(r)
        a = M.clean(M.first(r, "245", "a"))
        if a:
            titles.append(a)
        titles += [s for s, _ in M.series_statements(r)]
    authors = []
    for r in recs:
        authors += [a for a in M.creators(r) if a not in authors]
    line = {"key": key, "rl_id": _id("rl_", key), "name": name,
            "publisher": pubs.most_common(1)[0][0] if pubs else (M.publisher(p) if p is not None else None),
            "medium": "light_novel" if media.get("light_novel", 0) > media.get("manga", 0) else "manga",
            "edition": next((g["edition"] for g in out if g["edition"]), None) or
                       (M.edition_marker(p) if p is not None else None),
            "vols": out, "titles": list(dict.fromkeys(titles)), "orig": list(dict.fromkeys(orig)),
            "authors": authors}
    return line, lost


FORMAT = {"massiv": "omnibus", "mehrfachband": "omnibus", "deluxe": "deluxe", "perfect": "deluxe",
          "collector": "deluxe", "kanzenban": "deluxe"}


# ---- 5. Wikipedia DE lines ---------------------------------------------------------------

def wiki_lines(db):
    """The German lines already in the catalogue (Wikipedia): {rl_id: {work, vols}} and
    {isbn: (rl_id, volume_id)}."""
    W, by_isbn = {}, {}
    for rid, wid in db.execute("SELECT id, work_id FROM release_line WHERE market='DE'"):
        W[rid] = {"work": wid, "vols": {}}
    for vid, rid, num, isbn in db.execute("""SELECT v.id, v.release_line_id, v.number, v.isbn13 FROM volume v
                                             JOIN release_line rl ON rl.id=v.release_line_id
                                             WHERE rl.market='DE'"""):
        W[rid]["vols"][num] = (vid, isbn)
        if isbn:
            by_isbn[isbn] = (rid, vid)
    return W, by_isbn


def assign_roles(lines, W, w_isbn):
    """Set line['role'] / ['wiki_line'] from ISBN overlap with the Wikipedia lines."""
    best_for_w = collections.defaultdict(list)
    for ln in lines:
        shared = collections.Counter(w_isbn[i][0] for g in ln["vols"] for i in g["isbns"] if i in w_isbn)
        ln["role"], ln["wiki_line"] = None, None
        if not shared:
            continue
        rid, n = max(shared.items(), key=lambda kv: (kv[1], len(W[kv[0]]["vols"]), kv[0]))
        mine = sum(1 for g in ln["vols"] if g["isbns"])
        theirs = sum(1 for _, isbn in W[rid]["vols"].values() if isbn)
        if 2 * n >= min(mine, theirs):          # the majority of the smaller side
            best_for_w[rid].append((n, ln))
    for rid, cands in best_for_w.items():
        cands.sort(key=lambda t: (-t[0], idn_key(t[1]["key"][4:])))
        for i, (_, ln) in enumerate(cands):
            ln["role"], ln["wiki_line"] = ("merged" if i == 0 else "sibling"), rid


# ---- the build (pure: records in, lines out) -----------------------------------------------

def build(recs, parents, idx, W, w_isbn):
    """-> (lines, stats, lost [(group, fate, line key)])."""
    allparents = dict(parents)
    allparents.update({k: r for k, r in recs.items() if M.is_parent(r)})
    vols, drop = select(recs)
    groups, boxset = twins(vols)
    clusters = cluster(groups, allparents)
    lines, lost = [], []
    for key in sorted(clusters):
        ln, l2 = shape_line(key, clusters[key], allparents)
        lost += [(g, f, key) for g, f in l2]
        if not ln["vols"]:
            continue
        tier, work, cands, via = L.link(idx, ln["titles"], ln["authors"], ln["orig"], ln["name"])
        ln.update(tier=tier, link_work=work, candidates=cands, via=via)
        lines.append(ln)
    assign_roles(lines, W, w_isbn)
    for ln in lines:
        if ln["role"] in ("merged", "sibling"):
            ln["truth_work"] = W[ln["wiki_line"]]["work"]
            ln["work"] = ln["truth_work"]
        else:
            ln["truth_work"] = None
            ln["role"] = {"high": "linked", "medium": "linked", "low": "review",
                          "ambiguous": "review"}.get(ln["tier"], "unlinked")
            ln["work"] = ln["link_work"] if ln["role"] == "linked" else None
    stats = {"records": len(recs), "parents_known": len(allparents), "kept_records": len(vols),
             "dropped": dict(sorted(drop.items())), "volume_groups": len(groups),
             "twin_records_merged": len(vols) - len(groups), "boxset_isbns": len(boxset),
             "lines": len(lines)}
    return lines, stats, lost


# ---- 7. load ----------------------------------------------------------------------------

def _claim(c, entity, eid, field, value, idn):
    c.execute("""INSERT OR REPLACE INTO claim
        (entity,entity_id,field,value,source,source_url,licence,retrieved_at)
        VALUES(?,?,?,?,?,?,?,?)""", (entity, eid, field, str(value), SRC, url(idn), LICENCE[SRC], NOW))


def _volume_claims(c, vid, g):
    p = g["primary"]
    if g["isbn"]:
        _claim(c, "volume", vid, "isbn13", g["isbn"], p)
    d = g["date"]
    if d and d[0] != "HELD":
        _claim(c, "volume", vid, "release_date" if d[2] == "published" else "projected_date", d[0], p)
    if g["pages"]:
        _claim(c, "volume", vid, "page_count", g["pages"], p)
    _claim(c, "volume", vid, "volume_number", g["number"], p)


def unload(c):
    """Remove what a previous run of this stage wrote, so a rerun is a clean reload."""
    try:
        made_lines = [r[0] for r in c.execute("SELECT rl_id FROM dnb_line WHERE exported=1 AND role<>'merged'")]
        made_vols = [r[0] for r in c.execute("SELECT volume_id FROM dnb_member WHERE fate='created'")]
    except sqlite3.OperationalError:
        return
    for vid, filled in c.execute("SELECT DISTINCT volume_id, filled FROM dnb_member WHERE fate='attached' "
                                 "AND filled IS NOT NULL").fetchall():
        for col in json.loads(filled):
            if col == "release_date":
                c.execute("""UPDATE volume SET release_date=NULL, release_date_precision=NULL,
                             release_date_type='unknown' WHERE id=?""", (vid,))
            else:
                c.execute("UPDATE volume SET %s=NULL WHERE id=?" % col, (vid,))
    c.executemany("DELETE FROM volume WHERE id=?", [(v,) for v in made_vols])
    c.executemany("DELETE FROM release_line WHERE id=?", [(r,) for r in made_lines])
    c.execute("DELETE FROM claim WHERE source=?", (SRC,))
    c.execute("DELETE FROM dnb_line")
    c.execute("DELETE FROM dnb_member")


def load(db, lines, lost, W, w_isbn):
    """Write the exported lines, their volumes and claims, and the staging tables."""
    c = db.cursor()
    c.executescript(STAGING_DDL)
    unload(c)
    st = collections.Counter()
    for ln in lines:
        exported = ln["role"] in ("merged", "sibling", "linked")
        rid = ln["wiki_line"] if ln["role"] == "merged" else ln["rl_id"]
        wvols = W[rid]["vols"] if ln["role"] == "merged" else {}
        if exported and ln["role"] != "merged":
            c.execute("""INSERT OR IGNORE INTO release_line
                (id,work_id,parent_id,medium,market,language,publisher,format,created_at,updated_at)
                VALUES(?,?,NULL,?,'DE','de',?,?,?,?)""",
                (rid, ln["work"], ln["medium"], ln["publisher"], FORMAT.get(ln["edition"]), NOW, NOW))
            _claim(c, "release_line", rid, "line_name", ln["name"], ln["key"][4:])
            if ln["publisher"]:
                _claim(c, "release_line", rid, "publisher", ln["publisher"], ln["key"][4:])
        n_out = 0
        for g in ln["vols"]:
            fate, vid = "line_" + ln["role"], None
            wiki = next((w_isbn[i] for i in g["isbns"] if i in w_isbn), None)
            if wiki:
                # the same book is already a Wikipedia volume: it gains dnb claims
                vid, fate = wiki[1], "attached"
            elif exported:
                if g["date"] and g["date"][0] == "HELD":
                    fate = "held_future"
                elif not g["isbn"] and not g["date"]:
                    fate = "dropped_no_date_no_isbn"
                elif g["number"] in wvols:
                    wvid, wisbn = wvols[g["number"]]
                    if wisbn and wisbn not in g["isbns"]:
                        fate = "dropped_number_clash"
                    else:
                        vid, fate = wvid, "attached"
                else:
                    vid, fate = _id("v_", rid, g["number"]), "created"
                    d = g["date"] if g["date"] else (None, None, None)
                    fmt = FORMAT.get(g["edition"] or ln["edition"])
                    c.execute("""INSERT OR IGNORE INTO volume
                        (id,release_line_id,number,title,isbn13,page_count,format,release_date,
                         release_date_precision,release_date_type,created_at,updated_at)
                        VALUES(?,?,?,NULL,?,?,?,?,?,?,?,?)""",
                        (vid, rid, g["number"], g["isbn"], g["pages"], fmt, d[0], d[1],
                         d[2] or "unknown", NOW, NOW))
            filled = None
            if vid:
                _volume_claims(c, vid, g)
                if fate == "attached":
                    done = fill_attached(c, vid, g)
                    filled = json.dumps(done) if done else None
                n_out += fate == "created"
            st[fate] += 1
            for m in g["members"]:
                c.execute("INSERT OR REPLACE INTO dnb_member VALUES(?,?,?,?,?,?,?)",
                          (m["idn"], ln["key"], g["number"], g["isbn"], vid, fate, filled))
        if exported and ln["role"] != "merged" and not n_out and not c.execute(
                "SELECT 1 FROM volume WHERE release_line_id=?", (rid,)).fetchone():
            # every volume was attached elsewhere or held back: no empty line
            c.execute("DELETE FROM release_line WHERE id=?", (rid,))
            c.execute("DELETE FROM claim WHERE entity='release_line' AND entity_id=?", (rid,))
            ln["role"], exported = "absorbed", False
        ln["exported"] = exported
        c.execute("INSERT OR REPLACE INTO dnb_line VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (ln["key"], rid, ln["name"], ln["publisher"], ln["medium"], ln["edition"],
                   len(ln["vols"]), ln["tier"], ln["via"], ln["link_work"],
                   json.dumps(ln["candidates"][:8]), ln["role"], ln["wiki_line"], ln["truth_work"],
                   int(exported)))
    for g, fate, key in lost:
        for m in g["members"]:
            c.execute("INSERT OR REPLACE INTO dnb_member VALUES(?,?,?,?,NULL,?,NULL)",
                      (m["idn"], key, g["num"], g["isbn"], fate))
            st[fate] += 1
    db.commit()
    return st


def fill_attached(c, vid, g):
    """A Wikipedia volume that gained a DNB twin: fill what Wikipedia left empty. A
    Wikipedia date is never replaced (its day dates win); a projected date never fills a
    volume that has any date. -> the columns it filled, so unload() can put them back."""
    isbn, date, pc = c.execute("SELECT isbn13, release_date, page_count FROM volume WHERE id=?", (vid,)).fetchone()
    filled = []
    if not isbn and g["isbn"]:
        c.execute("UPDATE volume SET isbn13=? WHERE id=?", (g["isbn"], vid))
        filled.append("isbn13")
    d = g["date"]
    if not date and d and d[0] != "HELD":
        c.execute("""UPDATE volume SET release_date=?, release_date_precision=?, release_date_type=?
                     WHERE id=?""", (d[0], d[1], d[2], vid))
        filled.append("release_date")
    if pc is None and g["pages"]:
        c.execute("UPDATE volume SET page_count=? WHERE id=?", (g["pages"], vid))
        filled.append("page_count")
    return filled


# ---- 8. redirects ----------------------------------------------------------------------------

def redirects(db, carry):
    """German line ids in the carried artifact that this build no longer has -> id_redirect
    to the German line now holding most of their ISBNs (volumes follow by number).
    -> (lines redirected, lines with no successor)."""
    if not carry or not os.path.exists(carry):
        return 0, []
    A = sqlite3.connect(carry)
    try:
        old = A.execute("""SELECT s.tome_id, v.volume_number, v.tome_id, v.isbn13 FROM series s
                           JOIN volumes v USING(gcd_series_id) WHERE s.language='de'""").fetchall()
    except sqlite3.OperationalError:
        return 0, []
    now = {r[0] for r in db.execute("SELECT id FROM release_line WHERE market='DE'")}
    isbn_to = dict(db.execute("""SELECT v.isbn13, v.release_line_id FROM volume v JOIN release_line rl
                                 ON rl.id=v.release_line_id WHERE rl.market='DE' AND v.isbn13 IS NOT NULL"""))
    by_old = collections.defaultdict(list)
    for tid, num, vtid, isbn in old:
        by_old[tid].append((num, vtid, isbn))
    moved, orphans = 0, []
    for tid, vs in by_old.items():
        if tid in now or db.execute("SELECT 1 FROM id_redirect WHERE old_id=?", (tid,)).fetchone():
            continue
        votes = collections.Counter(isbn_to[i] for _, _, i in vs if i in isbn_to)
        if not votes:
            orphans.append(tid)
            continue
        new = votes.most_common(1)[0][0]
        db.execute("INSERT OR IGNORE INTO id_redirect VALUES(?,?,?,?,?)",
                   (tid, new, "release_line", "correction", NOW))
        for num, vtid, _ in vs:
            nv = db.execute("SELECT id FROM volume WHERE release_line_id=? AND number=?",
                            (new, str(num))).fetchone()
            if nv and vtid and nv[0] != vtid:
                db.execute("INSERT OR IGNORE INTO id_redirect VALUES(?,?,?,?,?)",
                           (vtid, nv[0], "volume", "correction", NOW))
        moved += 1
    db.commit()
    return moved, orphans


# ---- report ------------------------------------------------------------------------------

def review_file(lines, idx, path):
    rows = [ln for ln in lines if ln["role"] == "review"]
    rows.sort(key=lambda ln: (ln["tier"], -len(ln["vols"]), ln["key"]))
    with open(path, "w", encoding="utf8") as f:
        f.write("tier\tvia\tdnb_key\trl_id\tname\tpublisher\tmedium\tvolumes\tcandidates\t"
                "original_titles\tauthors\tdnb_url\n")
        for ln in rows:
            cands = "; ".join("%s %s" % (w, idx.name.get(w, "?")) for w in ln["candidates"][:6])
            f.write("\t".join(str(x).replace("\t", " ") for x in (
                ln["tier"], ln["via"], ln["key"], ln["rl_id"], ln["name"], ln["publisher"] or "",
                ln["medium"], len(ln["vols"]), cands,
                " | ".join(ln["titles"][:4]), " | ".join(ln["authors"][:3]), url(ln["key"][4:]))) + "\n")
    return len(rows)


def run(dbpath, carry=None):
    db = sqlite3.connect(dbpath, timeout=60)
    print("  enumerating (cached; live requests are logged to build/dnb-netlog.tsv)", flush=True)
    recs, parents, tally = E.enumerate_all(verbose=False)
    gaps = {k: v for k, v in tally.items() if k.endswith("_slice_gap") and v}
    if gaps:
        raise SystemExit("DNB enumeration incomplete -- year slices miss records: %s" % gaps)
    # a rerun on a populated catalogue first takes back what the last run wrote, so the
    # Wikipedia side and the linker's index are read exactly as the first run read them
    db.executescript(STAGING_DDL)
    unload(db.cursor())
    db.commit()
    idx = L.Index(db)
    W, w_isbn = wiki_lines(db)
    lines, stats, lost = build(recs, parents, idx, W, w_isbn)
    fates = load(db, lines, lost, W, w_isbn)
    moved, orphans = redirects(db, carry)
    os.makedirs(BUILD, exist_ok=True)
    n_review = review_file(lines, idx, os.path.join(BUILD, "dnb-review.tsv"))

    roles = collections.Counter(ln["role"] for ln in lines)
    tiers = collections.Counter(ln["tier"] for ln in lines)
    exp_tiers = collections.Counter(ln["tier"] for ln in lines if ln["role"] == "linked")
    gt = [ln for ln in lines if ln["truth_work"]]
    gt_linked = [ln for ln in gt if ln["tier"] in ("high", "medium")]
    gt_wrong = [ln for ln in gt_linked if ln["link_work"] != ln["truth_work"]]
    stats.update(tally=tally, roles=dict(roles), tiers=dict(tiers), exported_tiers=dict(exp_tiers),
                 volume_fates=dict(fates), review_lines=n_review, redirects=moved,
                 orphaned_ids=orphans,
                 ground_truth={"lines": len(gt), "linked": len(gt_linked), "wrong": len(gt_wrong),
                               "wrong_lines": [ln["name"] for ln in gt_wrong]})
    db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('dnb:stats',?)", (json.dumps(stats),))
    db.commit()
    with open(os.path.join(BUILD, "dnb-report.json"), "w", encoding="utf8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=1)

    print("  records %s (+%d parents fetched), kept %d -> %d volumes (%d twin records merged, "
          "%d box-set ISBNs)" % (format(len(recs), ","), tally.get("parents_fetched", 0),
                                 stats["kept_records"], stats["volume_groups"],
                                 stats["twin_records_merged"], stats["boxset_isbns"]))
    print("  dropped: %s" % ", ".join("%s %d" % kv for kv in stats["dropped"].items()))
    print("  lines %d: %s" % (len(lines), ", ".join("%s %d" % kv for kv in sorted(roles.items()))))
    print("  linker tiers (all lines): %s" % ", ".join("%s %d" % kv for kv in sorted(tiers.items())))
    print("  volume fates: %s" % ", ".join("%s %d" % kv for kv in sorted(fates.items())))
    print("  ground truth (Wikipedia lines, no ISBNs used): %d lines, %d linked, %d wrong %s" % (
        len(gt), len(gt_linked), len(gt_wrong), [ln["name"] for ln in gt_wrong]))
    print("  review file: %d lines -> build/dnb-review.tsv" % n_review)
    print("  id redirects from the carried artifact: %d%s" % (
        moved, ("; NO SUCCESSOR for %d: %s" % (len(orphans), orphans[:5])) if orphans else ""))
    print("  live DNB requests this run: %d" % S.live_requests[0])
    return stats


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else os.path.join(BUILD, "opentome.db"),
        sys.argv[2] if len(sys.argv) > 2 else None)
