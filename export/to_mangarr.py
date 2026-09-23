"""Export OpenTome -> a Mangarr-shaped artifact (drop-in for manga-metadata.sqlite).

Mangarr's `series` table is already one row per RELEASE LINE, which is the same
model OpenTome converged on independently, so the mapping is close to direct:

    opentome.release_line  ->  series
    opentome.volume        ->  volumes
    opentome.work_title    ->  series_alias      (localized-title matching)
    opentome.composition   ->  volumes.composition   (contains='volume' ONLY)

Two constraints come from the C# models, not from SQLite:

  * GcdSeries.GcdSeriesId is `int`  -> series ids must be stable INTEGERS.
    They are hash-derived and recorded in `id_map`, so a rebuild reuses existing
    ids and only new lines get new ones. Sequential numbering was rejected: it
    renumbers everything after an insertion, which the ID contract forbids.

  * GcdVolume.VolumeNumber is `int` -> fractional (7.5) and label volumes
    (SP, Ex3, Side Story) cannot be represented. They are NOT dropped silently:
    they go to `volumes_special`, which today's C# ignores and a later version
    can read, and the count is written to `meta`.

Three lessons from the first export, each measured against the live library
(docs/cleanup-v2.md):

  * `composition` means "the ORIGINAL volumes this volume contains" to the C#
    (an omnibus list). The first export wrote CHAPTER lists into it, which
    flagged every well-documented main line as an omnibus and made Mangarr
    prefer spin-offs over main lines (Attack on Titan -> "Before the Fall").
    Chapters now go to their own column; composition carries volumes only.
  * Work-level titles were attached as aliases to EVERY line of the work, so
    "Attack on Titan" answered 43 series. Only a work's MAIN line per market
    carries the work's titles; sub-lines carry their own name.
  * Year- and month-precision dates were emitted as bare '2019' / '2019-04',
    which .NET parses as 1 January / 1 April. Only day-precision dates are
    emitted as `release_date`; the coarse value and its precision travel in
    separate columns the C# can adopt later.
"""
import collections, hashlib, json, os, re, sqlite3, sys, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tier0"))
sys.path.insert(0, os.path.join(ROOT, "tier2"))
from build_corpus import work_title
from release_lines import GENERIC
from corrections import load_aliases
from line_status import line_status


def _build(name):
    """Default build-output path. Never /tmp: macOS cleaned it and destroyed a
    fully-built catalogue. Outputs belong beside the cache, inside the repo."""
    d = os.path.join(ROOT, "build")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, name)


NOW = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
TODAY = datetime.date.fromisoformat(NOW[:10])
# A volume title that only repeats the number says nothing the number does not.
NUMBER_ONLY_TITLE = re.compile(r"^\s*(?:vol(?:ume)?\.?\s*|tome\s*|band\s*)?\d+\s*$", re.I)
# Unstripped wiki/HTML syntax that never belonged in a title in the first place. A
# lone '<' or '>' is left alone -- both Japanese titles ('新たな恋敵<ライバル>',
# '境界線上のホライゾンI<上>') and English ones ('1933 <First> The Slash') legitimately
# use them; only a real tag (an opener the pipeline knows, or ANY closer) is markup.
MARKUP_TITLE_RE = re.compile(r"\{\{|\}\}|\[\[|\]\]|<ref|<br|<!--|<ruby|</", re.I)
# Kana, CJK ideographs, hangul -- the scripts a non-origin-market reader cannot use.
NATIVE_SCRIPT_RE = re.compile(r"[぀-ヿ㐀-鿿가-힯]")
# series_name, optionally followed by a bracketed qualifier ("(Light Novel)" --
# 2026-09-23 follow-up: "Mushoku Tensei: Jobless Reincarnation (Light Novel) Vol.
# 14" survived this check because nothing sat between the name and the separator),
# a separator (punctuation or plain whitespace), an optional vol/tome/band word,
# and a volume number -- i.e. nothing the row's own volume_number column doesn't
# already say.
_REDUNDANT_SUFFIX = r"(?:\s*\([^)]*\))?(?:\s*[:\-–,])?\s*(?:(?:vol(?:ume)?\.?|tome|band)\s*)?\d+"
# The English wiki's LicensedTitle often carries the series name and volume number
# AHEAD OF the real subtitle ("Sword Art Online 1: Aincrad", "Sword Art Online, Vol.
# 1: Aincrad") -- Task 7's spot check. Strip that lead-in so what's left is just the
# subtitle; a final separator + whitespace + non-empty remainder is required, so a
# title that is ONLY the series name and number (no subtitle after it) is left alone
# here and falls through to the redundant-suffix check below instead.
_PREFIX_LEAD_IN = r"[\s:,\-–—]*(?:(?:vol(?:ume)?\.?|tome|band)\s*)?\d+\s*[:\-–—]\s+(.+)$"


def _collapse_ws(s):
    return re.sub(r"\s+", " ", (s or "").strip())


