"""Apply hand-checked corrections. See `corrections/README.md`.

Two things make this different from editing the database by hand, which is what
it replaces:

  * **It survives a rebuild.** The catalogue is rebuilt from scratch into a new
    file, so any value typed into the old one is gone. A correction is applied
    as a pipeline stage, every time.
  * **It is checked.** A correction whose target no longer exists fails the
    build instead of silently doing nothing -- this project's recurring bug is
    an operation that reports success and changes nothing.

Volume corrections are written TWICE, on purpose: to `override` (where
`tier2/resolve.py` ranks them above every source, so the confidence layer
reports `manual_override` and the provenance is honest) and onto the `volume`
row (which is what the exporter actually reads). Writing only one of the two
produces a correction that is either invisible to consumers or invisible to the
audit trail.

`--check [DIR] [--artifact PATH]` is the pull-request check: the same
validation, resolved against a PUBLISHED artifact (manga-metadata.sqlite) instead
of the pipeline database, so a contributor and CI can run it with nothing but
the repository and one download. It writes nothing.
"""
import argparse, datetime, json, os, re, sqlite3, sys
from urllib.request import pathname2url

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, "corrections")
NOW = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

VOLUME_FIELDS = {"release_date", "isbn13", "page_count", "title", "cover_url"}
ORIGIN_MARKETS = ("JP", "KR", "CN", "TW")
VOLUME_KEYS = ("volume", "field", "value", "source_url", "checked")
LINE_KEYS = ("work", "market", "medium", "name", "volumes", "source_url", "checked")
ALIAS_KEYS = ("line", "alias", "source_url", "checked")
# A whole WORK the catalogue should not carry at all (2026-09-23 cleanup): a work
# that entered through a Wikipedia list-of-volumes page but is not in scope (The
# Walking Dead, a US comic -- Arrietty (Comics), a legitimate Japanese Ghibli
# film comic, is NOT this). Keyed on the work id tier 0 computes (`w_...`),
# stable across rebuilds the same way the medium override's line id is.
EXCLUDED_KEYS = ("work", "source_url", "checked")
ARTIFACT_URL = "https://github.com/DrAwesome441/mangarr-metadata/releases/download/metadata/manga-metadata.sqlite"

sys.path.insert(0, os.path.join(ROOT, "schema"))
sys.path.insert(0, os.path.join(ROOT, "tier0"))
from load import _id, LICENCE, MARKET_LANG        # noqa: E402  (ids must match the loader's)
from isbn import isbn_market, normalise_isbn      # noqa: E402
from release_lines import MEDIUM_HINTS            # noqa: E402  (canonical medium names)

# A medium OVERRIDE entry (2026-09-23 follow-up, the Denma orig_series_id defect):
# unlike a normal lines.json entry, which ADDS a release line the sources don't
# carry, this retags the `medium` of a line that already exists -- keyed on the
# line's own id (never on work/medium/market/name, which is what a normal entry's
# id is HASHED from: computing a fresh id from an overridden medium would not
# match the real line and would create a duplicate, id-contract-breaking row).
# Recognised by the absence of "volumes" (a normal entry always has a non-empty
# one -- see LINE_KEYS/_require). Applied as a plain UPDATE, so the line's id
# never changes.
MEDIUM_KEYS = ("line", "medium", "source_url", "checked")
# The canonical medium names tier0/release_lines.py's detect_medium() ever
# assigns. 'webtoon' is deliberately NOT included even though to_mangarr.py's
# MEDIUM_ORIGIN_HINT recognises it as a hint key: tier0 always canonicalises a
# webtoon heading to 'manhwa' (MEDIUM_HINTS maps both to the same name), so no
# release_line ever carries medium='webtoon' -- an override to it would put that
# one line in a (work, medium) group of its own instead of joining its manhwa
# counterparts (review round 1, finding 8).
KNOWN_MEDIA = {name for name, _ in MEDIUM_HINTS}


def _read(name, directory=DIR):
    path = os.path.join(directory, name)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("%s must be a JSON array" % path)
    return data


