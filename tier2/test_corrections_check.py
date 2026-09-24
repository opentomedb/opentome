"""`tier2/corrections.py --check` validates the corrections files against a PUBLISHED
artifact -- the pull-request check, run without the pipeline database.
Run: python3 tier2/test_corrections_check.py

Offline and self-contained: a tiny artifact carrying only the columns the check
reads (series.tome_id / tome_work_id / medium / language, volumes.tome_id / isbn13,
volumes_special.isbn13) is built in a temp
dir, and a corrections directory is written per case. The check must accept an
empty set, a `v_` id or an ISBN that resolves, a work and a line that resolve; it
must reject a stale key, a missing required key, an uncorrectable field, a page count
that is not a number, an unknown market and malformed JSON -- with a return code,
never a traceback.
"""
import contextlib, hashlib, io, json, os, shutil, sqlite3, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import corrections as C  # noqa: E402

VOL = {"volume": "v_111111111111", "field": "release_date", "value": "2020-01-07",
       "source_url": "https://example.org/v1", "checked": "2026-09-18"}
LINE = {"work": "w_aaaaaaaaaaaa", "market": "EN", "medium": "manga", "name": "Example Deluxe",
        "volumes": [{"number": "1", "isbn13": "978-1-234-56789-0"}],
        "source_url": "https://example.org/line", "checked": "2026-09-18"}
ALIAS = {"line": "rl_aaaaaaaaaaaa", "alias": "Example: The Alias",
         "source_url": "https://example.org/alias", "checked": "2026-09-18"}