def title_for_export(title, series_name, native_script_ok, drops=None, trusted=False):
    """The title to bind to an exported volume, or None when it is noise: absent,
    unparsed wiki markup, a script this market's readers cannot use, or a restatement
    of the series name and volume number the row's own columns already carry. `drops`
    (a Counter), when given, is incremented with the reason a title was rejected.
    Per-market title selection is a tier-0 concern -- this only filters what tier-0
    already produced for THIS line's market.
    `trusted` marks a hand-checked correction (corrections/*.json -> override): it keeps
    the hygiene rejects (markup, number-only -- the gate enforces those on every row) but
    skips the lossy transforms (wrong-script, prefix strip, redundant), so a corrected
    title round-trips to the artifact exactly as written."""
    def drop(reason):
        if drops is not None:
            drops[reason] += 1
        return None
    if not title:
        return None
    if NUMBER_ONLY_TITLE.match(title):
        return drop("number_only")
    if MARKUP_TITLE_RE.search(title):
        return drop("markup")
    if trusted:
        return title
    if not native_script_ok and NATIVE_SCRIPT_RE.search(title):
        return drop("wrong_script")
    name = _collapse_ws(series_name)
    if name:
        m = re.match(r"^" + re.escape(name) + _PREFIX_LEAD_IN, _collapse_ws(title), re.I)
        if m:
            title = m.group(1)
            if drops is not None:
                drops["prefix-stripped"] += 1
            if NUMBER_ONLY_TITLE.match(title):
                return drop("number_only")      # "Series 5: 1" -> "1" says nothing either
    if name and re.match(r"^" + re.escape(name) + r"(?:" + _REDUNDANT_SUFFIX + r")?$",
                          _collapse_ws(title), re.I):
        return drop("redundant")
    return title


MARKET_LANG = {"JP": "ja", "EN": "en", "FR": "fr", "DE": "de", "KR": "ko",
               "IT": "it", "ES": "es", "BR": "pt-BR", "CN": "zh", "TW": "zh-TW",
               "HK": "zh-HK"}

# Module level (2026-09-23 follow-up) so pick_origin is independently testable and
# a corrections-driven medium override (tier2/corrections.py) can be exercised
# without a database: originally a closure inside export(), which meant the only
# way to test it was a full export run.
ORIGIN = ("JP", "KR", "CN", "TW")
# A medium hint decides the origin market before falling back to the fixed
# JP>KR>CN>TW order: that fixed order picked JP as the origin for a Korean manhwa
# that ALSO has a Japanese edition (Saver, Warlord) and for Denma (a manga) --
# their KO line then pointed at its own JA translation as "the origin" and
# inherited a licensed-line status backwards (Warlord read 'stalled'). See
# pick_origin() below.
MEDIUM_ORIGIN_HINT = {"manhwa": ("KR",), "webtoon": ("KR",), "manhua": ("CN", "TW")}


def pick_origin(medium, markets, first_dated_by_market):
    """The market a work's ORIGINAL edition is in, for one (work, medium):
    1. a medium hint (manhwa/webtoon -> KR; manhua -> CN, then TW) -- these two
       are unconditional: a Korean/Chinese label on the medium itself is a
       stronger signal than any recorded date;
    2. otherwise (medium has no hint, e.g. plain 'manga' -- 'prefer JP' falls out
       of this step on its own, since JP is what usually shipped first) the
       ORIGIN candidate whose main line's first dated volume is earliest;
    3. the old fixed JP>KR>CN>TW order, when no candidate has a usable date.
    Step 2, not a hard JP default, is why: Saver and Warlord (both manhwa) are
    caught by step 1, but Denma is tagged plain 'manga' upstream, so it depends on
    step 2 -- and even there its JP line's first PRINT date (2008/2010) predates
    its KR line's first PRINT date (2015, a late collected edition; the original
    web serialization has no volume-level date in this data), so Denma's ko line
    still resolves to a ja origin -- UNLESS a corrections/lines.json medium
    override (tier2/corrections.py) has retagged its lines 'manhwa', which routes
    it through step 1 instead. Flagged, not hidden: hard-coding one title's id
    here would be exactly the kind of un-generalizable special case this
    pipeline avoids -- see the fix-round-2 report."""
    for m in MEDIUM_ORIGIN_HINT.get(medium, ()):
        if m in markets:
            return m
    dated = [(d, m) for m in ORIGIN if m in markets
             for d in [first_dated_by_market.get(m)] if d]
    if dated:
        # A tie on date falls back to the documented JP>KR>CN>TW order, not an
        # alphabetical one ("CN" < "JP" would otherwise win the tie wrongly).
        return min(dated, key=lambda dm: (dm[0], ORIGIN.index(dm[1])))[1]
    return next((m for m in ORIGIN if m in markets), None)