def _require(entry, keys, name, i):
    missing = [k for k in keys if not entry.get(k)]
    if missing:
        raise ValueError("%s[%d] is missing %s -- a correction without a source "
                         "is a guess (see corrections/README.md)"
                         % (name, i, ", ".join(missing)))


def load_aliases(directory=None):
    """-> [(release_line_id, alias)] after validation. Add-only: an entry with
    `"remove": true` is a curated removal (see load_alias_removals) and is
    skipped here, so it is never re-inserted as if it were a normal addition.
    `directory` is test-only (mirrors check()'s parameter); every real caller
    reads the repo's own corrections/."""
    out = []
    for i, e in enumerate(_read("aliases.json", directory or DIR)):
        _require(e, ALIAS_KEYS, "aliases.json", i)
        if e.get("remove"):
            continue
        out.append((e["line"], e["alias"]))
    return out


def load_alias_removals(directory=None):
    """-> [(release_line_id, alias)] for aliases.json entries marked
    `"remove": true` (2026-09-23 cleanup, item 2): a curated, exact-string
    removal of a specific bad alias the export's own fan-out generated --
    NOT a rule (the automated 'drop anything that collides with a volume
    title' pass was tried and reverted; see HANDOFF and the followups-0923
    review). Keyed on the exact line + alias string, same required keys as
    a normal aliases.json entry (a removal needs a source and a checked date
    just as much as an addition does)."""
    out = []
    for i, e in enumerate(_read("aliases.json", directory or DIR)):
        _require(e, ALIAS_KEYS, "aliases.json", i)
        if e.get("remove"):
            out.append((e["line"], e["alias"]))
    return out


def load_exclusions(directory=None):
    """-> [work_id] after validation (corrections/excluded.json)."""
    out = []
    for i, e in enumerate(_read("excluded.json", directory or DIR)):
        _require(e, EXCLUDED_KEYS, "excluded.json", i)
        out.append(e["work"])
    return out


def _precision(value):
    return "day" if len(value) == 10 else "month" if len(value) == 7 else "year"


def apply_exclusions(db, entries=None, verbose=True):
    """Remove a whole work the catalogue should not carry at all (corrections/
    excluded.json). The case: 'The Walking Dead (comic book)' entered through a
    Wikipedia list-of-volumes page even though it is a US comic, out of scope
    for a manga/light-novel/manhwa/manhua catalogue.

    Keyed on the work id (`w_...`) tier 0 computes -- stable across a rebuild
    the same way a medium override's line id is: reprocessing the SAME Wikipedia
    article recomputes the same id, so the exclusion keeps applying; if the work
    is ever merged or reclassified upstream, the id changes and this fails
    loudly (STALE CORRECTION) instead of silently doing nothing.

    Deletes every row the work owns -- its release lines, their volumes and
    compositions, and every claim/override/external_id attached to any of
    those entities plus the work itself. Aliases and volumes "go with the
    line": once the release_line row is gone, nothing later in the pipeline
    (export's own alias fan-out included) has anything left to read."""
    c = db.cursor()
    entries = _read("excluded.json") if entries is None else entries
    n = 0
    for i, e in enumerate(entries):
        _require(e, EXCLUDED_KEYS, "excluded.json", i)
        wid = e["work"]
        if not c.execute("SELECT 1 FROM work WHERE id=?", (wid,)).fetchone():
            print("\n  STALE CORRECTION -- excluded.json[%d]: work %s is not in the catalogue"
                  % (i, wid), flush=True)
            raise SystemExit(1)
        line_ids = [r[0] for r in c.execute("SELECT id FROM release_line WHERE work_id=?", (wid,))]
        vol_ids = []
        if line_ids:
            qs = ",".join("?" * len(line_ids))
            vol_ids = [r[0] for r in c.execute(
                "SELECT id FROM volume WHERE release_line_id IN (%s)" % qs, line_ids)]
        if vol_ids:
            qs = ",".join("?" * len(vol_ids))
            c.execute("DELETE FROM composition WHERE volume_id IN (%s)" % qs, vol_ids)
            c.execute("DELETE FROM claim WHERE entity='volume' AND entity_id IN (%s)" % qs, vol_ids)
            c.execute("DELETE FROM override WHERE entity='volume' AND entity_id IN (%s)" % qs, vol_ids)
            c.execute("DELETE FROM external_id WHERE entity='volume' AND entity_id IN (%s)" % qs, vol_ids)
            c.execute("DELETE FROM volume WHERE id IN (%s)" % qs, vol_ids)
        if line_ids:
            qs = ",".join("?" * len(line_ids))
            c.execute("DELETE FROM composition WHERE ref_line_id IN (%s)" % qs, line_ids)
            c.execute("DELETE FROM claim WHERE entity='release_line' AND entity_id IN (%s)" % qs, line_ids)
            c.execute("DELETE FROM override WHERE entity='release_line' AND entity_id IN (%s)" % qs, line_ids)
            c.execute("DELETE FROM external_id WHERE entity='release_line' AND entity_id IN (%s)" % qs, line_ids)
            c.execute("DELETE FROM release_line WHERE id IN (%s)" % qs, line_ids)
        c.execute("DELETE FROM claim WHERE entity='work' AND entity_id=?", (wid,))
        c.execute("DELETE FROM override WHERE entity='work' AND entity_id=?", (wid,))
        c.execute("DELETE FROM external_id WHERE entity='work' AND entity_id=?", (wid,))
        c.execute("DELETE FROM work_title WHERE work_id=?", (wid,))
        c.execute("DELETE FROM chapter WHERE work_id=?", (wid,))
        c.execute("DELETE FROM work_relation WHERE from_work_id=? OR to_work_id=?", (wid, wid))
        c.execute("DELETE FROM work WHERE id=?", (wid,))
        n += 1
    db.commit()
    if verbose:
        print("  excluded works removed             %8s" % format(n, ","))
    return n