def make_artifact(path):
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE series (gcd_series_id INTEGER PRIMARY KEY, name TEXT NOT NULL,
                             tome_id TEXT, tome_work_id TEXT, medium TEXT, language TEXT);
        CREATE TABLE volumes (id INTEGER PRIMARY KEY, gcd_series_id INTEGER NOT NULL,
                              volume_number INTEGER NOT NULL, tome_id TEXT, isbn13 TEXT);
        CREATE TABLE volumes_special (gcd_series_id INTEGER NOT NULL, volume_label TEXT NOT NULL,
                                      isbn13 TEXT);
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        INSERT INTO series VALUES (1, 'Example', 'rl_aaaaaaaaaaaa', 'w_aaaaaaaaaaaa', 'manga', 'ja');
        -- origin_line pin targets (2026-09-24, Roxy Gets Serious): a second same-work
        -- same-medium JP-market line, plus deliberately-wrong-shaped ones to fail a pin.
        INSERT INTO series VALUES (6, 'Example Origin', 'rl_bbbbbbbbbbbb', 'w_aaaaaaaaaaaa', 'manga', 'ja');
        INSERT INTO series VALUES (7, 'Other Work', 'rl_cccccccccccc', 'w_other0000001', 'manga', 'ja');
        INSERT INTO series VALUES (8, 'Wrong Medium', 'rl_dddddddddddd', 'w_aaaaaaaaaaaa', 'light_novel', 'ja');
        INSERT INTO series VALUES (9, 'Not Origin Market', 'rl_eeeeeeeeeeee', 'w_aaaaaaaaaaaa', 'manga', 'en');
        INSERT INTO volumes VALUES (1, 1, 1, 'v_111111111111', '9781234567890');
        INSERT INTO volumes VALUES (2, 1, 2, 'v_222222222222', NULL);
        INSERT INTO volumes VALUES (3, 1, 3, 'v_333333333333', '9781234567005');
        INSERT INTO volumes_special VALUES (1, '2.5', '9781234567999');   -- only here: no tome_id
        INSERT INTO volumes_special VALUES (1, '3.5', '9781234567005');   -- also on v_333: ambiguous
        INSERT INTO meta VALUES ('gcd_dump', 'opentome-2026-09-18');
    """)
    db.commit()
    db.close()


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="opentome-corrections-")
        self.art = os.path.join(self.tmp, "manga-metadata.sqlite")
        make_artifact(self.art)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def corrections(self, volumes="[]", lines="[]", aliases="[]"):
        """Write a corrections dir; each argument is JSON text (so malformed text is possible)."""
        d = tempfile.mkdtemp(prefix="c-", dir=self.tmp)
        for name, text in (("volumes.json", volumes), ("lines.json", lines), ("aliases.json", aliases)):
            with open(os.path.join(d, name), "w", encoding="utf8") as f:
                f.write(text if isinstance(text, str) else json.dumps(text))
        return d

    def check(self, d):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = C.check(d, self.art)
        return code, out.getvalue()

    # -- passes
    def test_all_empty_passes(self):
        code, out = self.check(self.corrections())
        self.assertEqual(code, 0, out)
        self.assertIn("ok", out)

    def test_volume_id_resolves(self):
        code, out = self.check(self.corrections(volumes=[VOL]))
        self.assertEqual(code, 0, out)

    def test_isbn_resolves_after_stripping(self):
        v = dict(VOL, volume="978-1-234-56789-0")
        code, out = self.check(self.corrections(volumes=[v]))
        self.assertEqual(code, 0, out)

    def test_isbn_only_in_volumes_special_resolves(self):
        v = dict(VOL, volume="978-1-234-56799-9")
        code, out = self.check(self.corrections(volumes=[v]))
        self.assertEqual(code, 0, out)

    def test_isbn_on_two_volumes_fails(self):
        v = dict(VOL, volume="9781234567005")      # on v_333 and on a special volume
        code, out = self.check(self.corrections(volumes=[v]))
        self.assertEqual(code, 1)
        self.assertIn("key the correction on a v_ id", out)

    def test_work_and_line_resolve(self):
        code, out = self.check(self.corrections(lines=[LINE], aliases=[ALIAS]))
        self.assertEqual(code, 0, out)

    # -- medium override (2026-09-23 follow-up: the Denma orig_series_id defect)
    def test_medium_override_resolves(self):
        m = {"line": "rl_aaaaaaaaaaaa", "medium": "manhwa",
             "source_url": "https://example.org/medium", "checked": "2026-09-18"}
        code, out = self.check(self.corrections(lines=[m]))
        self.assertEqual(code, 0, out)

    def test_medium_override_bad_medium_fails(self):
        m = {"line": "rl_aaaaaaaaaaaa", "medium": "not_a_medium",
             "source_url": "https://example.org/medium", "checked": "2026-09-18"}
        code, out = self.check(self.corrections(lines=[m]))
        self.assertEqual(code, 1)
        self.assertIn("lines.json[0]", out)
        self.assertIn("not_a_medium", out)

    def test_medium_override_stale_line_fails(self):
        m = {"line": "rl_999999999999", "medium": "manhwa",
             "source_url": "https://example.org/medium", "checked": "2026-09-18"}
        code, out = self.check(self.corrections(lines=[m]))
        self.assertEqual(code, 1)
        self.assertIn("STALE CORRECTION", out)
        self.assertIn("rl_999999999999", out)

    def test_medium_override_missing_key_fails(self):
        m = {"line": "rl_aaaaaaaaaaaa", "source_url": "https://example.org/medium", "checked": "2026-09-18"}
        code, out = self.check(self.corrections(lines=[m]))
        self.assertEqual(code, 1)
        self.assertIn("lines.json[0]", out)
        self.assertIn("medium", out)

    # -- market override (2026-09-23 cleanup, item 3: Denma's mislabelled "ja" line)
    def test_market_override_resolves(self):
        m = {"line": "rl_aaaaaaaaaaaa", "market": "KR",
             "source_url": "https://example.org/market", "checked": "2026-09-23"}
        code, out = self.check(self.corrections(lines=[m]))
        self.assertEqual(code, 0, out)

    def test_market_override_bad_market_fails(self):
        m = {"line": "rl_aaaaaaaaaaaa", "market": "XX",
             "source_url": "https://example.org/market", "checked": "2026-09-23"}
        code, out = self.check(self.corrections(lines=[m]))
        self.assertEqual(code, 1)
        self.assertIn("lines.json[0]", out)
        self.assertIn("XX", out)

    def test_market_override_stale_line_fails(self):
        m = {"line": "rl_999999999999", "market": "KR",
             "source_url": "https://example.org/market", "checked": "2026-09-23"}
        code, out = self.check(self.corrections(lines=[m]))
        self.assertEqual(code, 1)
        self.assertIn("STALE CORRECTION", out)
        self.assertIn("rl_999999999999", out)

    def test_market_override_missing_key_fails(self):
        m = {"line": "rl_aaaaaaaaaaaa", "source_url": "https://example.org/market", "checked": "2026-09-23"}
        code, out = self.check(self.corrections(lines=[m]))
        self.assertEqual(code, 1)
        self.assertIn("lines.json[0]", out)
        self.assertIn("market", out)

    # -- origin_line pin (2026-09-24, Roxy Gets Serious): a whole-edition entry
    # naming the exact origin-market line for orig_series_id, needed when two
    # lines share (work, medium, market) and the export's own name-key match
    # cannot pair them (see corrections/README.md).
    def test_origin_line_pin_resolves(self):
        line = dict(LINE, origin_line="rl_bbbbbbbbbbbb")
        code, out = self.check(self.corrections(lines=[line]))
        self.assertEqual(code, 0, out)

    def test_origin_line_pin_stale_fails(self):
        line = dict(LINE, origin_line="rl_999999999999")
        code, out = self.check(self.corrections(lines=[line]))
        self.assertEqual(code, 1)
        self.assertIn("STALE CORRECTION", out)
        self.assertIn("rl_999999999999", out)

    def test_origin_line_pin_wrong_work_fails(self):
        line = dict(LINE, origin_line="rl_cccccccccccc")
        code, out = self.check(self.corrections(lines=[line]))
        self.assertEqual(code, 1)
        self.assertIn("lines.json[0]", out)
        self.assertIn("rl_cccccccccccc", out)
        self.assertIn("w_other0000001", out)

    def test_origin_line_pin_wrong_medium_fails(self):
        line = dict(LINE, origin_line="rl_dddddddddddd")
        code, out = self.check(self.corrections(lines=[line]))
        self.assertEqual(code, 1)
        self.assertIn("lines.json[0]", out)
        self.assertIn("light_novel", out)

    def test_origin_line_pin_non_origin_market_fails(self):
        line = dict(LINE, origin_line="rl_eeeeeeeeeeee")
        code, out = self.check(self.corrections(lines=[line]))
        self.assertEqual(code, 1)
        self.assertIn("lines.json[0]", out)
        self.assertIn("origin market", out)

    # -- curated alias removal (2026-09-23 cleanup, item 2): "remove": true on
    # an otherwise-normal aliases.json entry. load_aliases() (additions, read by
    # export's normal alias-correction loop) and load_alias_removals() (the new
    # loop that deletes) must partition the file, never double-count an entry.
    def test_load_aliases_excludes_removals(self):
        add = dict(ALIAS, alias="Add Me")
        remove = dict(ALIAS, alias="Remove Me", remove=True)
        d = self.corrections(aliases=[add, remove])
        self.assertEqual(C.load_aliases(d), [(ALIAS["line"], "Add Me")])
        self.assertEqual(C.load_alias_removals(d), [(ALIAS["line"], "Remove Me")])

    def test_removal_entry_still_requires_source_and_checked(self):
        bad = {"line": "rl_aaaaaaaaaaaa", "alias": "Remove Me", "remove": True}
        code, out = self.check(self.corrections(aliases=[bad]))
        self.assertEqual(code, 1)
        self.assertIn("source_url", out)

    def test_removal_entry_line_still_resolves(self):
        remove = dict(ALIAS, alias="Remove Me", remove=True)
        code, out = self.check(self.corrections(aliases=[remove]))
        self.assertEqual(code, 0, out)

    # -- exclusion (2026-09-23 cleanup: The Walking Dead entered via a
    # Wikipedia list-of-volumes page and isn't in scope; excluded.json removes
    # a whole work -- keyed on the work id tier 0 computes, same stability
    # story as the medium override's line id)
    def test_exclusion_resolves(self):
        x = {"work": "w_aaaaaaaaaaaa", "source_url": "https://example.org/excluded",
             "checked": "2026-09-18"}
        # excluded.json is a fourth file; write it directly into a fresh corrections dir
        d = self.corrections()
        with open(os.path.join(d, "excluded.json"), "w", encoding="utf8") as f:
            json.dump([x], f)
        code, out = self.check(d)
        self.assertEqual(code, 0, out)

    def test_exclusion_stale_work_fails(self):
        x = {"work": "w_999999999999", "source_url": "https://example.org/excluded",
             "checked": "2026-09-18"}
        d = self.corrections()
        with open(os.path.join(d, "excluded.json"), "w", encoding="utf8") as f:
            json.dump([x], f)
        code, out = self.check(d)
        self.assertEqual(code, 1)
        self.assertIn("STALE CORRECTION", out)
        self.assertIn("w_999999999999", out)

    def test_exclusion_missing_key_fails(self):
        x = {"work": "w_aaaaaaaaaaaa", "checked": "2026-09-18"}
        d = self.corrections()
        with open(os.path.join(d, "excluded.json"), "w", encoding="utf8") as f:
            json.dump([x], f)
        code, out = self.check(d)
        self.assertEqual(code, 1)
        self.assertIn("excluded.json[0]", out)
        self.assertIn("source_url", out)

    def test_exclusion_recorded_in_meta_passes_once_the_work_is_gone(self):
        # After a publish that actually excludes the work, series no longer
        # carries it -- but the exporter records every excluded work id in
        # meta.excluded_works, and the check accepts either.
        db = sqlite3.connect(self.art)
        db.execute("INSERT INTO meta VALUES ('excluded_works', ?)",
                   (json.dumps(["w_gone0000001"]),))
        db.commit(); db.close()
        x = {"work": "w_gone0000001", "source_url": "https://example.org/excluded",
             "checked": "2026-09-18"}
        d = self.corrections()
        with open(os.path.join(d, "excluded.json"), "w", encoding="utf8") as f:
            json.dump([x], f)
        code, out = self.check(d)
        self.assertEqual(code, 0, out)

    # -- anilist.json (2026-09-24, the Worst wrong bind): a hand-checked AniList id per line
    def anilist(self, *pins):
        d = self.corrections()
        with open(os.path.join(d, "anilist.json"), "w", encoding="utf8") as f:
            json.dump(list(pins), f)
        return d

    PIN = {"line": "rl_aaaaaaaaaaaa", "anilist_id": 31741, "source_url": "https://anilist.co/manga/31741",
           "checked": "2026-09-24"}

    def test_anilist_pin_resolves(self):
        code, out = self.check(self.anilist(self.PIN))
        self.assertEqual(code, 0, out)
        self.assertIn("1 anilist", out)

    def test_anilist_pin_stale_line_fails(self):
        code, out = self.check(self.anilist(dict(self.PIN, line="rl_999999999999")))
        self.assertEqual(code, 1)
        self.assertIn("STALE CORRECTION -- anilist.json[0]", out)
        self.assertIn("rl_999999999999", out)

    def test_anilist_pin_missing_key_fails(self):
        pin = dict(self.PIN)
        del pin["source_url"]
        code, out = self.check(self.anilist(pin))
        self.assertEqual(code, 1)
        self.assertIn("anilist.json[0]", out)
        self.assertIn("source_url", out)

    def test_anilist_pin_id_not_an_int_fails(self):
        for bad in ("31741", True, -5, 1.5):
            code, out = self.check(self.anilist(dict(self.PIN, anilist_id=bad)))
            self.assertEqual(code, 1, bad)
            self.assertIn("not a positive integer", out)

    def test_anilist_pin_duplicate_line_fails(self):
        code, out = self.check(self.anilist(self.PIN, dict(self.PIN, anilist_id=147044)))
        self.assertEqual(code, 1)
        self.assertIn("anilist.json[1]: line rl_aaaaaaaaaaaa is already pinned by anilist.json[0]", out)
        with self.assertRaises(ValueError):
            C.load_anilist_pins(self.anilist(self.PIN, dict(self.PIN, anilist_id=147044)))

    def test_anilist_pin_apply_overrides_and_fails_stale(self):
        art = sqlite3.connect(":memory:")
        art.execute("CREATE TABLE series (gcd_series_id INTEGER PRIMARY KEY, tome_id TEXT, anilist_id INTEGER)")
        art.execute("INSERT INTO series VALUES (1, 'rl_aaaaaaaaaaaa', 147044)")   # the resolver's pick
        art.execute("INSERT INTO series VALUES (2, 'rl_bbbbbbbbbbbb', 5)")
        with contextlib.redirect_stdout(io.StringIO()):
            C.apply_anilist_pins(art, entries=[("rl_aaaaaaaaaaaa", 31741)])
        self.assertEqual(art.execute("SELECT gcd_series_id, anilist_id FROM series ORDER BY 1").fetchall(),
                         [(1, 31741), (2, 5)])
        with contextlib.redirect_stdout(io.StringIO()) as out, self.assertRaises(SystemExit):
            C.apply_anilist_pins(art, entries=[("rl_999999999999", 31741)])
        self.assertIn("STALE CORRECTION -- anilist.json[0]", out.getvalue())

    def test_anilist_pins_load_validates(self):
        d = self.anilist(self.PIN)
        self.assertEqual(C.load_anilist_pins(d), [("rl_aaaaaaaaaaaa", 31741)])
        with self.assertRaises(ValueError):
            C.load_anilist_pins(self.anilist(dict(self.PIN, anilist_id=True)))

    # -- failures: stale keys
    def test_stale_volume_id_fails(self):
        v = dict(VOL, volume="v_999999999999")
        code, out = self.check(self.corrections(volumes=[v]))
        self.assertEqual(code, 1)
        self.assertIn("STALE CORRECTION", out)
        self.assertIn("v_999999999999", out)

    def test_stale_isbn_fails(self):
        v = dict(VOL, volume="9789999999999")
        code, out = self.check(self.corrections(volumes=[v]))
        self.assertEqual(code, 1)
        self.assertIn("STALE CORRECTION", out)

    def test_stale_work_fails(self):
        code, out = self.check(self.corrections(lines=[dict(LINE, work="w_999999999999")]))
        self.assertEqual(code, 1)
        self.assertIn("STALE CORRECTION", out)

    def test_stale_line_fails(self):
        code, out = self.check(self.corrections(aliases=[dict(ALIAS, line="rl_999999999999")]))
        self.assertEqual(code, 1)
        self.assertIn("STALE CORRECTION", out)

    # -- failures: malformed entries
    def test_missing_required_key_fails(self):
        v = {k: v for k, v in VOL.items() if k != "source_url"}
        code, out = self.check(self.corrections(volumes=[v]))
        self.assertEqual(code, 1)
        self.assertIn("volumes.json[0]", out)
        self.assertIn("source_url", out)

    def test_bad_field_fails(self):
        code, out = self.check(self.corrections(volumes=[dict(VOL, field="colour")]))
        self.assertEqual(code, 1)
        self.assertIn("volumes.json[0]", out)
        self.assertIn("colour", out)

    def test_bad_page_count_fails(self):
        code, out = self.check(self.corrections(volumes=[dict(VOL, field="page_count", value="two hundred")]))
        self.assertEqual(code, 1)
        self.assertIn("volumes.json[0]", out)
        line = dict(LINE, volumes=[{"number": "1", "page_count": "n/a"}])
        code, out = self.check(self.corrections(lines=[line]))
        self.assertEqual(code, 1)
        self.assertIn("lines.json[0] v1", out)

    def test_bad_market_fails(self):
        code, out = self.check(self.corrections(lines=[dict(LINE, market="XX")]))
        self.assertEqual(code, 1)
        self.assertIn("lines.json[0]", out)
        self.assertIn("XX", out)

    # -- failures: hygiene-reject titles (authoring-time check, item 2)
    def test_markup_title_fails_volumes(self):
        v = dict(VOL, field="title", value="{{japonais|x}}")
        code, out = self.check(self.corrections(volumes=[v]))
        self.assertEqual(code, 1)
        self.assertIn("volumes.json[0]", out)
        self.assertIn("markup", out)

    def test_number_only_title_fails_volumes(self):
        v = dict(VOL, field="title", value="12")
        code, out = self.check(self.corrections(volumes=[v]))
        self.assertEqual(code, 1)
        self.assertIn("number-only", out)

    def test_redundant_title_fails_volumes(self):
        # v_111111111111 is series 'Example' volume 1 in make_artifact()
        v = dict(VOL, field="title", value="Example Vol. 1")
        code, out = self.check(self.corrections(volumes=[v]))
        self.assertEqual(code, 1)
        self.assertIn("redundant", out)

    def test_redundant_title_with_bracket_qualifier_fails_volumes(self):
        v = dict(VOL, field="title", value="Example (Light Novel) Vol. 1")
        code, out = self.check(self.corrections(volumes=[v]))
        self.assertEqual(code, 1)
        self.assertIn("redundant", out)

    def test_bare_v_form_is_not_redundant_volumes(self):
        # review round 1, finding 7: the check derives its redundancy pattern
        # from the exporter's _REDUNDANT_SUFFIX (one source of truth), which
        # does not recognise a bare 'v' word -- so this is no longer refused.
        v = dict(VOL, field="title", value="Example v1")
        code, out = self.check(self.corrections(volumes=[v]))
        self.assertEqual(code, 0, out)

    def test_bare_name_no_number_is_not_redundant_volumes(self):
        # review round 1, finding 7: a title equal to just the line/series name,
        # with no volume number at all, is not refused by this rule.
        v = dict(VOL, field="title", value="Example")
        code, out = self.check(self.corrections(volumes=[v]))
        self.assertEqual(code, 0, out)

    def test_bracket_qualifier_no_number_is_not_redundant_volumes(self):
        v = dict(VOL, field="title", value="Example (Light Novel)")
        code, out = self.check(self.corrections(volumes=[v]))
        self.assertEqual(code, 0, out)

    def test_real_subtitle_title_passes_volumes(self):
        v = dict(VOL, field="title", value="Example: The Beginning")
        code, out = self.check(self.corrections(volumes=[v]))
        self.assertEqual(code, 0, out)

    def test_markup_title_fails_lines(self):
        line = dict(LINE, volumes=[{"number": "1", "isbn13": "978-1-234-56789-0",
                                    "title": "[[Example]]"}])
        code, out = self.check(self.corrections(lines=[line]))
        self.assertEqual(code, 1)
        self.assertIn("lines.json[0] v1", out)
        self.assertIn("markup", out)

    def test_number_only_title_fails_lines(self):
        line = dict(LINE, volumes=[{"number": "1", "isbn13": "978-1-234-56789-0", "title": "1"}])
        code, out = self.check(self.corrections(lines=[line]))
        self.assertEqual(code, 1)
        self.assertIn("number-only", out)

    def test_redundant_title_fails_lines(self):
        line = dict(LINE, name="Example Deluxe",
                    volumes=[{"number": "1", "isbn13": "978-1-234-56789-0",
                             "title": "Example Deluxe (Light Novel) Vol. 1"}])
        code, out = self.check(self.corrections(lines=[line]))
        self.assertEqual(code, 1)
        self.assertIn("redundant", out)

    def test_real_subtitle_title_passes_lines(self):
        line = dict(LINE, name="Example Deluxe",
                    volumes=[{"number": "1", "isbn13": "978-1-234-56789-0",
                             "title": "Example Deluxe: A Real Subtitle"}])
        code, out = self.check(self.corrections(lines=[line]))
        self.assertEqual(code, 0, out)

    def test_bare_name_no_number_is_not_redundant_lines(self):
        line = dict(LINE, name="Example Deluxe",
                    volumes=[{"number": "1", "isbn13": "978-1-234-56789-0",
                             "title": "Example Deluxe"}])
        code, out = self.check(self.corrections(lines=[line]))
        self.assertEqual(code, 0, out)

    def test_bracket_qualifier_no_number_is_not_redundant_lines(self):
        line = dict(LINE, name="Example Deluxe",
                    volumes=[{"number": "1", "isbn13": "978-1-234-56789-0",
                             "title": "Example Deluxe (Light Novel)"}])
        code, out = self.check(self.corrections(lines=[line]))
        self.assertEqual(code, 0, out)

    def test_non_string_keys_fail_without_traceback(self):
        code, out = self.check(self.corrections(volumes=[dict(VOL, volume=["v_111111111111"])],
                                                lines=[dict(LINE, work={"id": 1})],
                                                aliases=[dict(ALIAS, line=[1, 2])]))
        self.assertEqual(code, 1)
        self.assertIn("STALE CORRECTION", out)

    def test_not_an_artifact_fails(self):
        bogus = os.path.join(self.tmp, "index.html")
        with open(bogus, "w") as f:
            f.write("<html>not found</html>")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = C.check(self.corrections(), bogus)
        self.assertEqual(code, 1)
        self.assertIn("not a published artifact", out.getvalue())

    def test_malformed_json_fails(self):
        code, out = self.check(self.corrections(aliases="[{oops"))
        self.assertEqual(code, 1)
        self.assertIn("aliases.json", out)

    def test_not_an_array_fails(self):
        code, out = self.check(self.corrections(volumes="{}"))
        self.assertEqual(code, 1)
        self.assertIn("volumes.json", out)

    # -- the CLI: exit codes, and nothing written
    def test_cli_exit_codes(self):
        script = os.path.join(HERE, "corrections.py")
        cwd = tempfile.mkdtemp(prefix="cwd-", dir=self.tmp)
        with open(self.art, "rb") as f:
            before = hashlib.sha256(f.read()).hexdigest()
        ok = subprocess.run([sys.executable, script, "--check", self.corrections(), "--artifact", self.art],
                            capture_output=True, text=True, cwd=cwd)
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        stale = subprocess.run([sys.executable, script, "--check",
                                self.corrections(volumes=[dict(VOL, volume="v_999999999999")]),
                                "--artifact", self.art], capture_output=True, text=True, cwd=cwd)
        self.assertEqual(stale.returncode, 1, stale.stdout + stale.stderr)
        self.assertIn("STALE CORRECTION", stale.stdout)
        bad_title = subprocess.run([sys.executable, script, "--check",
                                    self.corrections(volumes=[dict(VOL, field="title", value="{{x}}")]),
                                    "--artifact", self.art], capture_output=True, text=True, cwd=cwd)
        self.assertEqual(bad_title.returncode, 1, bad_title.stdout + bad_title.stderr)
        self.assertIn("markup", bad_title.stdout)
        self.assertEqual(os.listdir(cwd), [], "the check must not write anything")
        with open(self.art, "rb") as f:
            self.assertEqual(hashlib.sha256(f.read()).hexdigest(), before, "the artifact must be untouched")


if __name__ == "__main__":
    unittest.main(verbosity=1)
