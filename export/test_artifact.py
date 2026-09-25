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


def run_ids(path, carry):
    """IDs are a public contract: every German line and volume id of the carried (last
    published) artifact is still present here, or resolves through this artifact's id_redirect
    to one that is."""
    db = sqlite3.connect(path)
    C = sqlite3.connect(carry)
    try:
        old = [r[0] for r in C.execute("""SELECT tome_id FROM series WHERE language='de' UNION
                   SELECT v.tome_id FROM volumes v JOIN series s USING(gcd_series_id) WHERE s.language='de'""")]
    except sqlite3.OperationalError:
        old = []
    present = {r[0] for r in db.execute("SELECT tome_id FROM series UNION SELECT tome_id FROM volumes")}
    try:    # a merged work's redirect targets a work id (tier0/carried_ids.py)
        present |= {r[0] for r in db.execute("SELECT DISTINCT tome_work_id FROM series")}
    except sqlite3.OperationalError:
        pass
    try:
        red = dict(db.execute("SELECT old_tome_id, new_tome_id FROM id_redirect"))
    except sqlite3.OperationalError:
        red = {}
    lost = [t for t in old if t and t not in present and red.get(t) not in present]
    rule("German ids of the carried artifact neither present nor redirected", len(lost), str(lost[:5]))
    # A redirect keeps an id resolvable; it does not make losing the volume right. More than a
    # handful of carried German volumes gone in one build is a DNB outage, a clustering change or
    # a linker change -- stop and look before it ships (N1, 2026-09-24 re-review).
    gone = [t for t in old if t and t.startswith("v_") and t not in present]
    rule("more than %d carried German volumes retired in one build" % MAX_RETIRED_DE_VOLUMES,
         0 if len(gone) <= MAX_RETIRED_DE_VOLUMES else len(gone), str(gone[:5]))
    rule("id_redirect rows whose target is not in the artifact",
         sum(1 for t in red.values() if t not in present))
    print("  info  carried German ids: %s, redirected: %s" % (
        format(len(old), ","), format(sum(1 for t in old if t in red), ",")))


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

    # export policy (decision 1): only high/medium links (and ISBN-proven lines) ship
    rule("exported DNB lines that are not merged / sibling / kept / high-or-medium linked",
         c("""SELECT COUNT(*) FROM dnb_line WHERE exported=1 AND NOT (role IN ('merged','sibling','kept')
              OR (role='linked' AND tier IN ('high','medium')))"""))
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


if __name__ == "__main__":
    fails = run(sys.argv[1])
    if len(sys.argv) > 2:
        print("\n  -- German (DNB) rules, catalogue %s --" % sys.argv[2])
        run_dnb(sys.argv[1], sys.argv[2])
    if len(sys.argv) > 3 and sys.argv[3] and os.path.exists(sys.argv[3]):
        print("\n  -- ids, carried artifact %s --" % sys.argv[3])
        run_ids(sys.argv[1], sys.argv[3])
    print()
    if fails:
        print(f"{len(fails)} contract rule(s) FAILED: {fails}")
        sys.exit(1)
    print("artifact contract ok")