def apply_line_corrections(db, entries=None, verbose=True):
    """Add a release line the sources do not carry, from a hand-checked volume list.

    The case: an English edition that is on no Wikipedia article (Mushoku
    Tensei: Roxy Gets Serious -- Seven Seas, 12 volumes, absent from the en
    list article, and the publisher's site refuses robots). The pipeline cannot
    invent it; a person can read it off the publisher's page.

    The line gets the SAME id the loader would have given it (`_id` over work,
    medium, market, name), so if a source later carries the edition the two
    meet instead of duplicating, and Mangarr's series id never changes. Each
    value is written as a claim (so the resolver has something to resolve), an
    override (so the confidence layer reports `manual_override`) and onto the
    row (so the export sees it). Volumes may say which original-market volumes
    they contain, which is the cross-market mapping everything else uses.
    """
    c = db.cursor()
    entries = _read("lines.json") if entries is None else entries
    n_lines = n_vols = n_medium = 0
    for i, e in enumerate(entries):
        if "volumes" not in e:
            _require(e, MEDIUM_KEYS, "lines.json", i)
            line, medium = e["line"], e["medium"]
            if medium not in KNOWN_MEDIA:
                raise ValueError("lines.json[%d]: unknown medium %r (%s)"
                                 % (i, medium, ", ".join(sorted(KNOWN_MEDIA))))
            if not c.execute("SELECT 1 FROM release_line WHERE id=?", (line,)).fetchone():
                print("\n  STALE CORRECTION -- lines.json[%d]: line %s is not in the catalogue"
                      % (i, line), flush=True)
                raise SystemExit(1)
            c.execute("UPDATE release_line SET medium=?, updated_at=? WHERE id=?", (medium, NOW, line))
            n_medium += 1
            continue
        _require(e, LINE_KEYS, "lines.json", i)
        wid, market, medium = e["work"], e["market"].upper(), e["medium"]
        name = e["name"].strip()
        if market not in MARKET_LANG:
            raise ValueError("lines.json[%d]: unknown market %r" % (i, market))
        if not c.execute("SELECT 1 FROM work WHERE id=?", (wid,)).fetchone():
            print("\n  STALE CORRECTION -- lines.json[%d]: work %s is not in the catalogue"
                  % (i, wid), flush=True)
            raise SystemExit(1)
        origin = c.execute("""SELECT id FROM release_line WHERE work_id=? AND medium=?
                              AND market IN (?,?,?,?) ORDER BY CASE market
                              WHEN 'JP' THEN 0 WHEN 'KR' THEN 1 ELSE 2 END LIMIT 1""",
                           (wid, medium) + ORIGIN_MARKETS).fetchone()
        origin = origin[0] if origin else None
        reason = "%s | %s" % (e.get("reason", "hand-checked"), e["source_url"])
        author = e.get("author", "corrections/lines.json")

        rid = _id("rl_", wid, medium, market, name)
        c.execute("""INSERT OR IGNORE INTO release_line
                     (id,work_id,medium,market,language,publisher,created_at,updated_at)
                     VALUES(?,?,?,?,?,?,?,?)""",
                  (rid, wid, medium, market, MARKET_LANG[market], e.get("publisher"), NOW, NOW))
        c.execute("UPDATE release_line SET publisher=COALESCE(?, publisher), updated_at=? WHERE id=?",
                  (e.get("publisher"), NOW, rid))
        c.execute("""INSERT OR REPLACE INTO claim
                     (entity,entity_id,field,value,source,source_url,licence,retrieved_at)
                     VALUES('release_line',?,'line_name',?,'correction',?,?,?)""",
                  (rid, name, e["source_url"], LICENCE["correction"], NOW))

        for v in e["volumes"]:
            num = str(v.get("number", "")).strip()
            if not num:
                raise ValueError("lines.json[%d]: a volume without a number" % i)
            vid = _id("v_", rid, num)
            c.execute("""INSERT OR IGNORE INTO volume(id,release_line_id,number,created_at,updated_at)
                         VALUES(?,?,?,?,?)""", (vid, rid, num, NOW, NOW))
            for field in sorted(VOLUME_FIELDS):
                if v.get(field) in (None, ""):
                    continue
                val = str(v[field]).strip()
                if field == "isbn13":
                    val, _ = normalise_isbn(val)
                    if not val:
                        raise ValueError("lines.json[%d] v%s: %r is not an ISBN" % (i, num, v[field]))
                    if isbn_market(val) not in (market, None):
                        raise ValueError("lines.json[%d] v%s: ISBN %s belongs to the %s market, "
                                         "not %s" % (i, num, val, isbn_market(val), market))
                c.execute("""INSERT OR REPLACE INTO override
                             (entity,entity_id,field,value,reason,author,created_at)
                             VALUES('volume',?,?,?,?,?,?)""", (vid, field, val, reason, author, NOW))
                c.execute("""INSERT OR REPLACE INTO claim
                             (entity,entity_id,field,value,source,source_url,licence,retrieved_at)
                             VALUES('volume',?,?,?,'correction',?,?,?)""",
                          (vid, field, val, e["source_url"], LICENCE["correction"], NOW))
                if field == "release_date":
                    c.execute("""UPDATE volume SET release_date=?, release_date_precision=?,
                                 release_date_type=COALESCE(release_date_type,'published'),
                                 updated_at=? WHERE id=?""", (val, _precision(val), NOW, vid))
                elif field == "page_count":
                    c.execute("UPDATE volume SET page_count=?, updated_at=? WHERE id=?",
                              (int(val), NOW, vid))
                else:
                    c.execute("UPDATE volume SET %s=?, updated_at=? WHERE id=?" % field,
                              (val, NOW, vid))
            if v.get("contains") and origin:
                c.execute("""INSERT OR IGNORE INTO composition(volume_id,contains,ref_list,ref_line_id)
                             VALUES(?,'volume',?,?)""",
                          (vid, json.dumps([int(x) if str(x).isdigit() else x
                                            for x in v["contains"]]), origin))
            n_vols += 1
        n_lines += 1
    db.commit()
    if verbose:
        print("  line corrections applied          %8s  (%s volumes)"
              % (format(n_lines, ","), format(n_vols, ",")))
        print("  medium overrides applied          %8s" % format(n_medium, ","))
    return n_lines


