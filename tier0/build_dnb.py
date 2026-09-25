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
    role TEXT NOT NULL,                     -- merged | sibling | linked | kept | review | unlinked
                                            -- | out_of_scope (a Korean/Chinese work) | absorbed
    wiki_line TEXT, truth_work TEXT,        -- merged / sibling: the Wikipedia line and its work
    exported INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS dnb_member (     -- one row per DNB volume record kept
    idn TEXT PRIMARY KEY, line_key TEXT, number TEXT, isbn13 TEXT,
    volume_id TEXT,                         -- NULL when the volume did not reach `volume`
    fate TEXT NOT NULL,                     -- created | attached | held_future | dropped_* | line_*
    filled TEXT,                            -- attached: the empty Wikipedia columns it filled (JSON)
    announced_only INTEGER);                -- 1 when no record of its volume was deposited yet
"""


def url(idn):
    return "https://d-nb.info/" + idn


def idn_key(i):
    """IDNs are digit strings with an optional X check character; compare as numbers."""
    return (len(i), i)


# One German manga publisher under successive names -- a series keeps its numbering across a
# rebrand, so its line must too. VIZ Media Switzerland SA published as KAZÉ Manga, which became
# Crunchyroll Manga, whose list moved to Pegasus Manga (2026-09-24 review: 49 works split into
# consecutive-number lines, 33 of them along this chain); Planet Manga is Panini's imprint.
PUBLISHER_FAMILY = {"vizmed": "kaze", "crunch": "kaze", "pegasu": "kaze", "planet": "panini"}


def pubkey(p):
    k = L.fold(re.sub(r"(?i)\b(gmbh|verlag\w*|verl\.?-?ges\.?|verlagsgesellschaften|mbh|manga!?|sa|ag)\b",
                      "", p or ""), False)[:6]
    return PUBLISHER_FAMILY.get(k, k)


# ---- 2. select --------------------------------------------------------------------

def select(recs, parents=None):
    """-> (kept volume dicts, Counter of drop reasons). A volume of a boxed set (the parent
    is a box: 'Behältnis', 'Kassette', 'Schuber', a bundle title) with no ISBN of its own is
    part of the box, not a volume, in v1; one with its own ISBN is a book, but the box never
    becomes its line."""
    boxes = {k for k, p in (parents or {}).items() if M.box_parent(p)}
    kept, drop = [], collections.Counter()
    for r in recs.values():
        if M.is_parent(r):
            continue
        in_box = bool(boxes & set(M.parent_idns(r)))
        if in_box and not M.isbns(r):
            drop["in_boxed_set"] += 1          # a volume of a box with no ISBN of its own
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
                     # a box never keys a line: a book that was also sold in a box (its own
                     # ISBN) clusters by its series / title instead
                     "parent": None if in_box else (M.parent_idns(r) or [None])[0]})
    return kept, drop


# ---- 3. volumes (ISBN twins) ----------------------------------------------------------

def _tkey(v):
    return L.fold(M.bare_title(v["r"]), False)


def twins(vols):
    """-> (groups, dropped ISBNs). A group is one physical volume: records joined by a
    shared ISBN that is not a box-set ISBN (on records with different volume numbers) and
    not a collision (on records sharing neither parent nor folded title)."""
    by_isbn = collections.defaultdict(list)
    for v in vols:
        for i in v["isbns"]:
            by_isbn[i].append(v)
    boxset = {i for i, vs in by_isbn.items() if len({v["num"] for v in vs if v["num"]}) > 1}
    # an ISBN on records of two DIFFERENT sets (both have a 773, not the same one) whose folded
    # titles differ too is a cataloguing collision, not one book -- it joins nothing and is
    # dropped from both. A set-less record twinning a set member stays a twin: DNB re-catalogues
    # One Piece volumes under their chapter title ("Gear") with no 773, same ISBN, same number.
    boxset |= {i for i, vs in by_isbn.items()
               if any(v["parent"] and vs[0]["parent"] and v["parent"] != vs[0]["parent"]
                      and _tkey(v) != _tkey(vs[0]) for v in vs[1:])}
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
    # A planned month more than PROJECTED_MAX_AGE months past on a record DNB never received
    # (legal deposit lags a median 120 days, p90 293) is no longer a plan -- most likely a
    # cancellation or a changed ISBN. The volume stays; its date is dropped, never shipped as
    # if it had happened.
    if planned and _months_ago(planned) > PROJECTED_MAX_AGE:
        return None
    return (planned, "month", "projected") if planned else None


PROJECTED_MAX_AGE = 12          # months


def _months_ago(ym):
    t = datetime.date.today()
    return (t.year - int(ym[:4])) * 12 + t.month - int(ym[5:7])


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


def _numbers(gs):
    return {g["num"] for g in gs if g["num"]}


def cluster(groups, parents):
    """-> {line key: [groups]}. Raw clusters (parent set / series statement / bare title) that
    share a signature -- folded name, publisher family, medium, edition marker -- are one line:
      * series- and title-keyed clusters of one signature merge ("Black Clover 37" announced
        with no series statement joins "Black Clover" with one);
      * parent sets of one signature merge while their volume numbers stay disjoint (a new
        set record per publisher name: KAZÉ 1-26, Crunchyroll 27-30, Pegasus 31-32); a set
        that repeats the numbers is another edition and stays apart;
      * the series/title cluster then folds into the parent line when exactly one is left.
    A light novel and its manga adaptation often share a title and a publisher -- medium is
    part of the signature."""
    raw = collections.defaultdict(list)
    for g in groups:
        raw[raw_key(g)].append(g)
    by_sig = collections.defaultdict(lambda: {"parents": [], "loose": []})
    for k, gs in raw.items():
        media = collections.Counter(g["medium"] for g in gs)
        medium = "light_novel" if media["light_novel"] > media["manga"] else "manga"
        if k.startswith("parent:"):
            p = parents.get(k[7:])
            if p is None:
                by_sig[k]["parents"].append((k, gs))          # an unknown set: on its own
                continue
            pubs = collections.Counter(g["publisher"] for g in gs if g["publisher"])
            pub = M.publisher(p) or (pubs.most_common(1)[0][0] if pubs else None)
            sig = (L.fold(M.clean(M.first(p, "245", "a")), False), pubkey(pub), medium, M.edition_marker(p) or "")
            by_sig[sig]["parents"].append((k, gs))
        elif k.startswith(("series:", "title:")):
            by_sig[tuple(k.split(":", 1)[1].split("|"))]["loose"].append((k, gs))
        else:
            by_sig[k]["loose"].append((k, gs))
    out = {}

    def emit(gs, parent_ids):
        key = "dnb:" + (min(parent_ids, key=idn_key) if parent_ids else
                        min((i for g in gs for i in g["idns"]), key=idn_key))
        out[key] = gs
    for sig, d in by_sig.items():
        merged = []                      # [(parent ids, groups)], sets merged while disjoint
        for k, gs in sorted(d["parents"], key=lambda kg: idn_key(kg[0][7:])):
            for m in merged:
                a, b = _numbers(m[1]), _numbers(gs)
                # disjoint, or one shared number (a transitional volume both catalogued) between
                # sets of 3+ volumes; a small set repeating a number is another edition
                if not a & b or (len(a & b) == 1 and min(len(a), len(b)) >= 3):
                    m[0].append(k[7:])
                    m[1].extend(gs)
                    break
            else:
                merged.append(([k[7:]], list(gs)))
        loose = [g for _, gs in d["loose"] for g in gs]
        if loose and len(merged) == 1:
            merged[0][1].extend(loose)
            loose = []
        for pids, gs in merged:
            emit(gs, pids)
        if loose:
            emit(loose, [])
    return out


def shape_line(key, gs, parents):
    """Number the line's volumes: one group per number (the deposited, lowest-IDN record
    wins), an unnumbered group is volume 1 of a one-volume line and dropped otherwise.
    -> (line dict, [(group, fate)] for the groups that did not make it)"""
    out, lost, seen = [], [], set()
    # the regular edition beats a limited / special one; a deposited volume an announcement;
    # a volume with its own ISBN one without; then the first catalogued (a later record of
    # the same number is usually a reprint)
    gs = sorted(gs, key=lambda g: (g["date"] is not None and g["date"][0] == "HELD",
                                   all(v["ann"] for v in g["members"]), g["edition"] is not None,
                                   not g["isbns"], idn_key(g["primary"])))
    for g in gs:
        num = g["num"]
        if num is None:
            # only a real one-shot is volume 1: no set, no series, no digit in its title (a
            # digit there is a number the parser could not place, or a bundle)
            r = g["members"][0]["r"]
            if len(gs) == 1 and not g["parent"] and not g["series"] and \
                    not re.search(r"\d", M.clean(M.first(r, "245", "a"))):
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
    # a volume's original title (240) names the SERIES in a normal set ("Kawaii Koi wa
    # Kikazaranai 1", "... 2") but the PART in an anthology set (Toriyama short stories: one
    # volume 240 'Kajika', the next 'Cowa!'): a volume's original title counts only when at
    # least half the line's volumes carry the same folded title
    vol_orig = collections.Counter()
    for g in out:
        vol_orig.update({L.fold(t) for v in g["members"] for t in M.original_titles(v["r"])})
    for r in recs:
        o = M.original_titles(r)
        if r is not p:
            o = [t for t in o if 2 * vol_orig[L.fold(t)] >= len(out)]
        orig += o
        titles += o
        # the title proper is a line title only on the parent or on a volume that belongs to
        # no set and no numbered series; otherwise it can be a PART title ("Ocarina of time"
        # inside The Legend of Zelda, "From the sea" inside Fire Force)
        a = M.clean(M.first(r, "245", "a"))
        if a and (r is p or not (M.parent_idns(r) or M.series_statements(r))):
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

def build(recs, parents, idx, W, w_isbn, carried=None):
    """-> (lines, stats, lost [(group, fate, line key)]). carried: {tome_id: work_id} of the
    German lines in the last published artifact -- a line that shipped there keeps shipping
    (role 'kept', under its published work) when only the linker's answer changed: ids are a
    public contract, and a consumer may already store it."""
    allparents = dict(parents)
    allparents.update({k: r for k, r in recs.items() if M.is_parent(r)})
    vols, drop = select(recs, allparents)
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
            if ln["role"] == "linked" and ln["work"] in idx.non_japanese:
                ln["role"], ln["work"] = "out_of_scope", None      # Korean / Chinese origin: next round
            if ln["role"] != "linked" and (carried or {}).get(ln["rl_id"]) in idx.name:
                ln["role"], ln["work"] = "kept", carried[ln["rl_id"]]
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
    c.executescript("DROP TABLE dnb_line; DROP TABLE dnb_member;" + STAGING_DDL)
    st = collections.Counter()
    for ln in lines:
        exported = ln["role"] in ("merged", "sibling", "linked", "kept")
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
            ann = int(all(v["ann"] for v in g["members"]))
            for m in g["members"]:
                c.execute("INSERT OR REPLACE INTO dnb_member VALUES(?,?,?,?,?,?,?,?)",
                          (m["idn"], ln["key"], g["number"], g["isbn"], vid, fate, filled, ann))
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
            c.execute("INSERT OR REPLACE INTO dnb_member VALUES(?,?,?,?,NULL,?,NULL,?)",
                      (m["idn"], key, g["num"], g["isbn"], fate, int(all(v["ann"] for v in g["members"]))))
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

def carried_lines(carry):
    """{tome_id: work_id} of the German lines in the carried (last published) artifact."""
    if not carry or not os.path.exists(carry):
        return {}
    try:
        return dict(sqlite3.connect(carry).execute(
            "SELECT tome_id, tome_work_id FROM series WHERE language='de' AND tome_id IS NOT NULL"))
    except sqlite3.OperationalError:
        return {}


def redirects(db, carry):
    """Retired ids resolve forever (docs/id-scheme.md). From the carried artifact:
      1. its own id_redirect rows are re-read, so a redirect survives every later build;
      2. a German line id it has that this build does not is redirected to the German line
         now holding most of its ISBNs, else to the same work's main German line ('retired');
      3. each of its volumes that is gone follows by ISBN, else by number in the successor
         line, else to the successor LINE itself ('retired': the volume is no longer in the
         catalogue, the id still resolves to where it belonged).
    -> (lines redirected, lines with no successor)."""
    if not carry or not os.path.exists(carry):
        return 0, []
    A = sqlite3.connect(carry)
    try:
        for row in A.execute("SELECT old_tome_id, new_tome_id, entity, reason FROM id_redirect"):
            db.execute("INSERT OR IGNORE INTO id_redirect VALUES(?,?,?,?,?)", row + (NOW,))
    except sqlite3.OperationalError:
        pass                                  # an artifact from before id_redirect was exported
    try:
        old = A.execute("""SELECT s.tome_id, s.tome_work_id, v.volume_number, v.tome_id, v.isbn13 FROM series s
                           LEFT JOIN volumes v USING(gcd_series_id) WHERE s.language='de'""").fetchall()
    except sqlite3.OperationalError:
        return 0, []
    now = {r[0] for r in db.execute("SELECT id FROM release_line WHERE market='DE'")}
    vol_now = {r[0] for r in db.execute("""SELECT v.id FROM volume v JOIN release_line rl
                                           ON rl.id=v.release_line_id WHERE rl.market='DE'""")}
    isbn_to = {i: (rid, vid) for vid, rid, i in db.execute(
        """SELECT v.id, v.release_line_id, v.isbn13 FROM volume v JOIN release_line rl
           ON rl.id=v.release_line_id WHERE rl.market='DE' AND v.isbn13 IS NOT NULL""")}
    main_de = {}
    for rid, wid in db.execute("""SELECT rl.id, rl.work_id FROM release_line rl WHERE rl.market='DE'
                                  ORDER BY (SELECT COUNT(*) FROM volume v WHERE v.release_line_id=rl.id) DESC, rl.id"""):
        main_de.setdefault(wid, rid)
    redirected = {r[0] for r in db.execute("SELECT old_id FROM id_redirect")}
    by_old, work_of = collections.defaultdict(list), {}
    for tid, wid, num, vtid, isbn in old:
        work_of[tid] = wid
        if vtid:
            by_old[tid].append((num, vtid, isbn))
    moved, orphans = 0, []

    def put(old_id, new_id, entity, reason):
        if old_id != new_id and old_id not in redirected:
            db.execute("INSERT OR IGNORE INTO id_redirect VALUES(?,?,?,?,?)", (old_id, new_id, entity, reason, NOW))
            redirected.add(old_id)
    for tid in work_of:
        line = tid
        if tid not in now and tid not in redirected:
            votes = collections.Counter(isbn_to[i][0] for _, _, i in by_old[tid] if i in isbn_to)
            if votes:
                line = votes.most_common(1)[0][0]
                put(tid, line, "release_line", "correction")
            elif work_of[tid] in main_de:
                line = main_de[work_of[tid]]
                put(tid, line, "release_line", "retired")
            else:
                orphans.append(tid)
                continue
            moved += 1
        elif tid in redirected:
            line = next(r[0] for r in db.execute("SELECT new_id FROM id_redirect WHERE old_id=?", (tid,)))
        for num, vtid, isbn in by_old[tid]:
            if vtid in vol_now or vtid in redirected:
                continue
            nv = (isbn_to.get(isbn) or (None, None))[1] or next(
                (r[0] for r in db.execute("SELECT id FROM volume WHERE release_line_id=? AND number=?",
                                          (line, str(num)))), None)
            put(vtid, nv or line, "volume", "correction" if nv else "retired")
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
    degraded = tally.get("degraded")
    if gaps and not degraded:
        raise SystemExit("DNB enumeration incomplete -- year slices miss records: %s" % gaps)
    # A degraded refresh (DNB failed; every affected slice kept its previous COMPLETE page set)
    # is built and gated like any other, and recorded: meta 'dnb:degraded' reaches the artifact
    # as meta.dnb_degraded, and export/publish.sh refuses to publish it.
    db.execute("DELETE FROM meta WHERE key='dnb:degraded'")
    if degraded:
        db.execute("INSERT INTO meta(key,value) VALUES('dnb:degraded',?)", (json.dumps(
            {"reason": degraded, "kept_previous": tally.get("degraded_queries", []), "gaps": gaps}),))
        print("  WARNING DNB refresh degraded (%s): %d result set(s) kept their previous complete page "
              "set; gaps %s -- this build will not publish" % (degraded, len(tally.get("degraded_queries", [])), gaps),
              flush=True)
    db.commit()
    # a rerun on a populated catalogue first takes back what the last run wrote, so the
    # Wikipedia side and the linker's index are read exactly as the first run read them
    db.executescript(STAGING_DDL)
    unload(db.cursor())
    db.commit()
    idx = L.Index(db)
    W, w_isbn = wiki_lines(db)
    lines, stats, lost = build(recs, parents, idx, W, w_isbn, carried_lines(carry))
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