def normalize(value):
    """Byte-for-byte mirror of GcdMetadataService.Normalize() in the C#:
    lowercase, collapse every run of non-[a-z0-9] to a single space, trim.

    Mangarr queries `series_alias WHERE alias = @n` with the NORMALIZED form of
    a folder name. Storing only raw titles meant those queries never hit, which
    is why the first export matched fewer series than the hand-curated artifact
    it was meant to replace -- despite holding far more data."""
    out, pending = [], False
    for ch in (value or "").lower():
        if ch.isalnum() and ord(ch) < 128:
            if pending and out:
                out.append(" ")
            pending = False
            out.append(ch)
        else:
            pending = True
    return "".join(out).strip()


def heads(title):
    """Subtitle-stripped forms: 'Frieren: Beyond Journey's End' -> 'Frieren'."""
    t = (title or "").strip()
    out = []
    for sep in (":", " -", " –", ","):
        if sep in t:
            head = t.split(sep)[0].strip()
            if len(head) > 2:
                out.append(head)
    return out


def variants(title, with_heads=True):
    """Alias forms a real folder name might take. Deterministic order: the
    old set-based version flipped case forms between runs with the hash seed
    and produced thousands of spurious artifact diffs."""
    t = (title or "").strip()
    if not t:
        return []
    out = {t, normalize(t)}
    if with_heads:
        for head in heads(t):
            out.add(head)
            out.add(normalize(head))
    return sorted(x for x in out if x)


SCHEMA = """
PRAGMA user_version = 2;
CREATE TABLE IF NOT EXISTS series (
    gcd_series_id INTEGER PRIMARY KEY, name TEXT NOT NULL, year_began INTEGER,
    publisher TEXT, language TEXT, country TEXT,
    is_omnibus INTEGER NOT NULL DEFAULT 0, volume_count INTEGER NOT NULL DEFAULT 0,
    status TEXT, orig_series_id INTEGER,
    anilist_id INTEGER, mangaupdates_id INTEGER, mangadex_id TEXT,
    -- OpenTome additions (ignored by a C# that names its columns explicitly)
    medium TEXT,                 -- manga | light_novel | manhwa | novel | ...
    dated_count INTEGER NOT NULL DEFAULT 0,   -- integer volumes with a day-precision date
    is_main INTEGER NOT NULL DEFAULT 0,       -- the work's main line for this market
    tome_id TEXT,                -- OpenTome release-line id  (public contract)
    tome_work_id TEXT,           -- OpenTome work id
    parent_series_id INTEGER,    -- the series this arc / spin-off line belongs to (collections)
    author TEXT);                -- the work's author, first name of the tier-0 claim (2026-09-20)
CREATE TABLE IF NOT EXISTS volumes (
    id INTEGER PRIMARY KEY, gcd_series_id INTEGER NOT NULL REFERENCES series(gcd_series_id),
    volume_number INTEGER NOT NULL, title TEXT, release_date TEXT,
    isbn13 TEXT, isbn10 TEXT, page_count INTEGER, composition TEXT,
    release_date_precision TEXT, release_date_raw TEXT, volume_chapters TEXT,
    tome_id TEXT,
    cover_url TEXT, cover_source TEXT,      -- looked up by THIS edition's ISBN; never hosted
    UNIQUE (gcd_series_id, volume_number));
CREATE TABLE IF NOT EXISTS series_alias (
    gcd_series_id INTEGER NOT NULL REFERENCES series(gcd_series_id),
    alias TEXT NOT NULL, UNIQUE (gcd_series_id, alias));
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
-- Not read by the current C#. Preserves volumes whose number is not an int, so
-- nothing is lost silently; a later Mangarr can promote these.
CREATE TABLE IF NOT EXISTS volumes_special (
    gcd_series_id INTEGER NOT NULL, volume_label TEXT NOT NULL, title TEXT,
    release_date TEXT, isbn13 TEXT, page_count INTEGER, composition TEXT,
    UNIQUE (gcd_series_id, volume_label));
-- OpenTome text id <-> Mangarr integer id. Carried across rebuilds so ids never churn.
CREATE TABLE IF NOT EXISTS id_map (
    opentome_id TEXT PRIMARY KEY, int_id INTEGER UNIQUE NOT NULL, kind TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_series_name    ON series (name);
CREATE INDEX IF NOT EXISTS idx_volumes_series ON volumes (gcd_series_id);
CREATE INDEX IF NOT EXISTS idx_alias_alias    ON series_alias (alias);
-- The C# compares COLLATE NOCASE, which a BINARY index cannot serve.
CREATE INDEX IF NOT EXISTS idx_series_name_nc ON series (name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_alias_alias_nc ON series_alias (alias COLLATE NOCASE);
"""


def stable_int(text_id, taken):
    """Deterministic positive int32 from an OpenTome id, probing on collision."""
    for salt in range(64):
        h = hashlib.sha256((text_id + ("#%d" % salt if salt else "")).encode()).digest()
        n = int.from_bytes(h[:4], "big") & 0x7FFFFFFF
        if n and n not in taken:
            return n
    raise RuntimeError("could not allocate id for " + text_id)


_TEMPLATE = re.compile(r"\{\{[^{}]*\}\}")


