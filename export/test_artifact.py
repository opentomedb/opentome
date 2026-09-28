"""Contract tests for the exported Mangarr artifact.

Run automatically by tier0/rebuild_all.sh. Each rule encodes something the C#
consumer assumes and the first export violated silently while every unit test
on both sides stayed green (docs/cleanup-v2.md):

  * composition = ORIGINAL volume numbers this volume contains; a series is
    omnibus iff some volume contains >1 of them
  * volume_count = rows a consumer can read (Mangarr creates Books 1..N)
  * release_date is day precision or NULL (never '2019' -> 1 January)
  * no wiki markup in names, aliases or publishers
  * no English/French series with zero data
"""
import json, os, re, sqlite3, sys

FAILS = []


def rule(label, n, detail=""):
    ok = n == 0
    print(("  ok   " if ok else "  FAIL ") + f"{label}: {n:,}" + (f"  {detail}" if not ok else ""))
    if not ok:
        FAILS.append(label)


def run(path):
    db = sqlite3.connect(path)
    g = lambda q: db.execute(q).fetchone()[0]

    rule("meta.gcd_dump missing or not opentome-YYYY-MM-DD",
         0 if re.fullmatch(r"opentome-\d{4}-\d{2}-\d{2}",
                           g("SELECT COALESCE((SELECT value FROM meta WHERE key='gcd_dump'),'')")) else 1)

    # composition semantics
    rule("is_omnibus=0 series with a composition",
         g("""SELECT COUNT(DISTINCT s.gcd_series_id) FROM series s JOIN volumes v USING(gcd_series_id)
              WHERE s.is_omnibus=0 AND v.composition IS NOT NULL"""))
    rule("is_omnibus=1 series with no multi-entry composition",
         g("""SELECT COUNT(*) FROM series s WHERE s.is_omnibus=1 AND NOT EXISTS
              (SELECT 1 FROM volumes v WHERE v.gcd_series_id=s.gcd_series_id
               AND v.composition IS NOT NULL AND LENGTH(v.composition)>3)"""))
    bad_comp = 0
    for (c,) in db.execute("SELECT composition FROM volumes WHERE composition IS NOT NULL"):
        try:
            lst = __import__("json").loads(c)
            if not (isinstance(lst, list) and all(isinstance(x, int) for x in lst) and 1 <= len(lst) <= 12):
                bad_comp += 1
        except Exception:
            bad_comp += 1
    rule("composition not a short list of ints", bad_comp)
    rule("chapter lists leaked into composition (len > 12)",
         g("""SELECT COUNT(*) FROM volumes WHERE composition IS NOT NULL
              AND LENGTH(composition) - LENGTH(REPLACE(composition, ',', '')) >= 12"""))

    # counts
    rule("series.volume_count != rows in volumes",
         g("""SELECT COUNT(*) FROM series s WHERE s.volume_count <>
              (SELECT COUNT(*) FROM volumes v WHERE v.gcd_series_id=s.gcd_series_id)"""))
    rule("volumes with volume_number < 0", g("SELECT COUNT(*) FROM volumes WHERE volume_number < 0"))

    # dates
    rule("release_date not day precision (must be NULL or YYYY-MM-DD)",
         g("""SELECT COUNT(*) FROM volumes WHERE release_date IS NOT NULL
              AND (LENGTH(release_date)<>10 OR release_date_precision<>'day')"""))
    rule("Jan-1 release dates (year-only tell)",
         g("SELECT COUNT(*) FROM volumes WHERE release_date LIKE '%-01-01'"))

    # names / aliases
    rule("series names with wiki markup",
         g("""SELECT COUNT(*) FROM series WHERE name LIKE '%{{%' OR name LIKE '%[[%'
              OR name LIKE '%<%' OR name LIKE '%}}%'"""))
    rule("aliases with wiki markup",
         g("""SELECT COUNT(*) FROM series_alias WHERE alias LIKE '%{{%' OR alias LIKE '%[[%'
              OR alias LIKE '%<%'"""))
    rule("series_alias rows without a known kind",
         g("""SELECT COUNT(*) FROM series_alias WHERE kind IS NULL OR kind NOT IN
              ('line','official','alias','abbreviation','romanized','correction')"""))
    rule("empty series names", g("SELECT COUNT(*) FROM series WHERE TRIM(name)=''"))
    # Preferred Edition (2026-09-24): every line says its market; a local name is a clean title.
    rule("series without a country (the market code)",
         g("SELECT COUNT(*) FROM series WHERE country IS NULL OR TRIM(country)=''"))
    rule("local_name with markup or a list-article prefix",
         g("""SELECT COUNT(*) FROM series WHERE local_name LIKE '%{{%' OR local_name LIKE '%[[%'
              OR local_name LIKE 'Liste %' OR local_name LIKE 'Chronologie %' OR TRIM(local_name)=''"""))
    print("  info  local_name by language: %s" % ", ".join(
        "%s %s/%s" % (l, format(n, ","), format(t, ",")) for l, n, t in db.execute(
            "SELECT language, SUM(local_name IS NOT NULL), COUNT(*) FROM series GROUP BY 1 ORDER BY 3 DESC")))
    # a lone "<上>" / "<First>" is text, not markup -- flag exactly the exporter's drop
    # set (MARKUP_TITLE_RE in to_mangarr.py), never a bare '<'.
    rule("volume titles with wiki markup",
         g("""SELECT COUNT(*) FROM volumes WHERE title LIKE '%{{%' OR title LIKE '%}}%'
              OR title LIKE '%[[%' OR title LIKE '%]]%' OR title LIKE '%<ref%'
              OR title LIKE '%<br%' OR title LIKE '%<!--%' OR title LIKE '%<ruby%'
              OR title LIKE '%</%'"""))
    number_only = 0
    for (t,) in db.execute("SELECT title FROM volumes WHERE title IS NOT NULL"):
        if re.fullmatch(r"\s*(?:vol(?:ume)?\.?\s*|tome\s*|band\s*)?\d+\s*", t, re.I):
            number_only += 1
    rule("volume titles that only repeat the number", number_only)
    rule("publishers with markup",
         g("""SELECT COUNT(*) FROM series WHERE publisher LIKE '%<%' OR publisher LIKE '%{{%'
              OR publisher LIKE '%}}%' OR publisher LIKE '%[[%'"""))
    rule("authors with markup",
         g("""SELECT COUNT(*) FROM series WHERE author LIKE '%<%' OR author LIKE '%{{%'
              OR author LIKE '%}}%' OR author LIKE '%[[%'"""))

    # phantom lines: no date of ANY precision and no ISBN (release_date is
    # day-only; a month/year value lives in release_date_raw and is data)
    rule("en/fr/de series with no date (any precision) and no ISBN",
         g("""SELECT COUNT(*) FROM series s WHERE s.language IN ('en','fr','de')
              AND s.volume_count>0 AND NOT EXISTS (SELECT 1 FROM volumes v
              WHERE v.gcd_series_id=s.gcd_series_id
              AND (v.release_date_raw IS NOT NULL OR v.isbn13 IS NOT NULL))"""))
    rule("un-collapsed omnibus rows (consecutive, same ISBN, same date) in a non-ja series",
         g("""SELECT COUNT(*) FROM volumes a JOIN volumes b ON b.gcd_series_id=a.gcd_series_id
              AND b.isbn13=a.isbn13
              AND COALESCE(b.release_date_raw,'')=COALESCE(a.release_date_raw,'')
              AND b.volume_number=a.volume_number+1
              JOIN series s ON s.gcd_series_id=a.gcd_series_id
              WHERE s.language<>'ja' AND a.isbn13 IS NOT NULL"""))
    print("  info  same ISBN on rows with different dates / gaps (upstream, not merged): %s" % format(
        g("""SELECT COUNT(*) FROM (SELECT v.gcd_series_id, v.isbn13 FROM volumes v
             JOIN series s USING(gcd_series_id) WHERE s.language<>'ja' AND v.isbn13 IS NOT NULL
             GROUP BY 1,2 HAVING COUNT(*)>1)"""), ","))

    # corrections must actually land -- the whole point of keeping them as data
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "corrections", os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "tier2", "corrections.py"))
    corr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(corr)

    missing_alias = 0
    for line_id, alias in corr.load_aliases():
        hit = db.execute("""SELECT 1 FROM series_alias a JOIN series s USING(gcd_series_id)
                            WHERE s.tome_id=? AND a.alias=? COLLATE NOCASE""",
                         (line_id, alias)).fetchone()
        missing_alias += not hit
    rule("alias corrections missing from the artifact", missing_alias)

    missing_value, checked_value = 0, 0
    for e in corr._read("volumes.json"):
        key, field, want = str(e["volume"]).strip(), e["field"], str(e["value"])
        if field not in ("release_date", "isbn13", "page_count", "title", "cover_url"):
            continue
        col = "release_date" if field == "release_date" else field
        row = db.execute(
            "SELECT %s FROM volumes WHERE tome_id=? OR isbn13=?" % col,
            (key, re.sub(r"[^0-9Xx]", "", key))).fetchone()
        if row is None:
            continue        # non-integer volume label -> volumes_special, not read here
        checked_value += 1
        missing_value += str(row[0]) != want
    rule("volume corrections not present in the artifact", missing_value,
         f"({checked_value} checked)")

    missing_line = 0
    for e in corr._read("lines.json"):
        if "volumes" not in e:
            continue        # a medium override, not a new line -- checked below
        rid = corr._id("rl_", e["work"], e["medium"], e["market"].upper(), e["name"].strip())
        want = sum(1 for v in e["volumes"] if str(v.get("number", "")).strip().isdigit())
        row = db.execute("SELECT volume_count FROM series WHERE tome_id=?", (rid,)).fetchone()
        missing_line += (row is None or row[0] < want)
    rule("line corrections missing from the artifact", missing_line)

    missing_medium = 0
    for e in corr._read("lines.json"):
        if "volumes" in e or "medium" not in e:
            continue
        row = db.execute("SELECT medium FROM series WHERE tome_id=?", (e["line"],)).fetchone()
        missing_medium += (row is None or row[0] != e["medium"])
    rule("medium corrections not present in the artifact", missing_medium)

    missing_market = 0
    for e in corr._read("lines.json"):
        if "volumes" in e or "market" not in e:
            continue
        row = db.execute("SELECT language FROM series WHERE tome_id=?", (e["line"],)).fetchone()
        want_lang = corr.MARKET_LANG.get(str(e["market"]).upper())
        missing_market += (row is None or row[0] != want_lang)
    rule("market corrections not present in the artifact", missing_market)

    missing_removal = 0
    for line_id, alias in corr.load_alias_removals():
        hit = db.execute("""SELECT 1 FROM series_alias a JOIN series s USING(gcd_series_id)
                            WHERE s.tome_id=? AND a.alias=?""", (line_id, alias)).fetchone()
        missing_removal += bool(hit)
    rule("removed aliases still present in the artifact", missing_removal)

    wrong_pin = 0
    for line_id, aid in corr.load_anilist_pins():
        row = db.execute("SELECT anilist_id FROM series WHERE tome_id=?", (line_id,)).fetchone()
        wrong_pin += (row is None or row[0] != aid)
    rule("anilist id pins not present in the artifact", wrong_pin)

    missing_excluded = 0
    for wid in corr.load_exclusions():
        hit = db.execute("SELECT 1 FROM series WHERE tome_work_id=?", (wid,)).fetchone()
        missing_excluded += bool(hit)
    rule("excluded works still present in the artifact", missing_excluded)

    # Open Library's "no cover" placeholder (id -1, a 404 on archive.org) must never ship as a
    # cover: tier1/covers.py drops it at the source (2026-09-24, 15 volumes).
    placeholder = db.execute("""SELECT COUNT(*) FROM volumes
                                WHERE cover_url LIKE '%covers.openlibrary.org/b/id/-%'
                                   OR cover_url LIKE '%covers.openlibrary.org/b/id/0-%'""").fetchone()[0]
    rule("Open Library placeholder covers (id <= 0) in the artifact", placeholder)

    # status / covers (schema_version 2 additions)
    rule("licensed line 'completed' while behind its same-named original-market line",
         g("""SELECT COUNT(*) FROM series l JOIN series o
              ON o.tome_work_id=l.tome_work_id AND o.medium=l.medium AND o.name=l.name
              AND o.language IN ('ja','ko','zh') AND l.language NOT IN ('ja','ko','zh')
              WHERE l.status='completed' AND l.is_omnibus=0
              AND (SELECT MAX(volume_number) FROM volumes WHERE gcd_series_id=l.gcd_series_id)
                < (SELECT MAX(volume_number) FROM volumes WHERE gcd_series_id=o.gcd_series_id)"""))
    rule("parent_series_id pointing at a missing series",
         g("SELECT COUNT(*) FROM series c WHERE parent_series_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM series p WHERE p.gcd_series_id=c.parent_series_id)"))
    rule("parent_series_id pointing at a series of another work or market",
         g("""SELECT COUNT(*) FROM series c JOIN series p ON p.gcd_series_id=c.parent_series_id
              WHERE p.tome_work_id<>c.tome_work_id OR p.language<>c.language"""))
    print("  info  series with a parent (collection members): %s" % format(g("SELECT COUNT(*) FROM series WHERE parent_series_id IS NOT NULL"), ","))
    rule("series.status outside {completed, ongoing, stalled, NULL}",
         g("SELECT COUNT(*) FROM series WHERE status IS NOT NULL AND status NOT IN ('completed','ongoing','stalled')"))
    # stalled (export/line_status.py): >= 2 volumes behind its origin line and nothing dated in
    # the last 24 months. Both halves are re-checked here so the rule cannot drift from the gate.
    rule("stalled line without orig_series_id",
         g("SELECT COUNT(*) FROM series WHERE status='stalled' AND orig_series_id IS NULL"))
    rule("stalled line with a dated volume in the last 24 months",
         g("""SELECT COUNT(*) FROM series s WHERE s.status='stalled' AND EXISTS
              (SELECT 1 FROM volumes v WHERE v.gcd_series_id=s.gcd_series_id
               AND v.release_date_precision IN ('day','month')
               AND v.release_date_raw >= strftime('%Y-%m', 'now', '-24 months'))"""))
    rule("stalled line not at least two volumes behind its origin",
         g("""SELECT COUNT(*) FROM series l JOIN series o ON o.gcd_series_id=l.orig_series_id
              WHERE l.status='stalled'
              AND (SELECT COALESCE(MAX(volume_number),0) FROM volumes WHERE gcd_series_id=o.gcd_series_id)
                - (SELECT COALESCE(MAX(volume_number),0) FROM volumes WHERE gcd_series_id=l.gcd_series_id) < 2"""))
    rule("orig_series_id pointing at a missing series, another work, or an origin-market mismatch",
         g("""SELECT COUNT(*) FROM series l LEFT JOIN series o ON o.gcd_series_id=l.orig_series_id
              WHERE l.orig_series_id IS NOT NULL
              AND (o.gcd_series_id IS NULL OR o.tome_work_id<>l.tome_work_id OR o.medium<>l.medium
                   OR o.language NOT IN ('ja','ko','zh','zh-TW','zh-HK') OR o.language=l.language)"""))
    rule("cover_url without cover_source (or vice versa)",
         g("""SELECT COUNT(*) FROM volumes WHERE (cover_url IS NULL) <> (cover_source IS NULL)"""))
    rule("cover_url that is not http(s)",
         g("SELECT COUNT(*) FROM volumes WHERE cover_url IS NOT NULL AND cover_url NOT LIKE 'http%'"))
    # AniList ids (export/resolve_anilist.py, 2026-09-15): Mangarr binds by this id BEFORE any
    # title search, so the lines people actually add must carry one, and one AniList entry
    # can only be one work -- an id on two works is a wrong bind on at least one of them.
    # The allowance is 15 % (measured 13.1 % on opentome-2026-09-04; the residue is catalogue
    # naming -- Wikipedia list-article names, franchises AniList lists per part -- that no
    # exact-equality rule can reach, and a guess would be pinned by every future add).
    en3 = g("SELECT COUNT(*) FROM series WHERE language='en' AND volume_count>=3")
    en3_missing = g("SELECT COUNT(*) FROM series WHERE language='en' AND volume_count>=3 AND anilist_id IS NULL")
    rule("EN lines (volume_count >= 3) without anilist_id beyond the 15 % allowance",
         max(0, en3_missing - en3 * 15 // 100), f"({en3_missing:,} of {en3:,} unresolved)")
    # Report-only (ruled 2026-09-15): on opentome-2026-09-04 every shared id but one is the same
    # spin-off modelled twice in the catalogue (a parent-nested "(Before the Fall)" line AND the
    # article's own work) and the other is Dragon Ball / Dragon Ball Z -- two works, one AniList
    # entry. Both are catalogue shape, not a resolver fault; a genuinely wrong bind shows up here
    # too, so the pairs are printed for reading, never gated.
    shared = db.execute("""SELECT s.anilist_id, group_concat(s.name, ' | ') FROM series s
              WHERE s.language='en' AND s.anilist_id IN (SELECT anilist_id FROM series WHERE language='en'
              AND anilist_id IS NOT NULL GROUP BY anilist_id HAVING COUNT(DISTINCT tome_work_id)>1)
              GROUP BY 1 ORDER BY 1""").fetchall()
    print("  info  anilist_id shared by EN lines of different works: %d" % len(shared))
    for aid, names in shared:
        print("        %s: %s" % (aid, names))
    # Display-only fallback (export/resolve_anilist.py display(), 2026-09-24): a cover / synopsis
    # id for a line the rules left NULL. It must never look like a binding -- Mangarr pins
    # anilist_id, and a display id there would be a guess pinned by every future add.
    rule("display_anilist_id on a line that has an anilist_id, or on a non-EN line",
         g("""SELECT COUNT(*) FROM series WHERE display_anilist_id IS NOT NULL
              AND (anilist_id IS NOT NULL OR language<>'en')"""))
    rule("display_anilist_id and display_anilist_via not set together",
         g("SELECT COUNT(*) FROM series WHERE (display_anilist_id IS NULL) <> (display_anilist_via IS NULL)"))
    rule("display_anilist_via outside {parent, medium}",
         g("SELECT COUNT(*) FROM series WHERE display_anilist_via NOT IN ('parent','medium')"))
    rule("display_anilist_via 'medium' on a line that is not a novel / light_novel",
         g("""SELECT COUNT(*) FROM series WHERE display_anilist_via='medium'
              AND COALESCE(medium,'') NOT IN ('novel','light_novel')"""))
    # 'parent': the id is the anilist_id of a bound EN line of the SAME work whose name is the
    # line's name cut at its first ' (' / ': ' / ' - ' / ' / ' (key = letters and digits only)
    k = lambda s: "".join(c for c in (s or "").lower() if c.isalnum())
    bound = {}
    for wid, name, aid in db.execute("""SELECT tome_work_id, name, anilist_id FROM series
                                        WHERE language='en' AND anilist_id IS NOT NULL"""):
        bound.setdefault((wid, k(name)), set()).add(aid)
    bad_parent = 0
    for wid, name, did in db.execute("""SELECT tome_work_id, name, display_anilist_id FROM series
                                        WHERE display_anilist_via='parent'"""):
        s = " ".join(name.replace("–", "-").replace("—", "-").replace(" ", " ").split())
        m = re.search(r" \(|: | - | / ", s)
        bad_parent += not (m and bound.get((wid, k(s[:m.start()]))) == {did})   # unambiguous, too
    rule("'parent' display id that is not its same-work parent line's anilist_id", bad_parent)
    print("  info  display-only AniList ids (not bindings): %s" % (", ".join(
        "%s via %s" % (format(n, ","), v) for v, n in db.execute(
            """SELECT display_anilist_via, COUNT(*) FROM series WHERE display_anilist_via IS NOT NULL
               GROUP BY 1 ORDER BY 1""")) or "none"))
    print("  info  EN lines with anilist_id: %s / %s (volume_count >= 3: %s / %s)" % (
        format(g("SELECT COUNT(*) FROM series WHERE language='en' AND anilist_id IS NOT NULL"), ","),
        format(g("SELECT COUNT(*) FROM series WHERE language='en'"), ","),
        format(en3 - en3_missing, ","), format(en3, ",")))
    print("  info  series with status: %s | volumes with an ISBN-keyed cover: %s | publishers set: %s" % (
        format(g("SELECT COUNT(*) FROM series WHERE status IS NOT NULL"), ","),
        format(g("SELECT COUNT(*) FROM volumes WHERE cover_url IS NOT NULL"), ","),
        format(g("SELECT COUNT(*) FROM series WHERE publisher IS NOT NULL"), ",")))
    # Nested-template residue from tier-0's regex unwrap can leave a bare '|' in a title;
    # counted, not gated, so the number is read before a publish (HANDOFF follow-up).
    print("  info  volume titles carrying a '|': %s" % format(g("SELECT COUNT(*) FROM volumes WHERE title LIKE '%|%'"), ","))
    print("  info  status by value (en): %s" % ", ".join(
        "%s %s" % (s or "NULL", format(n, ",")) for s, n in db.execute(
            "SELECT status, COUNT(*) FROM series WHERE language='en' GROUP BY 1 ORDER BY 2 DESC")))
    print("  info  volumes with a title: %s / %s | licensed lines with orig_series_id: %s / %s" % (
        format(g("SELECT COUNT(*) FROM volumes WHERE title IS NOT NULL"), ","),
        format(g("SELECT COUNT(*) FROM volumes"), ","),
        format(g("SELECT COUNT(*) FROM series WHERE orig_series_id IS NOT NULL"), ","),
        format(g("SELECT COUNT(*) FROM series WHERE language NOT IN ('ja','ko','zh','zh-TW','zh-HK')"), ",")))
    print("  info  series with an author: %s / %s" % (
        format(g("SELECT COUNT(*) FROM series WHERE author IS NOT NULL"), ","),
        format(g("SELECT COUNT(*) FROM series"), ",")))

    # ids
    rule("series without an id_map row",
         g("""SELECT COUNT(*) FROM series s WHERE NOT EXISTS
              (SELECT 1 FROM id_map m WHERE m.int_id=s.gcd_series_id)"""))
    rule("more than one main line per (work, language, medium)",
         g("""SELECT COUNT(*) FROM (SELECT tome_work_id, language, medium FROM series
              WHERE is_main=1 GROUP BY 1,2,3 HAVING COUNT(*)>1)"""))

    # Preferred Edition (2026-09-24): meta.markets must agree with a straight count of series.language
    mk = json.loads(g("SELECT COALESCE((SELECT value FROM meta WHERE key='markets'),'{}')"))
    rule("meta.markets disagrees with series.language counts",
         sum(1 for l, n in db.execute("SELECT language, COUNT(*) FROM series WHERE language IS NOT NULL GROUP BY 1")
             if mk.get(l) != n))

    # informational
    print("  info  series %s / volumes %s / aliases %s / omnibus lines %s / specials %s" % (
        format(g("SELECT COUNT(*) FROM series"), ","),
        format(g("SELECT COUNT(*) FROM volumes"), ","),
        format(g("SELECT COUNT(*) FROM series_alias"), ","),
        format(g("SELECT COUNT(*) FROM series WHERE is_omnibus=1"), ","),
        format(g("SELECT COUNT(*) FROM volumes_special"), ",")))
    amb = g("""SELECT COUNT(*) FROM (SELECT LOWER(alias) a FROM series_alias sa
               JOIN series s USING(gcd_series_id) WHERE s.language='en'
               GROUP BY a HAVING COUNT(DISTINCT gcd_series_id)>1)""")
    print(f"  info  en aliases shared by >1 en series: {amb:,}")
    return FAILS


DNB_FIELDS = ("isbn13", "release_date", "projected_date", "page_count", "volume_number", "line_name", "publisher")


MAX_RETIRED_DE_VOLUMES = 25
# Every market (2026-09-25, alias-fix). RETIRED = a carried id that no longer resolves to an id of
# its own kind: a volume redirected to a line, a line redirected with reason 'retired' (to its
# work's main line), anything with reason 'retired', or not resolving at all. A re-key or a merge
# moves ids without retiring them (alias-fix: 261 moved, 0 retired). A mass retirement is a lost
# source or a parser change -- stop and look. The lines and volumes of a work listed in THIS
# build's corrections/excluded.json (meta.excluded_works) are retired on purpose and do not
# count; a work that vanishes without being listed there counts (and fails the lost-ids rule).
MAX_RETIRED_VOLUMES = 100
MAX_RETIRED_LINES = 10
# Moved (re-keyed or merged) carried ids of any kind. Generous -- this round moved 261 -- but a
# mass re-key (a title rule touching thousands of names) must not ship green because every id
# found a successor; the count is always printed.
MAX_MOVED_IDS = 500

def run_ids(path, carry):
    """IDs are a public contract: every work, line and volume id of the carried (last published)
    artifact, in every market -- and every id its own id_redirect already resolved -- is still
    present here or resolves through this artifact's id_redirect to one that is
    (tier0/carried_ids.py). A work in meta.excluded_works takes its lines and volumes with it,
    on purpose."""
    db = sqlite3.connect(path)
    C = sqlite3.connect(carry)
    cols = {r[1] for r in C.execute("PRAGMA table_info(series)")}
    work_col = "tome_work_id" if "tome_work_id" in cols else "NULL"
    try:
        lines = {t: (w, l) for t, w, l in C.execute("SELECT tome_id, %s, language FROM series" % work_col) if t}
        vols = {t: (s, lines.get(s, (None, None))[1]) for t, s in C.execute(
            "SELECT v.tome_id, s.tome_id FROM volumes v JOIN series s USING(gcd_series_id)") if t}
    except sqlite3.OperationalError:
        lines, vols = {}, {}
    works = {w for w, _ in lines.values() if w}
    old = list(lines) + list(vols) + sorted(works)
    # ids the carry already resolved through ITS id_redirect must keep resolving here: a
    # retired id resolves forever, not only in the build that retired it
    try:
        carried_red = dict(C.execute("SELECT old_tome_id, new_tome_id FROM id_redirect"))
    except sqlite3.OperationalError:
        carried_red = {}
    old += sorted(set(carried_red) - set(old))
    present = {r[0] for r in db.execute("SELECT tome_id FROM series UNION SELECT tome_id FROM volumes")}
    vol_now = {r[0] for r in db.execute("SELECT tome_id FROM volumes")}
    try:    # a merged work's redirect targets a work id (tier0/carried_ids.py)
        present |= {r[0] for r in db.execute("SELECT DISTINCT tome_work_id FROM series")}
    except sqlite3.OperationalError:
        pass
    try:
        red = dict(db.execute("SELECT old_tome_id, new_tome_id FROM id_redirect"))
    except sqlite3.OperationalError:
        red = {}
    try:
        excluded = set(json.loads(db.execute("SELECT value FROM meta WHERE key='excluded_works'").fetchone()[0]))
    except (sqlite3.OperationalError, TypeError, ValueError):
        excluded = set()
    work_of = {t: w for t, (w, _) in lines.items()}
    work_of.update({t: work_of.get(s) for t, (s, _) in vols.items()})
    work_of.update({t: work_of.get(n, n) for t, n in carried_red.items() if t not in work_of})
    exempt = {t for t in old if (work_of.get(t) or t) in excluded}
    lost = [t for t in old if t and t not in present and red.get(t) not in present and t not in exempt]
    rule("carried ids (every market: works, lines, volumes) neither present nor redirected", len(lost), str(lost[:5]))
    # A redirect keeps an id resolvable; it does not make losing the volume right. More than a
    # handful of carried German volumes gone in one build is a DNB outage, a clustering change or
    # a linker change -- stop and look before it ships (N1, 2026-09-24 re-review).
    de = [t for t, (_, lang) in vols.items() if lang == "de"]
    gone = [t for t in de if t not in present]
    rule("more than %d carried German volumes retired in one build" % MAX_RETIRED_DE_VOLUMES,
         0 if len(gone) <= MAX_RETIRED_DE_VOLUMES else len(gone), str(gone[:5]))
    try:
        reason = dict(db.execute("SELECT old_tome_id, reason FROM id_redirect"))
    except sqlite3.OperationalError:
        reason = {}
    retired = [t for t in vols if t not in present and t not in exempt
               and (red.get(t) not in vol_now or reason.get(t) == "retired")]
    rule("more than %d carried volumes retired in one build (every market)" % MAX_RETIRED_VOLUMES,
         0 if len(retired) <= MAX_RETIRED_VOLUMES else len(retired), str(retired[:5]))
    line_now = {r[0] for r in db.execute("SELECT tome_id FROM series")}
    retired_lines = [t for t in lines if t not in present and t not in exempt
                     and (red.get(t) not in line_now or reason.get(t) == "retired")]
    rule("more than %d carried lines retired in one build (every market)" % MAX_RETIRED_LINES,
         0 if len(retired_lines) <= MAX_RETIRED_LINES else len(retired_lines), str(retired_lines[:5]))
    # moved in THIS build: an id the carry had already redirected is not a new move (else the
    # cap would count every redirect ever written, and trip once history passed 500)
    moved_ids = [t for t in old if t not in present and t not in exempt and t not in carried_red
                 and red.get(t) in present]
    rule("more than %d carried ids moved (re-keyed or merged) in one build" % MAX_MOVED_IDS,
         0 if len(moved_ids) <= MAX_MOVED_IDS else len(moved_ids), str(moved_ids[:5]))
    rule("id_redirect rows whose target is not in the artifact",
         sum(1 for t in red.values() if t not in present))
    # Integers are a contract too (Mangarr stores gcd_series_id): every carried integer is still a
    # series here, or an id_redirect.old_series_id that resolves it -- and one the carry already
    # resolved keeps resolving.
    def ints(d, q):
        try:
            return {r[0]: r[1] for r in d.execute(q) if r[0] is not None}
        except sqlite3.OperationalError:
            return {}
    carried_ints = ints(C, "SELECT gcd_series_id, tome_id FROM series")
    carried_ints.update({i: t for i, t in ints(C, "SELECT old_series_id, old_tome_id FROM id_redirect").items()
                         if i not in carried_ints})
    have_ints = set(ints(db, "SELECT gcd_series_id, tome_id FROM series")) | \
        set(ints(db, "SELECT old_series_id, old_tome_id FROM id_redirect"))
    lost_ints = [i for i, t in carried_ints.items() if i not in have_ints and t not in exempt]
    rule("carried series integers neither a series nor an id_redirect.old_series_id", len(lost_ints),
         str(lost_ints[:5]))
    # A duplicate line 4c merged (the carry's meta.merged_lines) must stay merged: if a later
    # build stops re-applying the record, the duplicate ships again under its own id and no
    # carried id is lost -- nothing else would notice.
    try:
        merged_dups = [d for d, _ in json.loads(C.execute(
            "SELECT value FROM meta WHERE key='merged_lines'").fetchone()[0])]
    except (sqlite3.OperationalError, TypeError, ValueError):
        merged_dups = []
    back = [d for d in merged_dups if d in present]
    rule("duplicate lines merged in an earlier build (carry meta.merged_lines) shipping again", len(back), str(back[:5]))
    moved = [t for t in old if t not in present and t not in exempt]
    print("  info  carried ids: %s works / %s lines / %s volumes / %s already redirected; not present here: %s "
          "(redirected %s, moved %s of %s allowed, retired lines %s / volumes %s, excluded works' ids %s)" % (
              format(len(works), ","), format(len(lines), ","), format(len(vols), ","), format(len(carried_red), ","),
              format(len(moved) + len([t for t in exempt if t not in present]), ","),
              format(sum(1 for t in moved if red.get(t) in present), ","), format(len(moved_ids), ","),
              format(MAX_MOVED_IDS, ","), format(len(retired_lines), ","), format(len(retired), ","),
              format(sum(1 for t in exempt if t not in present), ",")))
    de_ids = [t for t, (_, lang) in lines.items() if lang == "de"] + de
    print("  info  carried German ids: %s, redirected: %s" % (
        format(len(de_ids), ","), format(sum(1 for t in de_ids if t in red), ",")))


def run_dnb(path, catalogue):
    """The German (DNB) rules, docs/dnb-design.md "Gates". Most need the pipeline catalogue:
    the artifact carries no per-claim provenance."""
    db = sqlite3.connect(path)
    cat = sqlite3.connect(catalogue)
    g = lambda q, *a: db.execute(q, a).fetchone()[0]
    c = lambda q, *a: cat.execute(q, a).fetchone()[0]
    fx = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")

    # ids are a public contract: the German Wikipedia lines that predate DNB stay present
    pre = [l["tome_id"] for l in json.load(open(os.path.join(fx, "de_lines_pre_dnb.json"), encoding="utf8"))["lines"]]
    have = {r[0] for r in db.execute("SELECT tome_id FROM series WHERE language='de'")}
    rule("pre-DNB German line ids missing from the artifact", sum(1 for t in pre if t not in have),
         str([t for t in pre if t not in have][:5]))
    lost = []
    for l in json.load(open(os.path.join(fx, "de_lines_pre_dnb.json"), encoding="utf8"))["lines"]:
        row = db.execute("SELECT gcd_series_id, is_main FROM series WHERE tome_id=?", (l["tome_id"],)).fetchone()
        if row is None:
            continue
        isbns = {r[0] for r in db.execute("SELECT isbn13 FROM volumes WHERE gcd_series_id=?", (row[0],))}
        if row[1] != l.get("is_main", row[1]) or set(l.get("isbns", [])) - isbns:
            lost.append(l["name"])
    rule("pre-DNB German lines that lost is_main or one of their ISBNs (a DNB line took over)", len(lost), str(lost))

    # DNB delivers NFD; everything German that ships must be NFC (review 2026-09-24)
    import unicodedata
    non_nfc = sum(1 for (t,) in db.execute("""SELECT name FROM series WHERE language='de' UNION ALL
                      SELECT publisher FROM series WHERE language='de' AND publisher IS NOT NULL UNION ALL
                      SELECT a.alias FROM series_alias a JOIN series s USING(gcd_series_id) WHERE s.language='de'""")
                  if t != unicodedata.normalize("NFC", t))
    rule("non-NFC strings in German series names, publishers or aliases", non_nfc)

    # provenance: CC0, a d-nb.info record url, bibliographic fields only (no cover, no blurb)
    rule("dnb claims not licensed cc0", c("SELECT COUNT(*) FROM claim WHERE source='dnb' AND licence<>'cc0'"))
    rule("dnb claims without a https://d-nb.info/ source_url",
         c("SELECT COUNT(*) FROM claim WHERE source='dnb' AND COALESCE(source_url,'') NOT LIKE 'https://d-nb.info/%'"))
    rule("dnb claims outside the bibliographic fields (covers / blurbs are not CC0)",
         c("SELECT COUNT(*) FROM claim WHERE source='dnb' AND field NOT IN (%s)" % ",".join("?" * len(DNB_FIELDS)),
           *DNB_FIELDS))

    # dates: published = the 008 year; projected = a 263 month that never outranks a real date
    rule("dnb release_date claims that are not year precision",
         c("SELECT COUNT(*) FROM claim WHERE source='dnb' AND field='release_date' AND value NOT GLOB '[12][0-9][0-9][0-9]'"))
    rule("dnb projected_date claims that are not month precision",
         c("SELECT COUNT(*) FROM claim WHERE source='dnb' AND field='projected_date' "
           "AND value NOT GLOB '[12][0-9][0-9][0-9]-[01][0-9]'"))
    rule("projected volumes that also have a release_date claim (projected outranked a real date)",
         c("""SELECT COUNT(*) FROM volume v WHERE v.release_date_type='projected' AND EXISTS
              (SELECT 1 FROM claim x WHERE x.entity='volume' AND x.entity_id=v.id AND x.field='release_date')"""))
    rule("projected dates more than 12 months past (a plan that never arrived is dropped)",
         c("""SELECT COUNT(*) FROM volume WHERE release_date_type='projected'
              AND release_date < strftime('%Y-%m', 'now', '-12 months')"""))
    rule("projected volumes not month precision (catalogue)",
         c("""SELECT COUNT(*) FROM volume WHERE release_date_type='projected'
              AND (release_date_precision<>'month' OR LENGTH(release_date)<>7)"""))
    rule("projected volumes not month precision (artifact)",
         g("""SELECT COUNT(*) FROM volumes WHERE release_date_type='projected'
              AND (release_date_precision<>'month' OR LENGTH(release_date_raw)<>7 OR release_date IS NOT NULL)"""))
    rule("release_date_type set on an undated volume, or missing on a dated one",
         g("SELECT COUNT(*) FROM volumes WHERE (release_date_type IS NULL) <> (release_date_raw IS NULL)"))
    year = __import__("datetime").date.today().year
    rule("a volume from a future-year announcement-only record (held back by design)",
         c("SELECT COUNT(*) FROM dnb_member WHERE fate='held_future' AND volume_id IS NOT NULL")
         + c("""SELECT COUNT(*) FROM claim WHERE source='dnb' AND field='projected_date'
                AND CAST(SUBSTR(value,1,4) AS INTEGER) > ?""", year))
    # A German Wikipedia table that lists one ISBN on two rows (Gothic Sports 1 and 2) is an
    # upstream error the audit already reports; what this pins is that DNB never adds one.
    rule("the same ISBN twice within one German line (not both from the Wikipedia table)",
         c("""SELECT COUNT(*) FROM (SELECT v.release_line_id, v.isbn13 FROM volume v
              JOIN release_line rl ON rl.id=v.release_line_id WHERE rl.market='DE' AND v.isbn13 IS NOT NULL
              GROUP BY 1,2 HAVING COUNT(*)>1 AND SUM(NOT EXISTS (SELECT 1 FROM claim w WHERE w.entity='volume'
                AND w.entity_id=v.id AND w.field='isbn13' AND w.source='wikipedia' AND w.value=v.isbn13)) > 0)"""))

    # export policy (decision 1): only high/medium links (and ISBN-proven lines) ship -- and a
    # line a person linked by a corrections/lines.json link_work entry (krcn-design R2)
    rule("exported DNB lines that are not merged / sibling / kept / high-or-medium linked",
         c("""SELECT COUNT(*) FROM dnb_line WHERE exported=1 AND NOT (role IN ('merged','sibling','kept')
              OR (role='linked' AND (tier IN ('high','medium') OR via='correction')))"""))
    held = {r[0] for r in cat.execute("SELECT rl_id FROM dnb_line WHERE exported=0")}
    rule("held-back DNB lines (review / unlinked) present in the artifact",
         sum(1 for t in have if t in held))

    # the linker, measured two ways (no ISBNs used by the linker in either)
    wrong = cat.execute("""SELECT name, link_work, truth_work FROM dnb_line WHERE truth_work IS NOT NULL
                           AND tier IN ('high','medium') AND link_work<>truth_work""").fetchall()
    n_gt, n_gt_linked = cat.execute("""SELECT COUNT(*), SUM(tier IN ('high','medium')) FROM dnb_line
                                       WHERE truth_work IS NOT NULL""").fetchone()
    rule("linker wrong on the ground-truth set (DNB lines that share ISBNs with a Wikipedia line)",
         len(wrong), str(wrong[:5]))
    print("  info  linker ground truth: %s lines, %s linked high/medium, %d wrong" % (n_gt, n_gt_linked or 0, len(wrong)))
    labels = json.load(open(os.path.join(fx, "dnb_linker_labels.json"), encoding="utf8"))["lines"]
    line_of = dict(cat.execute("SELECT idn, line_key FROM dnb_member"))
    verdict = {k: (t, w) for k, t, w in cat.execute("SELECT key, tier, link_work FROM dnb_line")}
    linked = correct = found = recall_hit = 0
    misses = []
    for lab in labels:
        keys = [line_of[i] for i in lab["member_idns"] if i in line_of]
        if lab["parent_idn"] and "dnb:" + lab["parent_idn"] in verdict:
            keys.append("dnb:" + lab["parent_idn"])
        if not keys:
            continue                    # the records are not volumes here (extras, bundles, dropped)
        found += 1
        key = max(set(keys), key=keys.count)
        tier, work = verdict.get(key, (None, None))
        if tier in ("high", "medium"):
            linked += 1
            correct += work == lab["expected_work"]
            if work != lab["expected_work"]:
                misses.append((lab["de"], work, lab["expected_work"]))
        recall_hit += bool(lab["expected_work"]) and tier in ("high", "medium") and work == lab["expected_work"]
    bad = []
    fixture = json.load(open(os.path.join(fx, "dnb_linker_labels.json"), encoding="utf8"))
    shipped = {k: w for k, w in cat.execute("""SELECT d.key, rl.work_id FROM dnb_line d
                   JOIN release_line rl ON rl.id=d.rl_id WHERE d.exported=1""")}
    for m in fixture.get("must_not_link", []):
        t, w = verdict.get(m["key"], (None, None))
        if (t in ("high", "medium") and w == m["wrong_work"]) or shipped.get(m["key"]) == m["wrong_work"]:
            bad.append(m["de"])
    rule("confirmed-wrong links linked or exported (any role, any tier; fixture must_not_link)",
         len(bad), str(bad))
    prec = correct / linked if linked else 0.0
    rule("linker precision on the spike's hand-labelled lines below 95%", 0 if prec >= 0.95 else 1,
         "(%d/%d; wrong: %s)" % (correct, linked, misses))
    print("  info  linker on the labelled set: %d of %d lines found, %d linked, %d correct (%.1f%%), "
          "recall %d/%d" % (found, len(labels), linked, correct, 100 * prec, recall_hit,
                            sum(1 for l in labels if l["expected_work"])))
    for m in misses:
        print("        labelled wrong: %s -> %s (expected %s)" % m)


def run_link_work(catalogue):
    """corrections/lines.json link_work entries (R2): each names a library line this build has, and
    that line ships under the corrected work -- linked or kept, or merged / sibling by ISBN when
    the ISBNs agree (the join resolves merged to the Wikipedia line's work); a different work
    fails. A key the build does not have is reported (stale), not failed: DNB can renumber a set."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tier2"))
    import corrections as CORR
    cat = sqlite3.connect(catalogue)
    want = CORR.load_link_work()
    rows = {}
    for table in ("dnb_line", "krcn_line"):         # both carry key, role and rl_id
        try:
            rows.update({k: (r, w) for k, r, w in cat.execute(
                "SELECT d.key, d.role, rl.work_id FROM %s d LEFT JOIN release_line rl ON rl.id=d.rl_id" % table)})
        except sqlite3.OperationalError:
            pass
    ships = ("linked", "kept", "merged", "sibling")
    wrong = [k for k, w in want.items() if k in rows and (rows[k][0] not in ships or rows[k][1] != w)]
    rule("link_work corrections not applied (line not linked under the corrected work)", len(wrong), str(wrong[:5]))
    stale = [k for k in want if k not in rows]
    if stale:
        print("  info  link_work keys this build does not have (stale): %s" % stale[:10])


LCCN_URL = re.compile(r"^https://lccn\.loc\.gov/[a-z]{0,3}[0-9]+$")
ARK_URL = re.compile(r"^https://catalogue\.bnf\.fr/ark:/12148/cb[0-9]{8}[0-9a-z]$")
DNB_URL = re.compile(r"^https://d-nb\.info/[0-9]{8,9}[0-9Xx]$")
# tier1/enrich_more.enrich_bnf's per-ISBN lookup: the only other shape a bnf claim's source_url has
BNF_ISBN_URL = re.compile(r"^https://catalogue\.bnf\.fr/api/SRU\?query=bib\.isbn\+all\+%22[0-9Xx-]+%22$")
BNF_ENRICH_FIELDS = {"volume_number", "page_count"}      # what enrich_bnf writes
# The fields each library may write -- an ALLOWLIST: any other field from these sources fails.
# dnb: measured on build/opentome.db (2026-09-27, exactly these 7); loc / bnf line sources: what stage 3f's
# load writes (plan Task 14 _claim / _volume_claims: line_name, publisher on the line; isbn13,
# release_date | projected_date, page_count, volume_number on a volume); bnf enrichment: a subset.
DNB_FIELDS = {"isbn13", "line_name", "page_count", "projected_date", "publisher", "release_date", "volume_number"}
LOC_FIELDS = {"isbn13", "line_name", "page_count", "projected_date", "publisher", "release_date", "volume_number"}
BNF_FIELDS = {"isbn13", "line_name", "page_count", "projected_date", "publisher", "release_date", "volume_number"}
LIB_FIELDS = {"dnb": DNB_FIELDS, "loc": LOC_FIELDS, "bnf": BNF_FIELDS}
# library cover hosts: DNB serves covers from portal.dnb.de/opac/mvb/cover and services.dnb.de
# (docs/dnb-design.md), BnF from catalogue.bnf.fr, LoC from *.loc.gov
LIB_HOSTS = ("d-nb.info", "dnb.de", "bnf.fr", "loc.gov")


def is_link(v):
    """A claim value that is (or embeds) a link: '://' or 'www.' anywhere, or a leading '//'."""
    v = (v or "").strip().lower()
    return "://" in v or v.startswith("//") or "www." in v


def run_krcn_licence(path, catalogue):
    """THE KR/CN licence gate (docs/krcn-design.md §2, §13; controller rulings 4 and 5) and the R6 id
    rule -- the single one: Task 15's run_krcn must call this, not duplicate it. Catalogue-side: the
    artifact carries no per-claim provenance.
      - dnb / loc / bnf claims only in their field allowlist (LIB_FIELDS): no cover, no 856 link, no
        summary or blurb can slip in under a new field name;
      - licence: loc us_gov_pd; the url: loc https://lccn.loc.gov/<LCCN>, dnb https://d-nb.info/<IDN>
        (anchored: no /04 cover or TOC path), bnf an ark URL -- enrich_bnf's per-ISBN SRU URL only on
        an enrichment entity (its bnf claims all volume_number / page_count, none an ark, and not a
        krcn_member volume of a bnf line);
      - no claim value that is or embeds a link ('://' or 'www.' anywhere, a leading '//'); no artifact
        cover_url on a library host (LIB_HOSTS); sources and cover_source compared case-insensitively;
      - no isbn13_alt column; meta.attribution names the Library of Congress;
      - R6: a held / review / unlinked KR/CN line holds no id anywhere."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schema"))
    from load import _id
    db = sqlite3.connect(path)
    cat = sqlite3.connect(catalogue)
    # source compared lowered throughout: a 'DNB' claim must not escape the gate
    rows = cat.execute("""SELECT entity, entity_id, field, value, lower(source), source_url, licence FROM claim
                          WHERE lower(source) IN ('dnb','loc','bnf')""").fetchall()
    bad = sorted({(s, f) for _, _, f, _, s, _, _ in rows if f not in LIB_FIELDS[s]})
    rule("dnb / loc / bnf claims outside the source's field allowlist", len(bad), str(bad[:5]))
    bad = [v for _, _, _, v, _, _, _ in rows if is_link(v)]
    rule("dnb / loc / bnf claims whose value is a link", len(bad), str(bad[:3]))
    rule("loc claims not licensed us_gov_pd (DLC-created records only)",
         sum(1 for *_, s, _, l in rows if s == "loc" and l != "us_gov_pd"))
    bad = [u for *_, s, u, _ in rows if s == "loc" and not LCCN_URL.match(u or "")]
    rule("loc claims whose source_url is not https://lccn.loc.gov/<LCCN>", len(bad), str(bad[:3]))
    bad = [u for *_, s, u, _ in rows if s == "dnb" and not DNB_URL.match(u or "")]
    rule("dnb claims whose source_url is not https://d-nb.info/<IDN>", len(bad), str(bad[:3]))
    line_src = {(e, i) for e, i, f, _, s, u, _ in rows
                if s == "bnf" and (e != "volume" or f not in BNF_ENRICH_FIELDS or ARK_URL.match(u or ""))}
    # a volume staged by a BnF KR/CN line (krcn_member) IS line-source, even when its only bnf claims
    # look like enrichment (volume_number / page_count on the per-ISBN SRU url): ark urls only
    try:
        line_src |= {("volume", v) for (v,) in cat.execute(
            """SELECT m.volume_id FROM krcn_member m JOIN krcn_line k ON k.key=m.line_key
               WHERE m.volume_id IS NOT NULL AND lower(k.source)='bnf'""")}
    except sqlite3.OperationalError:
        pass                            # no stage 3f staging in this catalogue
    bad = [u for e, i, f, _, s, u, _ in rows if s == "bnf" and not (
        ARK_URL.match(u or "") or ((e, i) not in line_src and BNF_ISBN_URL.match(u or "")))]
    rule("bnf claims whose source_url is not an ark URL (the per-ISBN lookup: enrichment only)", len(bad),
         str(bad[:3]))
    rule("artifact covers from dnb / loc / bnf (source or host)", db.execute(
        "SELECT COUNT(*) FROM volumes WHERE lower(cover_source) IN ('dnb','loc','bnf') OR " +
        " OR ".join("cover_url LIKE '%%%s%%'" % h for h in LIB_HOSTS)).fetchone()[0])
    cols = [(t, c[1]) for (t,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            for c in db.execute("PRAGMA table_info(%s)" % t) if c[1] == "isbn13_alt"]
    rule("artifact columns named isbn13_alt (alternative ISBNs are not exported)", len(cols), str(cols))
    attr = (db.execute("SELECT value FROM meta WHERE key='attribution'").fetchone() or [""])[0]
    rule("meta.attribution does not name the Library of Congress", 0 if "Library of Congress" in attr else 1)
    # R6 (§13): a held / review / unlinked line holds no id anywhere. krcn_line.rl_id is NULL for it
    # (build_krcn.staged_rl_id), so its own-key id is re-derived and looked for; a carried line that
    # does not export is 7b's (redirect / retirement), not this rule's
    try:
        rows = cat.execute("SELECT key, rl_id, work, carried FROM krcn_line WHERE exported=0").fetchall()
    except sqlite3.OperationalError:
        return
    rule("non-exported krcn_line rows holding a tome_id or a work", sum(1 for _, r, w, _ in rows if r or w))
    mint = {_id("rl_", k) for k, _, _, carried in rows if not carried}
    ids = json.loads((db.execute("SELECT value FROM meta WHERE key='krcn_ids'").fetchone() or ["{}"])[0])
    held = sorted(mint & ({r[0] for r in cat.execute("SELECT id FROM release_line")}
                          | {r[0] for r in db.execute("SELECT tome_id FROM series")}
                          | {r[0] for r in db.execute("SELECT opentome_id FROM id_map WHERE kind<>'retired'")}
                          | set(ids.get("lines", {}))))
    rule("held / review / unlinked KR/CN line ids in release_line, series, id_map or meta.krcn_ids", len(held),
         str(held[:5]))


MAX_NEW_LIBRARY_WORKS = 20       # a refresh build (docs/krcn-design.md §9 flood gate; the MAX_MOVED_IDS pattern)
KRCN_FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
COMIC = ("manga", "manhwa", "manhua", "webtoon")
SHIPS = ("linked", "merged", "sibling", "adopting", "kept")


def _meta(d, k):
    try:
        return (d.execute("SELECT value FROM meta WHERE key=?", (k,)).fetchone() or [None])[0]
    except sqlite3.OperationalError:
        return None


def run_krcn(path, catalogue, carry=None):
    """The KR/CN contract (docs/krcn-design.md §13). Calls run_krcn_licence -- THE licence and R6 id
    gate (per-source field allowlists = no loc 520 / 856 / 955 and no cover / summary field; loc
    us_gov_pd; anchored lccn / d-nb / ark urls with bnf line sources ark-only; no links in values; no
    library covers; no isbn13_alt; the LoC attribution; a held / review / unlinked line holds no id
    anywhere) -- and adds only what it does not cover: DLC provenance through loc_member, clean_claim,
    the library dates, the works a build creates, never-demoted carried lines, the flood gate, novels,
    disjoint keys, taken_weak, carried volumes' ISBNs, and the fixtures (P19 / P21). Provenance is read
    from the catalogue (claims, krcn_line / krcn_member / loc_member, meta krcn:stats); the artifact
    carries meta.krcn_ids; the carry is opened read-only."""
    db, cat = sqlite3.connect(path), sqlite3.connect(catalogue)
    g = lambda q, *a: db.execute(q, a).fetchone()[0]
    c = lambda q, *a: cat.execute(q, a).fetchone()[0]
    try:
        c("SELECT COUNT(*) FROM krcn_line")
    except sqlite3.OperationalError:
        rule("KR/CN staging missing from the catalogue (stage 3f did not run)", 1)
        return
    run_krcn_licence(path, catalogue)
    ids = json.loads(_meta(db, "krcn_ids") or "{}")
    created = ids.get("created", [])
    C = sqlite3.connect("file:%s?mode=ro" % carry, uri=True) if carry and os.path.exists(carry) else None
    carried_ids = json.loads(_meta(C, "krcn_ids") or "null") if C else None
    url = "'https://lccn.loc.gov/' || m.lccn = x.source_url"
    # provenance: LoC-created records only (the 040 $a of the record each loc claim cites)
    rule("loc_member rows whose 040 $a is not DLC", c("SELECT COUNT(*) FROM loc_member WHERE f040a<>'DLC'"))
    rule("loc claims whose record is not a DLC loc_member", c(
        """SELECT COUNT(*) FROM claim x WHERE lower(x.source)='loc'
           AND NOT EXISTS (SELECT 1 FROM loc_member m WHERE %s AND m.f040a='DLC')""" % url))
    rule("clean_claim misses loc claims (us_gov_pd must be in the commercial subset)",
         c("SELECT COUNT(*) FROM claim WHERE lower(source)='loc'")
         - c("SELECT COUNT(*) FROM clean_claim WHERE lower(source)='loc'"))
    # dates (dnb's precision rules are run_dnb's)
    rule("loc date claims from a set record", c("""SELECT COUNT(*) FROM claim x JOIN loc_member m ON %s
         WHERE lower(x.source)='loc' AND x.field IN ('release_date','projected_date') AND m.set_record=1""" % url))
    rule("loc published dates from a record at encoding level 5 / 8", c("""SELECT COUNT(*) FROM claim x
         JOIN loc_member m ON %s WHERE lower(x.source)='loc' AND x.field='release_date'
         AND m.encoding_level IN ('5','8')""" % url))
    rule("loc / bnf published dates not year precision", c("""SELECT COUNT(*) FROM claim WHERE
         lower(source) IN ('loc','bnf') AND field='release_date' AND value NOT GLOB '[12][0-9][0-9][0-9]'"""))
    rule("loc / bnf projected dates not month precision", c("""SELECT COUNT(*) FROM claim WHERE
         lower(source) IN ('loc','bnf') AND field='projected_date' AND value NOT GLOB '[12][0-9][0-9][0-9]-[01][0-9]'"""))
    rule("volumes dated from a 263 1111", c("""SELECT COUNT(*) FROM claim x JOIN loc_member m ON %s
         WHERE lower(x.source)='loc' AND x.field='projected_date' AND m.f263='1111'""" % url))
    # works created in this build (§9; R6)
    rule("library-created works without a line of explicit KR/CN origin", sum(
        1 for w in created if not c("SELECT COUNT(*) FROM krcn_line WHERE work=? AND exported=1 AND explicit=1", w)))
    rule("library-created works without a comic line", sum(1 for w in created if not c(
        "SELECT COUNT(*) FROM release_line WHERE work_id=? AND medium IN (%s)" % ",".join("?" * len(COMIC)), w, *COMIC)))
    rule("library-created works with a Japanese line", sum(1 for w in created if c(
        "SELECT COUNT(*) FROM release_line WHERE work_id=? AND market='JP' AND medium NOT IN ('manhwa','manhua','webtoon')", w)))
    rule("R6: library works created in this build exported without an English line", sum(
        1 for w in created if not g("SELECT COUNT(*) FROM series WHERE tome_work_id=? AND language='en'", w)))
    art_ids = {r[0] for r in db.execute("SELECT tome_id FROM series")}
    if carried_ids is not None:
        try:
            red = {r[0] for r in db.execute("SELECT old_tome_id FROM id_redirect")}
        except sqlite3.OperationalError:
            red = set()
        gone = sorted(t for t in carried_ids.get("lines", {}) if t not in art_ids and t not in red)
        rule("published KR/CN lines absent from the artifact (never demoted to held)", len(gone), str(gone[:5]))
        new = sorted(set(created) - set(carried_ids.get("works", [])))
        rule("more than %d new library works in a refresh build (flood gate)" % MAX_NEW_LIBRARY_WORKS,
             0 if len(new) <= MAX_NEW_LIBRARY_WORKS else len(new), str(new[:5]))
    novel_bad = 0
    for t in ids.get("lines", {}):
        row = db.execute("SELECT tome_work_id, medium FROM series WHERE tome_id=?", (t,)).fetchone()
        if row and row[1] == "novel" and not g("SELECT COUNT(*) FROM series WHERE tome_work_id=? AND medium IN (%s)"
                                               % ",".join("?" * len(COMIC)), row[0], *COMIC):
            novel_bad += 1
    rule("KR/CN novel lines in a work without a comic line", novel_bad)
    try:
        rule("dnb_line and krcn_line keys overlap", c("SELECT COUNT(*) FROM krcn_line k JOIN dnb_line d ON d.key=k.key"))
    except sqlite3.OperationalError:
        pass
    # ids: step-2 takes without a strict ISBN majority (krcn_identity.line_ids; build_krcn.gate_report
    # drops 0-of-0 takes) block until a person confirms them in the linker fixture's "taken_ok"
    fx = lambda n: json.load(open(os.path.join(KRCN_FIXTURES, n), encoding="utf8"))
    labels = fx("krcn_linker_labels.json")
    try:
        gate = json.loads(_meta(cat, "krcn:stats"))["gate"]
    except (TypeError, ValueError, KeyError):
        gate = None
    if gate is None:
        rule("catalogue meta krcn:stats (the gate lists) missing: taken_weak unreadable", 1)
    else:
        ok = {tuple(p) for p in labels.get("taken_ok", [])}
        weak = [t for t in gate.get("taken_weak", []) if (t[1], t[0]) not in ok]
        rule("step-2 takes of a carried id without a strict ISBN majority (taken_weak), not confirmed in "
             "krcn_linker_labels.json taken_ok", len(weak), str(weak[:5]))
        for k in sorted(gate):
            if gate[k] and k != "taken_weak":
                print("  info  gate list %s (review, not failed): %d %s" % (k, len(gate[k]), json.dumps(gate[k][:3])))
    if C is not None:
        bad = carried_isbn_moved(db, cat, C, ids, carried_ids)
        rule("carried KR/CN-scope volumes whose carried ISBN now sits on another present volume", len(bad), str(bad[:3]))
    # fixtures
    pre = [l["tome_id"] for l in fx("krcn_lines_pre.json")["lines"]]
    rule("pre-round KR/CN line ids (and the library-fixture lines) missing", sum(1 for t in pre if t not in art_ids),
         str([t for t in pre if t not in art_ids][:5]))
    verdict = {k: (r, w) for k, r, w in cat.execute("SELECT key, role, work FROM krcn_line")}
    wrong = [m["key"] for m in labels.get("must_link", []) if m["key"] in verdict and
             (verdict[m["key"]][0] not in SHIPS or verdict[m["key"]][1] != m["expected_work"])]
    rule("KR/CN linker fixture: must_link lines not linked to the expected work", len(wrong),
         str([(k, verdict[k]) for k in wrong[:5]]))
    bad = [m["key"] for m in labels.get("must_not_link", []) if verdict.get(m["key"], (None, None))[1] == m["wrong_work"]]
    rule("KR/CN linker fixture: must_not_link lines linked to the wrong work", len(bad), str(bad[:5]))
    missing = [m["key"] for m in labels.get("must_link", []) + labels.get("must_not_link", []) if m["key"] not in verdict]
    if missing:
        print("  info  linker fixture keys this build does not have: %s" % missing[:10])
    nw = fx("krcn_new_works.json")["works"]
    works_out = set(ids.get("works", []))
    rule("new-work fixture: must_not_create works exported",
         sum(1 for w, e in nw.items() if e["verdict"] == "must_not_create" and w in works_out))
    rule("new-work fixture: must_create works missing",
         sum(1 for w, e in nw.items() if e["verdict"] == "must_create" and w not in works_out))
    unlabelled = [w for w in created if w not in nw]
    if carried_ids is None:
        rule("new-work fixture: new works of the first KR/CN build not labelled (build/krcn-new-works.tsv)",
             len(unlabelled), str(unlabelled[:5]))
    elif unlabelled:
        print("  info  new library works not in the fixture (reported, not failed after the first build): %s" % unlabelled)
    roles = dict(cat.execute("SELECT market || ' ' || role, COUNT(*) FROM krcn_line GROUP BY 1"))
    print("  info  KR/CN lines: %s; works created %d, exported %d" % (json.dumps(roles, sort_keys=True), len(created), len(works_out)))


def carried_isbn_moved(db, cat, C, ids, carried_ids):
    """A present carried volume id whose carried ISBN now sits on ANOTHER present volume -- one that
    did not already hold it in the carry (controller ruling, Task 11: an ISBN moving off a published
    volume id is an id-contract break 7b cannot see). Scope: carried volumes of KR/CN lines (the
    carry's and this build's meta krcn_ids, the catalogue's exported krcn_line rows) and of the lines
    of every work a KR/CN line touches. -> [(volume id, isbn, [other volume ids])]."""
    lines = set(ids.get("lines", {})) | set((carried_ids or {}).get("lines", {}))
    works = set(ids.get("works", [])) | set((carried_ids or {}).get("works", []))
    for rid, w in cat.execute("SELECT rl_id, work FROM krcn_line WHERE exported=1"):
        lines.add(rid)
        works.add(w)
    cols = {r[1] for r in C.execute("PRAGMA table_info(series)")}
    wcol = "s.tome_work_id" if "tome_work_id" in cols else "NULL"
    held_then = {}
    scope = []
    for vid, isbn, tid, w in C.execute("""SELECT v.tome_id, v.isbn13, s.tome_id, %s FROM volumes v
                                          JOIN series s USING(gcd_series_id) WHERE v.isbn13 IS NOT NULL""" % wcol):
        held_then.setdefault(isbn, set()).add(vid)
        if tid in lines or w in works:
            scope.append((vid, isbn))
    now = {}
    for vid, isbn in db.execute("SELECT tome_id, isbn13 FROM volumes WHERE isbn13 IS NOT NULL"):
        now.setdefault(isbn, set()).add(vid)
    present = {r[0] for r in db.execute("SELECT tome_id FROM volumes")}
    out = []
    for vid, isbn in scope:
        others = now.get(isbn, set()) - {vid} - held_then.get(isbn, set())
        if vid in present and others:
            out.append((vid, isbn, sorted(others)))
    return sorted(out)


if __name__ == "__main__":
    fails = run(sys.argv[1])
    if len(sys.argv) > 2:
        print("\n  -- German (DNB) rules, catalogue %s --" % sys.argv[2])
        run_dnb(sys.argv[1], sys.argv[2])
        run_link_work(sys.argv[2])
        print("\n  -- KR/CN rules (licence, R6, provenance, dates, works, ids, fixtures) --")
        run_krcn(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] else None)
    if len(sys.argv) > 3 and sys.argv[3] and os.path.exists(sys.argv[3]):
        print("\n  -- ids, carried artifact %s --" % sys.argv[3])
        run_ids(sys.argv[1], sys.argv[3])
    print()
    if fails:
        print(f"{len(fails)} contract rule(s) FAILED: {fails}")
        sys.exit(1)
    print("artifact contract ok")