def apply_volume_corrections(db, verbose=True):
    c = db.cursor()
    entries = _read("volumes.json")
    applied, stale, unchanged = 0, [], 0

    for i, e in enumerate(entries):
        _require(e, VOLUME_KEYS, "volumes.json", i)
        field = e["field"]
        if field not in VOLUME_FIELDS:
            raise ValueError("volumes.json[%d]: field %r is not correctable (%s)"
                             % (i, field, ", ".join(sorted(VOLUME_FIELDS))))

        key = str(e["volume"]).strip()
        if key.startswith("v_"):
            row = c.execute("SELECT id FROM volume WHERE id=?", (key,)).fetchone()
        else:
            isbn = re.sub(r"[^0-9Xx]", "", key)
            rows = c.execute("SELECT id FROM volume WHERE isbn13=?", (isbn,)).fetchall()
            if len(rows) > 1:
                raise ValueError("volumes.json[%d]: ISBN %s is on %d volumes -- key the "
                                 "correction on a v_ id instead" % (i, isbn, len(rows)))
            row = rows[0] if rows else None
        if not row:
            stale.append((i, key))
            continue
        vid = row[0]
        value = str(e["value"])

        c.execute("""INSERT OR REPLACE INTO override
            (entity,entity_id,field,value,reason,author,created_at)
            VALUES('volume',?,?,?,?,?,?)""",
            (vid, field, value,
             "%s | %s" % (e.get("reason", "hand-checked"), e["source_url"]),
             e.get("author", "corrections/volumes.json"), NOW))

        if field == "release_date":
            prec = e.get("precision") or ("day" if len(value) == 10 else
                                          "month" if len(value) == 7 else "year")
            n = c.execute("""UPDATE volume SET release_date=?, release_date_precision=?
                             WHERE id=? AND (release_date IS NOT ? OR
                                             release_date_precision IS NOT ?)""",
                          (value, prec, vid, value, prec)).rowcount
        elif field == "page_count":
            n = c.execute("UPDATE volume SET page_count=? WHERE id=? AND page_count IS NOT ?",
                          (int(value), vid, int(value))).rowcount
        elif field == "cover_url":
            # no volume column: a cover is a claim, and the exporter prefers the
            # 'correction' source over every ISBN lookup (a picked cover wins)
            n = c.execute("""INSERT OR REPLACE INTO claim
                             (entity,entity_id,field,value,source,source_url,licence,retrieved_at)
                             VALUES('volume',?,'cover_url',?,'correction',?,?,?)""",
                          (vid, value, e["source_url"], LICENCE["correction"], NOW)).rowcount
        else:
            n = c.execute("UPDATE volume SET %s=? WHERE id=? AND %s IS NOT ?"
                          % (field, field), (value, vid, value)).rowcount
        applied += 1
        unchanged += (n == 0)

    db.commit()
    if verbose:
        print("  volume corrections applied        %8s" % format(applied, ","))
        print("  ...already matched the pipeline   %8s" % format(unchanged, ","))
        print("  alias corrections                 %8s" % format(len(load_aliases()), ","))
    if stale:
        print("\n  STALE CORRECTIONS -- target not in the catalogue:", flush=True)
        for i, key in stale:
            print("    volumes.json[%d]: %s" % (i, key))
        print("  An id or ISBN that no longer resolves means the row moved or the\n"
              "  key is wrong. Fix or remove the entry; do not leave it dangling.")
        raise SystemExit(1)
    return applied