def _first_author(value):
    """The first name of a work's author claim -- a JSON list of names
    (tier0/main_articles.py), else the raw string. tier-0's one-pass template
    strip leaves the OUTER of two nested templates behind ('Kentaro Miura
    ({{nowrap| 1-41}})'); it goes here, with the empty '()' it leaves. A
    qualifier that still says something ('Jitakukeibihei (Natsume Akatsuki)')
    is kept as is, and an entry that is ONLY a qualifier ('(1994-1998)') is
    not a name."""
    try:
        names = json.loads(value)
    except (TypeError, ValueError):
        names = None
    if not isinstance(names, list):
        names = [value]
    for n in names:
        n = str(n or "")
        while _TEMPLATE.search(n):
            n = _TEMPLATE.sub("", n)
        n = re.sub(r"\s*\(\s*\)", "", n)
        n = re.sub(r"\s+", " ", n).strip()
        if re.sub(r"\([^)]*\)", "", n).strip():
            return n
    return None


def _line_raw(lname, wtitle):
    """'Re:Zero (Truth of Zero)' -> 'Truth of Zero'; self-named lines unchanged."""
    if not lname:
        return None
    m = re.match(r"^(.*)\s\((.+)\)$", lname)
    if m and normalize(m.group(1)) == normalize(wtitle):
        return m.group(2).strip()
    return lname


