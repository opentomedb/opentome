"""`tier2/corrections.py --check` validates the corrections files against a PUBLISHED
artifact -- the pull-request check, run without the pipeline database.
Run: python3 tier2/test_corrections_check.py

Offline and self-contained: a tiny artifact carrying only the columns the check
reads (series.tome_id / tome_work_id, volumes.tome_id / isbn13, volumes_special.isbn13)
is built in a temp
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
                             tome_id TEXT, tome_work_id TEXT);
        CREATE TABLE volumes (id INTEGER PRIMARY KEY, gcd_series_id INTEGER NOT NULL,
                              volume_number INTEGER NOT NULL, tome_id TEXT, isbn13 TEXT);
        CREATE TABLE volumes_special (gcd_series_id INTEGER NOT NULL, volume_label TEXT NOT NULL,
                                      isbn13 TEXT);
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        INSERT INTO series VALUES (1, 'Example', 'rl_aaaaaaaaaaaa', 'w_aaaaaaaaaaaa');
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
        self.assertEqual(os.listdir(cwd), [], "the check must not write anything")
        with open(self.art, "rb") as f:
            self.assertEqual(hashlib.sha256(f.read()).hexdigest(), before, "the artifact must be untouched")


if __name__ == "__main__":
    unittest.main(verbosity=1)