def check(directory=DIR, artifact=None):
    """Validate the three corrections files against a PUBLISHED artifact. Returns
    the exit code: 0 when every entry is well-formed and every key resolves, 1
    otherwise -- and never a traceback, because the reader is a contributor.

    Keys resolve against the artifact's own columns, which are not the pipeline
    database's: a `volume` is `volumes.tome_id` (v_...) or `volumes.isbn13`
    (digits/X, stripped exactly as the apply path strips it -- `volumes_special`
    is searched too, since a special volume has no id to key on); a line's `work`
    is `series.tome_work_id`; an alias's `line` is `series.tome_id`. Everything
    the apply path would reject without a database -- a missing key, a field
    that is not correctable, an unknown market, a volume without a number, a
    page count that is not a number, an ISBN from another market -- is rejected
    here too, so a pull request that passes cannot then fail the build on the
    same entry. Nothing is written.
    """
    artifact = artifact or os.path.join(ROOT, "build", "manga-metadata.sqlite")
    if not os.path.exists(artifact):
        print("no artifact at %s -- pass --artifact PATH, or download the published one:\n  %s"
              % (artifact, ARTIFACT_URL))
        return 1
    try:
        db = sqlite3.connect("file:%s?mode=ro" % pathname2url(artifact), uri=True)
        db.execute("SELECT tome_id FROM volumes LIMIT 1")
        db.execute("SELECT tome_id, tome_work_id FROM series LIMIT 1")
    except sqlite3.Error:
        print("not a published artifact: %s (expected manga-metadata.sqlite with series and volumes)"
              % artifact)
        return 1
    problems, stale = [], []          # (reason) / (file, index, what)

    # Reused from the exporter (function-local: export/to_mangarr.py imports this
    # module at its own top level -- `from corrections import load_aliases` -- so a
    # module-level import here would be circular; by the time check() runs this
    # module has already finished initializing, so importing to_mangarr now is safe).
    # _REDUNDANT_SUFFIX is the SAME regex title_for_export uses for the non-trusted
    # export path (one source of truth, review round 1 finding 7 -- this used to be
    # a separate copy here, which could drift from the exporter's and, wrapped in
    # an extra layer of its own optionality, refused a title that was just the bare
    # line/series name with no number at all).
    sys.path.insert(0, os.path.join(ROOT, "export"))
    from to_mangarr import MARKUP_TITLE_RE, NUMBER_ONLY_TITLE, _REDUNDANT_SUFFIX  # noqa: E402

    def bad_title(title, name):
        """None, or the reason a hand-typed title is not a correction (markup,
        number-only, or a restatement of the line/series name and its volume
        number) -- refused at authoring time instead of round-tripping to the
        artifact verbatim, which is what trusted=True corrections otherwise do.
        The redundancy check REQUIRES a volume number (_REDUNDANT_SUFFIX ends in
        a mandatory \\d+): a title that is just the bare name, or the name plus a
        bracketed qualifier ("Name (Light Novel)") with nothing else, is not
        redundant on its own -- it says nothing the row's number doesn't, but it
        also isn't obviously the wrong shape, so this rule leaves it alone."""
        title = str(title)
        if MARKUP_TITLE_RE.search(title):
            return "markup"
        if NUMBER_ONLY_TITLE.match(title):
            return "number-only"
        name = re.sub(r"\s+", " ", (name or "")).strip()
        if name and re.match(r"^" + re.escape(name) + _REDUNDANT_SUFFIX + r"$",
                             re.sub(r"\s+", " ", title).strip(), re.I):
            return "redundant"
        return None

    def series_name_for(key):
        """The artifact's series.name for a volumes.json `volume` key (v_... id or
        ISBN), so a redundant title can be recognised without the entry itself
        carrying a series name."""
        if key.startswith("v_"):
            row = db.execute("""SELECT s.name FROM volumes v JOIN series s
                                ON s.gcd_series_id=v.gcd_series_id WHERE v.tome_id=?""",
                             (key,)).fetchone()
        else:
            isbn = re.sub(r"[^0-9Xx]", "", key)
            row = db.execute("""SELECT s.name FROM volumes v JOIN series s
                                ON s.gcd_series_id=v.gcd_series_id WHERE v.isbn13=?
                                UNION
                                SELECT s.name FROM volumes_special v JOIN series s
                                ON s.gcd_series_id=v.gcd_series_id WHERE v.isbn13=?""",
                             (isbn, isbn)).fetchone()
        return row[0] if row else None

    def entries(name, keys):
        try:
            data = _read(name, directory)
        except ValueError as e:        # json.JSONDecodeError is a ValueError
            problems.append("%s: %s" % (name, e))
            return
        for i, e in enumerate(data):
            if not isinstance(e, dict):
                problems.append("%s[%d]: not an object" % (name, i))
                continue
            try:
                _require(e, keys, name, i)
            except ValueError as err:
                problems.append(str(err))
                continue
            yield i, e

    def exists(sql, value):
        return db.execute(sql, (value,)).fetchone() is not None

    n_vol = n_line = n_medium = n_alias = 0
    for i, e in entries("volumes.json", VOLUME_KEYS):
        field = str(e["field"])
        if field not in VOLUME_FIELDS:
            problems.append("volumes.json[%d]: field %r is not correctable (%s)"
                            % (i, e["field"], ", ".join(sorted(VOLUME_FIELDS))))
            continue
        if field == "page_count" and not str(e["value"]).strip().isdigit():
            problems.append("volumes.json[%d]: page_count %r is not a number" % (i, e["value"]))
            continue
        key = str(e["volume"]).strip()
        if key.startswith("v_"):
            if not exists("SELECT 1 FROM volumes WHERE tome_id=?", key):
                stale.append(("volumes.json", i, "volume %s" % key))
        else:
            # volumes_special (non-integer volume numbers) has no tome_id, so an
            # ISBN is the only key a correction on one of those can carry
            isbn = re.sub(r"[^0-9Xx]", "", key)
            n = db.execute("""SELECT (SELECT COUNT(*) FROM volumes WHERE isbn13=?)
                                   + (SELECT COUNT(*) FROM volumes_special WHERE isbn13=?)""",
                           (isbn, isbn)).fetchone()[0]
            if not isbn or n == 0:
                stale.append(("volumes.json", i, "ISBN %s" % (isbn or repr(key))))
            elif n > 1:
                problems.append("volumes.json[%d]: ISBN %s is on %d volumes -- key the "
                                "correction on a v_ id instead" % (i, isbn, n))
        if field == "title":
            reason = bad_title(e["value"], series_name_for(key))
            if reason:
                problems.append("volumes.json[%d]: title %r looks %s -- not a correctable "
                                "title (see corrections/README.md)" % (i, e["value"], reason))
        n_vol += 1
    try:
        line_data = _read("lines.json", directory)
    except ValueError as err:            # json.JSONDecodeError is a ValueError
        problems.append("lines.json: %s" % err)
        line_data = []
    for i, e in enumerate(line_data):
        if not isinstance(e, dict):
            problems.append("lines.json[%d]: not an object" % i)
            continue
        if "volumes" not in e:
            # a medium override (2026-09-23 follow-up): a narrower shape than a
            # normal entry -- see MEDIUM_KEYS -- so it gets its own validation
            # instead of LINE_KEYS's required work/market/name/volumes.
            try:
                _require(e, MEDIUM_KEYS, "lines.json", i)
            except ValueError as err:
                problems.append(str(err))
                continue
            if e["medium"] not in KNOWN_MEDIA:
                problems.append("lines.json[%d]: unknown medium %r (%s)"
                                % (i, e["medium"], ", ".join(sorted(KNOWN_MEDIA))))
            line = str(e["line"]).strip()
            if not exists("SELECT 1 FROM series WHERE tome_id=?", line):
                stale.append(("lines.json", i, "line %s" % line))
            n_medium += 1
            continue
        try:
            _require(e, LINE_KEYS, "lines.json", i)
        except ValueError as err:
            problems.append(str(err))
            continue
        market = str(e["market"]).upper()
        if market not in MARKET_LANG:
            problems.append("lines.json[%d]: unknown market %r" % (i, e["market"]))
        if not isinstance(e["volumes"], list):
            problems.append("lines.json[%d]: volumes must be an array" % i)
        else:
            for v in e["volumes"]:
                num = str(v.get("number", "")).strip() if isinstance(v, dict) else ""
                if not num:
                    problems.append("lines.json[%d]: a volume without a number" % i)
                    continue
                if v.get("page_count") not in (None, "") and not str(v["page_count"]).strip().isdigit():
                    problems.append("lines.json[%d] v%s: page_count %r is not a number" % (i, num, v["page_count"]))
                if v.get("isbn13") not in (None, ""):
                    isbn, _ = normalise_isbn(str(v["isbn13"]))
                    if not isbn:
                        problems.append("lines.json[%d] v%s: %r is not an ISBN" % (i, num, v["isbn13"]))
                    elif isbn_market(isbn) not in (market, None):
                        problems.append("lines.json[%d] v%s: ISBN %s belongs to the %s market, not %s"
                                        % (i, num, isbn, isbn_market(isbn), market))
                if v.get("title"):
                    reason = bad_title(v["title"], e.get("name"))
                    if reason:
                        problems.append("lines.json[%d] v%s: title %r looks %s -- not a "
                                        "correctable title (see corrections/README.md)"
                                        % (i, num, v["title"], reason))
        work = str(e["work"]).strip()
        if not exists("SELECT 1 FROM series WHERE tome_work_id=?", work):
            stale.append(("lines.json", i, "work %s" % work))
        n_line += 1
    for i, e in entries("aliases.json", ALIAS_KEYS):
        line = str(e["line"]).strip()
        if not exists("SELECT 1 FROM series WHERE tome_id=?", line):
            stale.append(("aliases.json", i, "line %s" % line))
        n_alias += 1

    # A work an exclusion already removed from `series` is not stale: the
    # exporter records every applied exclusion in meta.excluded_works, and this
    # accepts either a work still present (a PR opened before the next publish)
    # or one recorded there (the publish that actually excluded it already
    # happened) -- otherwise every future corrections PR would fail STALE for
    # an exclusion that did exactly what it was supposed to.
    try:
        excluded_recorded = set(json.loads(
            db.execute("SELECT value FROM meta WHERE key='excluded_works'").fetchone()[0]))
    except (TypeError, sqlite3.OperationalError, ValueError):
        excluded_recorded = set()
    n_excluded = 0
    for i, e in entries("excluded.json", EXCLUDED_KEYS):
        work = str(e["work"]).strip()
        if work not in excluded_recorded and not exists("SELECT 1 FROM series WHERE tome_work_id=?", work):
            stale.append(("excluded.json", i, "work %s" % work))
        n_excluded += 1

    for reason in problems:
        print("  %s" % reason)
    for name, i, what in stale:
        print("  STALE CORRECTION -- %s[%d]: %s is not in the published artifact" % (name, i, what))
    if stale:
        print("  An id or ISBN that does not resolve means the key is wrong or the row is\n"
              "  not published yet. Fix or remove the entry; do not leave it dangling.")
    if problems or stale:
        return 1
    try:
        label = db.execute("SELECT value FROM meta WHERE key='gcd_dump'").fetchone()
    except sqlite3.OperationalError:
        label = None
    print("  corrections check ok: %d volume, %d line, %d medium, %d alias, %d excluded "
          "entries resolve against %s%s"
          % (n_vol, n_line, n_medium, n_alias, n_excluded, os.path.basename(artifact),
             " (%s)" % label[0] if label else ""))
    return 0


def _check_main(argv):
    ap = argparse.ArgumentParser(prog="corrections.py --check",
                                 description="validate corrections/ against a published artifact")
    ap.add_argument("--check", nargs="?", const=DIR, default=DIR, metavar="DIR",
                    help="corrections directory (default: corrections/)")
    ap.add_argument("--artifact", metavar="PATH",
                    help="published artifact to resolve keys against (default: build/manga-metadata.sqlite, "
                         "the LAST LOCAL BUILD -- CI checks against the published one, so pass the "
                         "download for a result that matches)")
    a = ap.parse_args(argv)
    return check(a.check, a.artifact)


if __name__ == "__main__":
    if "--check" in sys.argv:            # before any connect: never a database named "--check"
        sys.exit(_check_main(sys.argv[1:]))
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "build", "opentome.db")
    _db = sqlite3.connect(path, timeout=60)
    apply_exclusions(_db)                # excluded works first: nothing later should touch their rows
    apply_line_corrections(_db)          # lines first: a volume correction may target one
    apply_volume_corrections(_db)