def export(src_path, out_path, carry_ids_from=None):
    src = sqlite3.connect(src_path, timeout=60)
    if os.path.exists(out_path):
        os.remove(out_path)
    out = sqlite3.connect(out_path)
    out.executescript(SCHEMA)

    # reuse existing id assignments if a prior artifact is supplied
    mapping, taken, prev_status = {}, set(), {}
    if carry_ids_from and os.path.exists(carry_ids_from):
        old = sqlite3.connect(carry_ids_from)
        try:
            for t, i, k in old.execute("SELECT opentome_id,int_id,kind FROM id_map"):
                mapping[t] = i
                taken.add(i)
        except sqlite3.OperationalError:
            pass
        try:
            prev_status = dict(old.execute("SELECT tome_id, status FROM series"))
        except sqlite3.OperationalError:
            pass

    # resolved page counts (BnF / Open Library) -- tier0 never fills volume.page_count
    pages = {}
    for vid, val in src.execute("""SELECT entity_id, value FROM resolution
                                   WHERE entity='volume' AND field='page_count'"""):
        try:
            n = int(float(val))
            if 20 <= n <= 2000:
                pages[vid] = n
        except (TypeError, ValueError):
            pass

    # Hand-checked title corrections (tier2/corrections.py writes an override row): the
    # export keeps them verbatim so the contract rule "volume corrections present in the
    # artifact" can hold -- see title_for_export(trusted=...).
    trusted_titles = {vid for (vid,) in src.execute(
        "SELECT entity_id FROM override WHERE entity='volume' AND field='title'")}

    # ISBN-keyed cover URLs (tier1/covers.py). One volume has one ISBN, so at most
    # one claim per source; prefer the source native to the volume's market.
    covers = {}
    for vid, url, source in src.execute("""SELECT entity_id, value, source FROM claim
                                           WHERE entity='volume' AND field='cover_url'"""):
        covers.setdefault(vid, {})[source] = url

    # Work-level facts from the main article (tier0/main_articles.py): status and
    # first year. Mangarr's MapGcdStatus reads completed|ongoing.
    work_facts = {wid: (status, year) for wid, status, year in src.execute(
        "SELECT id, status, year_started FROM work")}
    # The work's author (the main article's infobox `author`, a JSON list of
    # names): every line of the work carries the first one. Mangarr reads it as
    # the series' author; a pin there overrides it.
    work_authors = {}
    for wid, val in src.execute("""SELECT entity_id, value FROM claim
                                   WHERE entity='work' AND field='author'"""):
        name = _first_author(val)
        if name:
            work_authors[wid] = name

    lines = src.execute("""
        SELECT rl.id, rl.work_id, rl.market, rl.medium, rl.publisher, rl.status, rl.parent_id,
               w.primary_title,
               (SELECT value FROM claim WHERE entity='release_line'
                  AND entity_id=rl.id AND field='line_name') AS line_name
        FROM release_line rl JOIN work w ON w.id=rl.work_id
        ORDER BY rl.id""").fetchall()

    # Every work's normalized title, so a subtitle head that IS another work's
    # title ('Attack on Titan: Before the Fall' -> 'Attack on Titan') is never
    # attached as an alias to the wrong work.
    other_titles = {}
    for wid, t in src.execute("SELECT id, primary_title FROM work"):
        other_titles.setdefault(normalize(t), set()).add(wid)

    # main line per (work, market, medium): the line named after the work, else
    # the biggest. Only main lines carry the work-level aliases.
    by_group = {}
    for rid, wid, market, medium, *_rest, wtitle, lname in lines:
        n = src.execute("SELECT COUNT(*) FROM volume WHERE release_line_id=?", (rid,)).fetchone()[0]
        named = (not lname) or normalize(lname) == normalize(wtitle)
        by_group.setdefault((wid, market, medium), []).append((not named, -n, rid))
    main_of = {k: sorted(v)[0][2] for k, v in by_group.items()}

    # For the status rule: a licensed line's counterpart in the work's original
    # market -- the same-named line there, else that market's main line -- and
    # every line's highest plain-integer volume number. Highest number, not
    # count: an arc line keeps Wikipedia's continuous numbering (34-36) and a
    # table with gaps still reaches its last volume.
    # ORIGIN, MEDIUM_ORIGIN_HINT and pick_origin() are module-level (above).
    markets_of, line_key = {}, {}
    for rid, wid, market, medium, *_rest, wtitle, lname in lines:
        markets_of.setdefault((wid, medium), set()).add(market)
        # exact name, not normalize(): "Kageki Shojo!!" must not resolve to its
        # prequel "Kageki Shojo!", nor "Mechanical Marie" to "Mechanical Marie+"
        line_key[(wid, medium, market, (lname or wtitle).strip().lower())] = rid
    # Earliest dated volume per line (day/month precision, like last_dated_of below),
    # for pick_origin()'s step 2: whichever candidate market's main line shipped first.
    first_dated_of = dict(src.execute("""SELECT release_line_id, MIN(release_date) FROM volume
                                         WHERE release_date IS NOT NULL
                                           AND release_date_precision IN ('day','month')
                                         GROUP BY 1"""))

    origin_of = {}
    for (wid, medium), ms in markets_of.items():
        first_by_market = {m: first_dated_of.get(main_of.get((wid, m, medium))) for m in ms}
        origin_of[(wid, medium)] = pick_origin(medium, ms, first_by_market)
    int_max = dict(src.execute("""SELECT release_line_id, MAX(CAST(number AS INTEGER)) FROM volume
                                  WHERE number GLOB '[0-9]*' AND number NOT GLOB '*[^0-9]*'
                                  GROUP BY 1"""))
    # Last dated volume per line, day or month precision (a year-only date says nothing
    # about a 24-month window). Stored as the ISO prefix so strings compare.
    last_dated_of = dict(src.execute("""SELECT release_line_id, MAX(release_date) FROM volume
                                        WHERE release_date IS NOT NULL
                                          AND release_date_precision IN ('day','month')
                                        GROUP BY 1"""))

    def origin_line(wid, medium, market, lname, wtitle):
        """This licensed line's counterpart in the work's original market: the same-named
        line there, else that market's main line. None for an origin-market line."""
        om = origin_of.get((wid, medium))
        if om is None or om == market:
            return None
        return (line_key.get((wid, medium, om, (lname or wtitle).strip().lower()))
                or main_of.get((wid, om, medium)))

    n_series = n_vol = n_special = n_alias = n_omni = 0
    # (sid, alias.lower()) pairs inserted from a work_level=False candidate --
    # the line's own name, or its raw arc name (_line_raw) -- which alias
    # hygiene (below) never drops, no matter what it collides with: an arc is
    # often titled after its own volumes, and a folder named after the arc must
    # keep resolving to it (the Re:Zero comment above cands, "Truth of Zero").
    protected_aliases = set()
    # ids first, so a child line can point at its parent whichever comes first
    for rid, *_ in lines:
        if rid not in mapping:
            mapping[rid] = stable_int(rid, taken)
            taken.add(mapping[rid])
    # the line NAMED after the work per (work, market, medium): what an arc or
    # spin-off line belongs to when the splitter did not record a parent
    named_line = {}
    for rid, wid, market, medium, *_rest, wtitle, lname in lines:
        if (not lname) or normalize(lname) == normalize(wtitle):
            named_line.setdefault((wid, market, medium), rid)

    transitions, newly_stalled = collections.Counter(), []
    title_drops, n_title_kept = collections.Counter(), 0
    for rid, wid, market, medium, publisher, status, parent_rl, wtitle, lname in lines:
        sid = mapping[rid]
        is_main = 1 if main_of.get((wid, market, medium)) == rid else 0
        is_named = (not lname) or normalize(lname) == normalize(wtitle)
        parent_sid = mapping.get(parent_rl or (None if is_named else named_line.get((wid, market, medium))))
        if parent_sid == sid:
            parent_sid = None
        # Native-script titles are only legitimate on a line in its own origin market;
        # a licensed line's readers cannot use them (spec: fix round 1, controller finding).
        # An UNKNOWN origin is not the same as "this market IS the origin": a work with
        # only an EN line (no JP/KR/CN/TW counterpart at all) is never native for CJK
        # script (fix round 3 -- Jack Frost's en-only line was exporting raw Hangul).
        om = origin_of.get((wid, medium))
        native_script_ok = (om == market) if om is not None else (market in ORIGIN)

        vols = src.execute("""SELECT id, number, title, release_date, release_date_precision,
                                     isbn13, isbn10, format
                              FROM volume WHERE release_line_id=? ORDER BY rowid""", (rid,)).fetchall()
        comp_vol, comp_ch = {}, {}
        for vid, contains, ref_list in src.execute(
                """SELECT volume_id, contains, ref_list FROM composition c
                   WHERE c.volume_id IN (SELECT id FROM volume WHERE release_line_id=?)""", (rid,)):
            (comp_vol if contains == "volume" else comp_ch)[vid] = ref_list
        ints_written, dated, years, is_omni = set(), 0, [], 0
        for vid, num, title, rdate, prec, i13, i10, fmt in vols:
            c = comp_vol.get(vid)
            cv = covers.get(vid) or {}
            cover_src = ("correction" if "correction" in cv else          # a picked cover wins
                         "openbd" if market == "JP" and "openbd" in cv else
                         next(iter(cv), None))
            cover_url = cv.get(cover_src) if cover_src else None
            day = rdate if (rdate and prec == "day" and len(rdate) == 10) else None
            if rdate:
                years.append(int(rdate[:4]))
            try:
                iv = int(num)
                if iv < 0:
                    raise ValueError
            except (TypeError, ValueError):
                out.execute("""INSERT OR IGNORE INTO volumes_special
                    (gcd_series_id,volume_label,title,release_date,isbn13,page_count,composition)
                    VALUES(?,?,?,?,?,?,?)""", (sid, str(num), title, rdate, i13, pages.get(vid), c))
                n_special += 1
                continue
            title_out = title_for_export(title, lname or wtitle, native_script_ok, title_drops,
                                         trusted=vid in trusted_titles)
            if title_out:
                n_title_kept += 1
            cur = out.execute("""INSERT OR IGNORE INTO volumes
                (gcd_series_id,volume_number,title,release_date,isbn13,isbn10,page_count,
                 composition,release_date_precision,release_date_raw,volume_chapters,tome_id,
                 cover_url,cover_source)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (sid, iv, title_out, day, i13, i10, pages.get(vid), c, prec, rdate,
                 comp_ch.get(vid), vid, cover_url, cover_src))
            if cur.rowcount:
                ints_written.add(iv)
                n_vol += 1
                if day:
                    dated += 1
                # omnibus iff a READABLE volume genuinely contains >1 original
                # volume; a range-labelled special ('17-18') does not count
                if c and len(json.loads(c)) > 1:
                    is_omni = 1
        n_omni += is_omni
        # A straight-translation line carries no composition in the published file
        # (the pipeline writes `contains` only for omnibus lines; a corrected line
        # writes `[N]` for every volume so the cross-market mapping can see it).
        # Nulling it here keeps `is_omnibus=0 ⇒ composition IS NULL` true for every
        # line -- the artifact contract's rule -- and touches no existing line.
        if not is_omni:
            out.execute("UPDATE volumes SET composition=NULL WHERE gcd_series_id=? AND composition IS NOT NULL", (sid,))

        # volume_count = rows a consumer can actually read. Counting every row
        # (specials, duplicates) made Mangarr create Books with nothing behind them.
        w_status, w_year = work_facts.get(wid, (None, None))
        reach = set(ints_written)
        for cj in comp_vol.values():
            reach.update(n for n in json.loads(cj) if isinstance(n, int))
        orid = origin_line(wid, medium, market, lname, wtitle)
        orig_sid = mapping.get(orid) if orid else None
        if orid and not is_omni:
            # A licensed line with a counterpart: its own dates against the origin's
            # (export/line_status.py). Named or not no longer matters -- an arc has an
            # arc to compare with.
            mangarr_status = line_status(w_status, is_named, max(reach) if reach else None,
                                         last_dated_of.get(rid), int_max.get(orid),
                                         last_dated_of.get(orid), TODAY)
        else:
            # Origin-market lines, omnibus lines and lines with no counterpart keep the
            # work's status, with the reach correction as before.
            st = status or (w_status if is_named else None)
            oc = int_max.get(orid, 0) if orid else None
            if st == "ended" and oc and (max(reach) if reach else 0) < oc:
                st = "ongoing"
            mangarr_status = {"ended": "completed", "ongoing": "ongoing"}.get(st or "", None)
        transitions[(prev_status.get(rid), mangarr_status)] += 1
        if mangarr_status == "stalled" and prev_status.get(rid) != "stalled":
            newly_stalled.append((lname or wtitle, MARKET_LANG.get(market, market.lower()),
                                  max(reach) if reach else None, int_max.get(orid),
                                  last_dated_of.get(rid), last_dated_of.get(orid)))
        out.execute("""INSERT OR REPLACE INTO series
            (gcd_series_id,name,year_began,publisher,language,is_omnibus,volume_count,status,
             orig_series_id,medium,dated_count,is_main,tome_id,tome_work_id,parent_series_id,author)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (sid, lname or wtitle, min(years) if years else w_year, publisher,
             MARKET_LANG.get(market, market.lower()), is_omni, len(ints_written), mangarr_status,
             orig_sid, medium, dated, is_main, rid, wid, parent_sid, work_authors.get(wid)))
        out.execute("INSERT OR REPLACE INTO id_map VALUES(?,?, 'release_line')", (rid, sid))
        n_series += 1

        # ---- aliases -------------------------------------------------------
        # Main line: the work's titles in every language (raw article names AND
        # the cleaned work title -- raw names like "Liste des chapitres de X"
        # match no folder, cleaned ones do), plus subtitle-stripped heads unless
        # the head is some OTHER work's title.
        # Sub-line: only its own name and its bare sub-title when that is
        # specific enough (3+ tokens, not a generic heading) -- so a folder named
        # after the arc ("A Day in the Capital") can still resolve.
        # EVERY line carries its own name, and a sub-line also carries its bare
        # arc title ("Re:Zero (Truth of Zero)" -> "Truth of Zero"). The main
        # line ADDITIONALLY carries the work's titles in every language, plus
        # the official-English and redirect titles main_titles.py collected.
        #
        # These used to be either/or, so whichever arc happened to be the
        # market's main line lost its arc alias and became unreachable by the
        # only name a folder ever uses -- Re:Zero's "The Sanctuary and the Witch
        # of Greed" resolved to nothing at all.
        cands = [(lname or wtitle, False)]
        raw = _line_raw(lname, wtitle)
        if raw and raw != lname and len(normalize(raw).split()) >= 3 and not GENERIC.match(raw):
            cands.append((raw, False))
        if is_main:
            for (alias,) in src.execute("SELECT title FROM work_title WHERE work_id=?", (wid,)):
                if alias:
                    cands.append((alias, True))
                    cands.append((work_title(alias), True))
            cands.append((wtitle, True))

        def owned_by_another_work(text):
            """True when this string is some OTHER work's own title -- the
            guard that keeps 'Attack on Titan' off 'Attack on Titan: Before the
            Fall', and now also keeps a shared redirect off the wrong work."""
            return bool(other_titles.get(normalize(text), set()) - {wid})

        seen = set()
        for alias, work_level in cands:
            # A work-level alias is only as trustworthy as its uniqueness; a
            # line's own name is always kept, since that IS what it is called.
            if work_level and owned_by_another_work(alias):
                continue
            for a in variants(alias, with_heads=False):
                if a.lower() not in seen:
                    seen.add(a.lower())
                    out.execute("INSERT OR IGNORE INTO series_alias VALUES(?,?)", (sid, a))
                    n_alias += 1
                    if not work_level:
                        protected_aliases.add((sid, a.lower()))
            if not work_level:
                continue
            for head in heads(alias):
                if owned_by_another_work(head):
                    continue          # 'Attack on Titan' belongs to another work
                for a in (head, normalize(head)):
                    if a and a.lower() not in seen:
                        seen.add(a.lower())
                        out.execute("INSERT OR IGNORE INTO series_alias VALUES(?,?)", (sid, a))
                        n_alias += 1

    # ---- alias hygiene: drop a generated alias that collides with a volume
    # title (2026-09-23 follow-up) -------------------------------------------
    # A work-level alias (a Wikipedia redirect, an official title) can equal one
    # of the work's own volume titles: 'Aincrad' is both a Sword Art Online
    # redirect (attached to every main line of the work, is_main branch above)
    # AND the title of SAO's English light-novel volume 1 -- which makes it
    # ambiguous for series-picking (every main line of the work answers to it)
    # instead of useful. Checked against the line's OWN volume titles and its
    # origin line's (a licensed line whose own titles are often None/untitled
    # is where this bites hardest -- the collision lives on the origin's
    # volumes). A run AFTER the main loop, over the OUTPUT tables: only there
    # does every line's final titles and orig_series_id already exist, so this
    # does not depend on iteration order over `lines`. protected_aliases (the
    # line's own name, and its raw arc name) is exempt no matter what it
    # collides with -- see the comment where it is built, above.
    n_alias_dropped = 0
    title_sets = {}

    def _titles_of(s):
        if s not in title_sets:
            title_sets[s] = {normalize(t) for (t,) in out.execute(
                "SELECT title FROM volumes WHERE gcd_series_id=? AND title IS NOT NULL", (s,))}
        return title_sets[s]

    for sid, orig_sid in out.execute("SELECT gcd_series_id, orig_series_id FROM series").fetchall():
        collide = _titles_of(sid) | (_titles_of(orig_sid) if orig_sid is not None else set())
        if not collide:
            continue
        for (alias,) in out.execute(
                "SELECT alias FROM series_alias WHERE gcd_series_id=?", (sid,)).fetchall():
            if (sid, alias.lower()) in protected_aliases:
                continue
            if normalize(alias) in collide:
                out.execute("DELETE FROM series_alias WHERE gcd_series_id=? AND alias=?", (sid, alias))
                n_alias_dropped += 1
    n_alias -= n_alias_dropped

    # Hand-checked alias corrections (corrections/aliases.json). Applied last so
    # a correction always reaches the artifact, and asserted by test_artifact.py
    # so one that stops landing fails the build instead of vanishing quietly.
    n_corr = 0
    for line_id, alias in load_aliases():
        sid = mapping.get(line_id)
        if sid is None or not out.execute(
                "SELECT 1 FROM series WHERE gcd_series_id=?", (sid,)).fetchone():
            raise SystemExit(
                "corrections/aliases.json: release line %s is not in this catalogue --\n"
                "fix or remove the entry (see corrections/README.md)" % line_id)
        for a in variants(alias, with_heads=False):
            n_corr += out.execute(
                "INSERT OR IGNORE INTO series_alias VALUES(?,?)", (sid, a)).rowcount

    src_counts = dict(src.execute("SELECT source, COUNT(*) FROM claim GROUP BY source"))
    for k, v in [
        ("schema_version", "2"),
        ("generator", "opentome"),
        ("generated_at", NOW),
        ("source", "OpenTome — reconciled from Wikipedia, openBD, Open Library, BnF"),
        # BnF's Etalab licence and openBD's terms both REQUIRE retained attribution.
        # Names only the sources the pipeline actually reads (DNB is not wired in yet);
        # LICENSE-DATA.md carries this string byte-for-byte -- change both together.
        ("attribution", "Bibliographic data: Bibliotheque nationale de France (Licence Ouverte/Open Licence); "
                        "openBD; Open Library / Internet Archive; "
                        "Wikipedia contributors (facts only). Cover art is not included."),
        ("licence", "Free/non-commercial use. openBD and Open Library terms are non-commercial; "
                    "see docs/legal-position.md before any paid use."),
        ("gcd_dump", "opentome-" + NOW[:10]),
        ("volumes_special_count", str(n_special)),
        ("omnibus_lines", str(n_omni)),
        ("correction_aliases", str(len(load_aliases()))),
        # Publishing is gated on this being exactly "opentome": merge_aliases.py
        # overwrites it with the name of any artifact it merged aliases from, so
        # a build that is not clean-room fails the check rather than passing it
        # by omission. Fail-closed, not fail-open.
        ("alias_provenance", "opentome"),
        ("claim_sources", json.dumps(src_counts)),
        ("composition_semantics", "volumes.composition = original-market volume numbers this "
                                  "volume contains (omnibus). Chapters are in volume_chapters."),
        ("release_date_semantics", "release_date is day-precision only; coarser values are in "
                                   "release_date_raw with release_date_precision."),
    ]:
        out.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (k, v))

    # Read before publishing: what title_for_export kept vs rejected, and why (fix
    # round 1 -- wrong-script and markup titles were reaching the artifact).
    print("  titles kept %d; dropped: number-only %d, markup %d, wrong-script %d, redundant %d"
          "; prefix stripped %d" % (
        n_title_kept, title_drops["number_only"], title_drops["markup"],
        title_drops["wrong_script"], title_drops["redundant"], title_drops["prefix-stripped"]))

    # Read before publishing: every status that moved since the carry artifact, and the
    # lines that became 'stalled' (spec §6 decision 4). Also written next to the artifact.
    print("  status transitions (previous -> new):")
    for (a, b), n in sorted(transitions.items(), key=lambda kv: -kv[1]):
        if a != b:
            print("    %-10s -> %-10s %s" % (a or "NULL", b or "NULL", format(n, ",")))
    print("  newly stalled: %d" % len(newly_stalled))
    # None-safe: origin_last_dated (and a tie on name+lang, e.g. two "Aria the Scarlet
    # Ammo" lines) can put a None next to a str, which a bare sorted() can't compare
    # (fix round 3, the same class of bug as the transitions sort above).
    _stalled_key = lambda r: (r[0] or "", r[1] or "", r[2] if r[2] is not None else -1)
    for name, lang, mv, om, ld, old in sorted(newly_stalled, key=_stalled_key):
        print("    %s [%s] at %s of %s, last %s (origin last %s)" % (name, lang, mv, om, ld, old))
    with open(os.path.join(os.path.dirname(os.path.abspath(out_path)), "status-transitions.tsv"), "w", encoding="utf8") as fh:
        fh.write("previous\tnew\tlines\n")
        for (a, b), n in sorted(transitions.items(), key=lambda kv: (kv[0][0] or "", kv[0][1] or "")):
            fh.write("%s\t%s\t%d\n" % (a or "NULL", b or "NULL", n))
        fh.write("\nnewly_stalled\tlanguage\tmax_vol\torigin_max\tlast_dated\torigin_last_dated\n")
        for row in sorted(newly_stalled, key=_stalled_key):
            fh.write("\t".join("" if x is None else str(x) for x in row) + "\n")
    out.commit()
    return dict(series=n_series, volumes=n_vol, specials=n_special, aliases=n_alias,
                omnibus_lines=n_omni, aliases_dropped=n_alias_dropped)


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else _build("opentome.db")
    out = sys.argv[2] if len(sys.argv) > 2 else _build("manga-metadata.sqlite")
    carry = sys.argv[3] if len(sys.argv) > 3 else None
    r = export(src, out, carry)
    print("exported -> %s" % out)
    for k, v in r.items():
        print("   %-14s %s" % (k, format(v, ",")))
    print("   size           %.0f MB" % (os.path.getsize(out) / 1e6))
