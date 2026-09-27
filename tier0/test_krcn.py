"""Unit tests for the KR/CN round (docs/krcn-design.md). Run: python3 tier0/test_krcn.py

No network: synthetic records transcribed from the 2026-09-27 spike's cached responses (each
cites its spike cache file under ~/Claude/scratch/mangarr-session/krcn/cache/), in-memory
catalogues built from schema/schema.sql, and *_OFFLINE=1 as a backstop.
"""
import datetime, json, os, re, sqlite3, sys, tempfile, unicodedata

for _src in ("DNB", "LOC", "BNF"):
    os.environ[_src + "_OFFLINE"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _d in (HERE, os.path.join(ROOT, "schema"), os.path.join(ROOT, "tier1"), os.path.join(ROOT, "tier2"),
           os.path.join(ROOT, "export")):
    sys.path.insert(0, _d)

FAILS = []
Y = datetime.date.today().year


def eq(label, got, want):
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else f"  got={got!r} want={want!r}"))
    if not ok:
        FAILS.append(label)


def schema_db():
    db = sqlite3.connect(":memory:")
    db.executescript(open(os.path.join(ROOT, "schema", "schema.sql"), encoding="utf8").read())
    return db


# ---- Task 1: replay harness --------------------------------------------------------------------
import krcn_replay as R

base = {"dnb:1": ["high", "linked", 1, "rl_a", "w_1"], "dnb:2": ["none", "unlinked", 0, "rl_b", None]}
eq("identical snapshots: no change", R.diff_snapshots(base, dict(base)), {"added": [], "removed": [], "changed": []})
new = {"dnb:1": ["high", "out_of_scope", 0, "rl_a", "w_1"], "dnb:3": ["none", "unlinked", 0, "rl_c", None]}
d = R.diff_snapshots(base, new)
eq("a role and an exported flag changed", d["changed"],
   [("dnb:1", "role", "linked", "out_of_scope"), ("dnb:1", "exported", 1, 0)])
eq("a key added and a key removed", (d["added"], d["removed"]), (["dnb:3"], ["dnb:2"]))
eq("an rl_id-only change is detected",
   R.diff_snapshots(base, dict(base, **{"dnb:1": ["high", "linked", 1, "rl_z", "w_1"]}))["changed"],
   [("dnb:1", "rl_id", "rl_a", "rl_z")])
eq("a link_work-only change is detected",
   R.diff_snapshots(base, dict(base, **{"dnb:2": ["none", "unlinked", 0, "rl_b", "w_9"]}))["changed"],
   [("dnb:2", "link_work", None, "w_9")])
eq("has_hangul: syllables", R.has_hangul("나 혼자만 레벨업"), True)
eq("has_hangul: compatibility jamo", R.has_hangul("ㅋㅋ"), True)
eq("has_hangul: kana / Latin", R.has_hangul("ガンダム Übel Blatt"), False)
eq("fold_v1 is the pre-round fold (Hangul dropped)", R.fold_v1("나 혼자만 레벨업"), "")
eq("fold_v1 kana voicing dropped", R.fold_v1("ガンダム"), R.fold_v1("カンタム"))

# ---- Task 2: fold() keeps Hangul ------------------------------------------------------------------
import dnb_link as L

eq("fold keeps Hangul syllables (NFD split them, NFC restores)", L.fold("나 혼자만 레벨업"), "나혼자만레벨업")
eq("fold of NFD Hangul input", L.fold(unicodedata.normalize("NFD", "나 혼자만 레벨업")), "나혼자만레벨업")
eq("DNB Bastard's 246 (spike dnb_lines.json dnb:1380595053)", L.fold("후레자식"), "후레자식")
SAMPLES = ["ガンダム", "Übel Blatt", "Jeanne d’Arc", "Kaiju No. 8 – Band 16 (Finale)", "\x98Die\x9c Welt",
           "Détective Conan Tome 3", "ＡＢＣ", "Ranma ½", "Shaman King × 2", "One Piece & Co", "Monster Mädchen 21",
           "ワンピース", "進撃の巨人", "Kōsuke Fujishima", "L'Attaque des Titans vol. 3", "Taboo Tattoo #4"]
for s in SAMPLES:
    eq("fold unchanged without Hangul: %r" % s, (L.fold(s), L.fold(s, False)), (R.fold_v1(s), R.fold_v1(s, False)))
eq("key_ok: 2-syllable Hangul key admitted", L.key_ok("괴물"), True)
eq("key_ok: 1-syllable Hangul key refused", L.key_ok("괴"), False)
eq("key_ok: 2-letter Latin key refused (MIN_KEY 3 unchanged)", L.key_ok("ab"), False)
eq("key_ok: 2-kanji key refused (MIN_KEY 3 unchanged)", L.key_ok("巨人"), False)
eq("keys(): the 2-syllable Hangul title keys", L.keys(["괴물"]), {"괴물"})
eq("keys(): mixed Hangul + Latin under 3 is not Hangul-only", L.keys(["괴a"]), set())

db = schema_db()
db.execute("INSERT INTO work VALUES('w_kr1','Bastard (manhwa)',NULL,NULL,NULL,NULL,'x','x')")
db.execute("INSERT INTO work_title VALUES('w_kr1','ko','후레자식','official')")
db.execute("INSERT INTO work_title VALUES('w_kr1','ko','괴물','alias')")
idx = L.Index(db)
eq("Index._add keeps a Hangul official key", idx.official.get("후레자식"), {"w_kr1"})
eq("Index._add keeps a 2-syllable Hangul alias key", idx.alias.get("괴물"), {"w_kr1"})
tier, work, _, via = L.link(idx, ["Bastard", "후레자식"], [], ["후레자식"], "Bastard")
eq("a line carrying only the Hangul original links through it", (tier, work), ("medium", "w_kr1"))

# ---- Task 3: KR/CN work set, out-of-scope, JP guard, full names ------------------------------------
def line_row(db, rid, wid, medium, market, lang, source="wikipedia"):
    db.execute("INSERT INTO release_line(id,work_id,medium,market,language,created_at,updated_at) "
               "VALUES(?,?,?,?,?,'x','x')", (rid, wid, medium, market, lang))
    db.execute("INSERT INTO claim VALUES('release_line',?,'publisher','x',?,NULL,'facts_only','x')", (rid, source))

db = schema_db()
for wid, title in (("w_wind", "Wind Breaker"), ("w_mag", "Ultramarine Magmell"), ("w_priest", "Priest"),
                   ("w_hell", "King of Hell"), ("w_ouro", "Ouroboros"), ("w_sl", "Solo Leveling")):
    db.execute("INSERT INTO work VALUES(?,?,NULL,NULL,NULL,NULL,'x','x')", (wid, title))
line_row(db, "rl_w1", "w_wind", "manga", "JP", "ja")            # Kodansha manga ...
line_row(db, "rl_w2", "w_wind", "manhwa", "KR", "ko")           # ... and the webtoon (merged by title)
line_row(db, "rl_m1", "w_mag", "manhua", "JP", "ja")            # Magmell: its only line is a JP-market manhua
line_row(db, "rl_p1", "w_priest", "manhwa", "EN", "en")
line_row(db, "rl_h1", "w_hell", "manga", "KR", "ko")            # a Korean work tagged manga (§1)
line_row(db, "rl_o1", "w_ouro", "manga", "JP", "ja")
line_row(db, "rl_s1", "w_sl", "manhwa", "EN", "en")
db.execute("""INSERT INTO claim VALUES('work','w_sl','author','["Chugong"]','wikipedia',NULL,'facts_only','x')""")
db.execute("""INSERT INTO claim VALUES('work','w_priest','author','["Park Sun-young"]','wikipedia',NULL,'facts_only','x')""")
idx = L.Index(db)
eq("KR/CN work set: manhwa/manhua lines and KR/CN/TW markets",
   idx.krcn_works, {"w_wind", "w_mag", "w_priest", "w_hell", "w_sl"})
eq("Japanese works: a JP line of a Japanese medium (Magmell's JP manhua is not one)",
   idx.jp_works, {"w_wind", "w_ouro"})
eq("out of scope for the German JP round: a manhwa/manhua/webtoon line and no Japanese line",
   idx.out_of_scope, {"w_mag", "w_priest", "w_sl"})
eq("King of Hell (ko market, tagged manga): KR/CN for the KR/CN linker, but its published German line stays "
   "in the JP round (P1)", ("w_hell" in idx.krcn_works, "w_hell" in idx.out_of_scope), (True, False))
eq("Wind Breaker (JP manga + KR webtoon) stays in scope (the §1 latent drop fixed)", "w_wind" in idx.out_of_scope, False)
eq("JP guard: a KR/CN line to Ouroboros (JP only) -> review", idx.jp_guard("w_ouro"), True)
eq("JP guard: not for a mixed work", idx.jp_guard("w_wind"), False)
idx.add_krcn_work("w_new")
eq("add_krcn_work extends the set", "w_new" in idx.krcn_works, True)

eq("full_splits: 'Park, Jin-hwan'", L.full_splits("Park, Jin-hwan"), {("park", "jinhwan")})
eq("full_splits: 'Park Jin Hwan' (either order, or joined)", L.full_splits("Park Jin Hwan"),
   {("park", "jinhwan"), ("hwan", "parkjin"), ("parkjinhwan", "")})
eq("same_person (JP rule) accepts Park = Park (the §10 defect)",
   L.same_person(L.name_key("Park, Jin-hwan"), L.name_key("Park Sun-young")), True)
eq("same_full: Park, Jin-hwan != Park Sun-young", L.same_full("Park, Jin-hwan", "Park Sun-young"), False)
eq("same_full: Chugong = Chu-Gong", L.same_full("Chugong", "Chu-Gong"), True)
eq("same_full: Chugong = Chu Gong (the joined split)", L.same_full("Chugong", "Chu Gong"), True)
eq("same_full: 'Kim, Carnby' = 'Carnby Kim'", L.same_full("Kim, Carnby", "Carnby Kim"), True)
eq("same_full: 'Dubu (Redice Studio)' = 'Dubu'", L.same_full("Dubu (Redice Studio)", "Dubu"), True)
t = L.link(idx, ["Priest"], ["Park, Jin-hwan"], name="Priest", full_names=True)
eq("full names: a KR/CN line whose author differs is a collision (low), not a link", (t[0], t[3]),
   ("low", "title, authors differ"))
t = L.link(idx, ["Solo Leveling"], ["Chu-Gong"], name="Solo Leveling", full_names=True)
eq("full names: Chu-Gong matches Chugong -> high", (t[0], t[1], t[3]), ("high", "w_sl", "title+author"))
t = L.link(idx, ["Priest"], ["Park, Jin-hwan"], name="Priest")
eq("JP rule unchanged by default (family name within one edit)", t[0], "high")

# a line stage 3f loads (DE / manhwa, a dnb line_name claim) onto a KR-market work tagged manga
# (King of Hell) must not move the work into out_of_scope: the work sets never read a library line
line_row(db, "rl_h_de", "w_hell", "manhwa", "DE", "de", source="dnb")
db.execute("INSERT INTO claim VALUES('release_line','rl_h_de','line_name','King of Hell','dnb',NULL,'cc0','x')")
line_row(db, "rl_o_loc", "w_ouro", "manhwa", "US", "en", source="loc")      # a 3f LoC line: ignored too
db.execute("INSERT INTO work VALUES('w_tog','Tower of God',NULL,NULL,NULL,NULL,'x','x')")
line_row(db, "rl_t1", "w_tog", "manhwa", "EN", "en")
db.execute("""INSERT INTO claim VALUES('work','w_tog','author','["SIU", "Kim Min-soo"]','wikipedia',NULL,'facts_only','x')""")
idx2 = L.Index(db)
eq("a 3f-loaded DE/manhwa line (dnb claim) leaves out_of_scope unchanged",
   idx2.out_of_scope, {"w_mag", "w_priest", "w_sl", "w_tog"})
eq("... and the KR/CN / JP work sets", (idx2.krcn_works, idx2.jp_works),
   ({"w_wind", "w_mag", "w_priest", "w_hell", "w_sl", "w_tog"}, {"w_wind", "w_ouro"}))
# a line a correction created (only a 'correction' claim) and a DE Wikipedia line merged with DNB
# claims are not library lines: both count
db.execute("INSERT INTO work VALUES('w_corr','Corrected Manhwa',NULL,NULL,NULL,NULL,'x','x')")
line_row(db, "rl_c1", "w_corr", "manhwa", "EN", "en", source="correction")
db.execute("INSERT INTO work VALUES('w_dewiki','German Wiki Manhua',NULL,NULL,NULL,NULL,'x','x')")
line_row(db, "rl_dw1", "w_dewiki", "manhua", "DE", "de")
db.execute("INSERT INTO claim VALUES('release_line','rl_dw1','line_name','German Wiki Manhua','dnb',NULL,'cc0','x')")
idx3 = L.Index(db)
eq("a correction-created manhwa line counts (KR/CN work set and out_of_scope)",
   ("w_corr" in idx3.krcn_works, "w_corr" in idx3.out_of_scope), (True, True))
eq("a DE Wikipedia line merged with DNB claims counts",
   ("w_dewiki" in idx3.krcn_works, "w_dewiki" in idx3.out_of_scope), (True, True))
eq("author_raw keeps a short pen name name_key drops ('SIU')", "SIU" in idx2.author_raw["w_tog"], True)
t = L.link(idx2, ["Tower of God"], ["SIU"], name="Tower of God", full_names=True)
eq("full names: 'SIU' against a work credited SIU + another creator -> high", (t[0], t[1], t[3]),
   ("high", "w_tog", "title+author"))

# ---- Task 4: Open Library per-ISBN cache keys -------------------------------------------------------
import hashlib, verify as V, enrich_more as EM

_ol_tmp = tempfile.mkdtemp(prefix="krcn-ol-")
_saved_ol = (V.CACHE, V.urllib.request.urlopen)
V.CACHE = _ol_tmp
OL_CALLS = []


class _OLResp:
    def __init__(self, d):
        self.d = json.dumps(d).encode()

    def read(self):
        return self.d

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


OL_DB = {"9780000000002": {"publish_date": "March 2, 2021", "number_of_pages": 320},
         "9780000000019": {"publish_date": "2020"},
         "9780000000040": {"publish_date": "Sep 02, 2020", "number_of_pages": 192}}


def ol_urlopen(req, timeout=None):
    OL_CALLS.append(req.full_url)
    want = re.search(r"bibkeys=([^&]+)", req.full_url).group(1).split(",")
    return _OLResp({k: OL_DB[k[5:]] for k in want if k[5:] in OL_DB})


V.urllib.request.urlopen = ol_urlopen
try:
    A_, B_, C_, D_ = "9780000000002", "9780000000019", "9780000000026", "9780000000040"
    # a legacy batch the old code fetched for [A, B, C]: the answer holds A and B only
    legacy = EM.ol_url([A_, B_, C_])
    with open(os.path.join(_ol_tmp, hashlib.sha256(legacy.encode()).hexdigest()[:32] + ".json"), "w") as f:
        json.dump({"ISBN:" + A_: OL_DB[A_], "ISBN:" + B_: OL_DB[B_]}, f)
    pos, neg = EM.ol_adopt([A_, B_, C_])
    eq("adopt: A and B positive, C negative (asked, not held)", (pos, neg), (2, 1))
    eq("adopt: C's entry is {} (covers.py skips it)", EM.ol_entry(C_), {})
    eq("adopt: zero requests", OL_CALLS, [])
    db = schema_db()
    db.execute("INSERT INTO work VALUES('w1','T',NULL,NULL,NULL,NULL,'x','x')")
    line_row(db, "rl_e", "w1", "manhwa", "EN", "en")
    for n, i in enumerate((A_, B_, C_, D_), 1):
        db.execute("INSERT INTO volume(id,release_line_id,number,isbn13,created_at,updated_at) "
                   "VALUES(?,?,?,?,'x','x')", ("v%d" % n, "rl_e", str(n), i))
    eq("plan: 4 ISBNs, 3 have entries, 1 missing, 1 request",
       EM.enrich_openlibrary(db, market="EN", plan=True), {"isbns": 4, "have": 3, "missing": 1, "requests": 1})
    eq("plan: zero requests", OL_CALLS, [])
    EM.enrich_openlibrary(db, market="EN")
    eq("only the uncached ISBN is fetched, alone (its URL IS its per-ISBN key)", OL_CALLS, [EM.ol_url([D_])])
    claims = sorted(db.execute("SELECT entity_id, field, value FROM claim WHERE source='openlibrary'"))
    eq("claims from per-ISBN entries (day, year, day; pages)", claims,
       [("v1", "page_count", "320"), ("v1", "release_date", "2021-03-02"), ("v2", "release_date", "2020"),
        ("v4", "page_count", "192"), ("v4", "release_date", "2020-09-02")])
    n = len(OL_CALLS)
    db.execute("DELETE FROM claim")
    EM.enrich_openlibrary(db, market="EN")
    eq("rerun: zero requests", len(OL_CALLS) - n, 0)
    V.urllib.request.urlopen = lambda req, timeout=None: (_ for _ in ()).throw(OSError("down"))
    E_ = "9780000000057"
    db.execute("INSERT INTO volume(id,release_line_id,number,isbn13,created_at,updated_at) "
               "VALUES('v5','rl_e','5',?,'x','x')", (E_,))
    EM.enrich_openlibrary(db, market="EN")
    eq("a failed fetch writes no negative entry", EM.ol_entry(E_), None)
finally:
    V.CACHE, V.urllib.request.urlopen = _saved_ol

# ---- Task 4 fix round: ol_adopt determinism + OL_NEG_REFRESH_DAYS ------------------------------
import time

_fix_tmp = tempfile.mkdtemp(prefix="krcn-olfix-")
_saved_fix = (V.CACHE, V.urllib.request.urlopen)
V.CACHE = _fix_tmp
try:
    WORSE = {"publish_date": "2017", "cover": {"large": "https://covers.openlibrary.org/b/id/99999999-L.jpg"}}
    BETTER = {"publish_date": "May 16, 2017", "cover": {"large": "https://covers.openlibrary.org/b/id/15251348-L.jpg"}}

    F_ = "9780000000064"       # worse record sorts first (file name "aaa...")
    with open(os.path.join(_fix_tmp, "aaa_batch.json"), "w") as f:
        json.dump({"ISBN:" + F_: WORSE}, f)
    with open(os.path.join(_fix_tmp, "zzz_batch.json"), "w") as f:
        json.dump({"ISBN:" + F_: BETTER}, f)
    EM.ol_adopt([])
    eq("ol_adopt: finer date precision wins even when the coarser record sorts first",
       EM.ol_entry(F_), BETTER)

    G_ = "9780000000071"       # same two variants, better record sorts first this time
    with open(os.path.join(_fix_tmp, "aaa_batch2.json"), "w") as f:
        json.dump({"ISBN:" + G_: BETTER}, f)
    with open(os.path.join(_fix_tmp, "zzz_batch2.json"), "w") as f:
        json.dump({"ISBN:" + G_: WORSE}, f)
    EM.ol_adopt([])
    eq("ol_adopt: the same winner regardless of which file sorts first", EM.ol_entry(G_), BETTER)

    H_ = "9780000000088"       # tied date; lowest positive cover id wins (6390630 < 15249132)
    COVER_HI = {"publish_date": "2019", "cover": {"large": "https://covers.openlibrary.org/b/id/15249132-L.jpg"}}
    COVER_LO = {"publish_date": "2019", "cover": {"large": "https://covers.openlibrary.org/b/id/6390630-L.jpg"}}
    with open(os.path.join(_fix_tmp, "aaa_batch3.json"), "w") as f:
        json.dump({"ISBN:" + H_: COVER_HI}, f)
    with open(os.path.join(_fix_tmp, "zzz_batch3.json"), "w") as f:
        json.dump({"ISBN:" + H_: COVER_LO}, f)
    EM.ol_adopt([])
    eq("ol_adopt: on a date tie, the lowest positive cover id wins", EM.ol_entry(H_), COVER_LO)

    # OL_NEG_REFRESH_DAYS / ol_needs_fetch, with a fake mtime
    I_ = "9780000000095"
    EM._put(I_, None)
    pi = EM.ol_isbn_path(I_)
    old_t, fresh_t = time.time() - 61 * 86400, time.time() - 10 * 86400
    os.utime(pi, (old_t, old_t))
    eq("a negative older than OL_NEG_REFRESH_DAYS (60) needs a refetch", EM.ol_needs_fetch(I_), True)
    os.utime(pi, (fresh_t, fresh_t))
    eq("a fresh negative (10 days) does not", EM.ol_needs_fetch(I_), False)
    os.utime(pi, (old_t, old_t))
    _saved_days = EM.OL_NEG_REFRESH_DAYS
    EM.OL_NEG_REFRESH_DAYS = 0
    eq("OL_NEG_REFRESH_DAYS=0 disables the retry even when stale", EM.ol_needs_fetch(I_), False)
    EM.OL_NEG_REFRESH_DAYS = _saved_days

    J_ = "9780000000101"
    EM._put(J_, {"publish_date": "2020"})
    os.utime(EM.ol_isbn_path(J_), (old_t, old_t))
    eq("a positive entry is never stale, however old", EM.ol_needs_fetch(J_), False)

    # _put(refresh=True): a repeat negative just touches mtime; an upgrade is written; a positive
    # is never overwritten either way
    L_ = "9780000000125"
    EM._put(L_, None)
    pl = EM.ol_isbn_path(L_)
    os.utime(pl, (old_t, old_t))
    eq("_put(refresh=True) with no new data leaves it negative", EM._put(L_, None, refresh=True), False)
    eq("... but resets the staleness clock", EM.ol_needs_fetch(L_), False)
    os.utime(pl, (old_t, old_t))
    eq("_put(refresh=True) upgrades a stale negative to positive",
       EM._put(L_, {"publish_date": "2021"}, refresh=True), True)
    eq("... entry is now positive", EM.ol_entry(L_), {"publish_date": "2021"})
    eq("a positive entry is never overwritten, even with refresh=True",
       EM._put(L_, {"publish_date": "1999"}, refresh=True), False)
    eq("... value unchanged", EM.ol_entry(L_), {"publish_date": "2021"})

    # A size-1 missing chunk's url IS that ISBN's own per-ISBN cache key: _fetch's ordinary cache
    # read would just re-serve the stale {} and never attempt a live call, silently resetting the
    # staleness clock forever without ever re-checking Open Library. enrich_openlibrary detects a
    # stale chunk and passes _fetch(fresh=True) to force the live attempt.
    O_ = "9780000000156"
    db_o = schema_db()
    db_o.execute("INSERT INTO work VALUES('w_o','TO',NULL,NULL,NULL,NULL,'x','x')")
    line_row(db_o, "rl_o2", "w_o", "manhwa", "EN", "en")
    db_o.execute("INSERT INTO volume(id,release_line_id,number,isbn13,created_at,updated_at) "
                 "VALUES('v_o1','rl_o2','1',?,'x','x')", (O_,))
    EM._put(O_, None)
    os.utime(EM.ol_isbn_path(O_), (old_t, old_t))
    OL_CALLS.clear()
    V.urllib.request.urlopen = ol_urlopen
    EM.enrich_openlibrary(db_o, market="EN")
    eq("a lone stale negative is actually retried, not just re-read from cache",
       OL_CALLS, [EM.ol_url([O_])])
    eq("still not held -> stays negative", EM.ol_entry(O_), {})
    # age it again and rerun: a SECOND real call, not a silent no-op reusing the first response
    os.utime(EM.ol_isbn_path(O_), (old_t, old_t))
    EM.enrich_openlibrary(db_o, market="EN")
    eq("re-staled and re-run: two identical calls, not one (still refetching each time)",
       OL_CALLS, [EM.ol_url([O_]), EM.ol_url([O_])])

    # integration: two stale negatives on one market are retried together in a single request
    M_, N_ = "9780000000132", "9780000000149"
    for _isbn in (M_, N_):
        EM._put(_isbn, None)
        os.utime(EM.ol_isbn_path(_isbn), (old_t, old_t))
    db_r = schema_db()
    db_r.execute("INSERT INTO work VALUES('w_r','TR',NULL,NULL,NULL,NULL,'x','x')")
    line_row(db_r, "rl_r", "w_r", "manhwa", "EN", "en")
    db_r.execute("INSERT INTO volume(id,release_line_id,number,isbn13,created_at,updated_at) "
                 "VALUES('v_r1','rl_r','1',?,'x','x')", (M_,))
    db_r.execute("INSERT INTO volume(id,release_line_id,number,isbn13,created_at,updated_at) "
                 "VALUES('v_r2','rl_r','2',?,'x','x')", (N_,))
    OL_DB[M_] = {"publish_date": "2021"}      # N_ stays unresolved -- OL still doesn't hold it
    OL_CALLS.clear()
    EM.enrich_openlibrary(db_r, market="EN")
    eq("stale negatives retried together in one request", OL_CALLS, [EM.ol_url(sorted([M_, N_]))])
    eq("the one OL now holds is upgraded to positive", EM.ol_entry(M_), {"publish_date": "2021"})
    eq("the one still not held stays negative", EM.ol_entry(N_), {})
    eq("... but its staleness clock was reset", EM.ol_needs_fetch(N_), False)
finally:
    V.CACHE, V.urllib.request.urlopen = _saved_fix

# ---- Task 5: link_work correction, scoped DNB unload --------------------------------------------------
import corrections as CORR, build_dnb as B, dnb_marc as M

cdir = tempfile.mkdtemp(prefix="krcn-corr-")
with open(os.path.join(cdir, "lines.json"), "w") as f:
    json.dump([{"line_key": "dnb:1200000000", "link_work": "w_aaaaaaaaaaaa",
                "source_url": "https://d-nb.info/1200000000", "checked": "2026-09-28"}], f)
eq("load_link_work", CORR.load_link_work(cdir), {"dnb:1200000000": "w_aaaaaaaaaaaa"})
with open(os.path.join(cdir, "lines.json"), "w") as f:
    json.dump([{"line_key": "isbn:978", "link_work": "w_aaaaaaaaaaaa", "source_url": "x", "checked": "x"}], f)
try:
    CORR.load_link_work(cdir)
    eq("a non-library key is refused", "no exception", "ValueError")
except ValueError:
    eq("a non-library key is refused", True, True)


def drec(idn, *fields, year="2019", parent=False):
    leader = "00000pam a2200000 c" + ("a" if parent else "c") + "4500"
    return {"leader": leader, "cf": {"001": idn, "008": "190101s%s    gw ||||| |||| 00||||ger  " % year},
            "df": [(t, " ", " ", list(s)) for t, s in fields]}


def dvol(idn, num, isbn, parent, title="Unbekannt Titel", origin=("h", "jpn")):
    return drec(idn, ("041", [("a", "ger"), origin]), ("082", [("a", "741.5")]),
                ("245", [("a", title), ("n", num)]), ("264", [("b", "Altraverse GmbH")]),
                ("020", [("a", isbn)]), ("773", [("w", "(DE-101)" + parent)]))


recs = {r["cf"]["001"]: r for r in (dvol("1300000001", "1", "9783753935874", "1200000000"),
                                    dvol("1300000002", "2", "9783753935881", "1200000000"))}
db = schema_db()
db.execute("INSERT INTO work VALUES('w_aaaaaaaaaaaa','Some Work',NULL,NULL,NULL,NULL,'x','x')")
idx = L.Index(db)
lines, _, _ = B.build(recs, {}, idx, {}, {})
eq("without the correction the line is unlinked", [(l["key"], l["role"]) for l in lines], [("dnb:1200000000", "unlinked")])
lines, _, _ = B.build(recs, {}, idx, {}, {}, link_work={"dnb:1200000000": "w_aaaaaaaaaaaa"})
eq("link_work: role linked to the named work, via correction",
   [(l["role"], l["work"], l["via"]) for l in lines], [("linked", "w_aaaaaaaaaaaa", "correction")])
lines, _, _ = B.build(recs, {}, idx, {}, {}, link_work={"dnb:1200000000": "w_000000000000"})
eq("link_work to a work not in the catalogue: stale, ignored", lines[0]["role"], "unlinked")

db = schema_db()
B.load(db, [], [], {}, {})                                     # creates the staging tables
db.execute("INSERT INTO dnb_member VALUES('1','dnb:1','1',NULL,'v_jp','created',NULL,0)")
db.execute("INSERT INTO dnb_line(key,rl_id,role,exported) VALUES('dnb:1','rl_jp','linked',1)")
for eid, ent in (("v_jp", "volume"), ("rl_jp", "release_line"), ("v_kr", "volume")):
    db.execute("INSERT INTO claim VALUES(?,?,'isbn13','x','dnb',NULL,'cc0','x')", (ent, eid))
B.unload(db.cursor())
eq("scoped unload: only 3e's own dnb claims go (a KR/CN 3f claim stays)",
   [r[0] for r in db.execute("SELECT entity_id FROM claim WHERE source='dnb'")], ["v_kr"])
db = schema_db()
B.load(db, [], [], {}, {})
db.execute("INSERT INTO dnb_line(key,rl_id,role,exported) VALUES('dnb:2','rl_wiki','merged',1)")
db.execute("INSERT INTO claim VALUES('release_line','rl_wiki','line_name','x','dnb',NULL,'cc0','x')")
B.unload(db.cursor())
eq("scoped unload: a merged row's rl_id is the Wikipedia line (3e writes no line claim there)",
   [r[0] for r in db.execute("SELECT entity_id FROM claim WHERE source='dnb'")], ["rl_wiki"])

# ---- Task 5 review fix: merged/sibling link_work lines -----------------------------------------------
import contextlib, io
eq("LIBRARY_KEY refuses a trailing newline", bool(CORR.LIBRARY_KEY.match("dnb:1200000000\n")), False)

# 3e: a link_work entry on a line that became merged by ISBN is logged (the ISBNs decide)
db = schema_db()
db.execute("INSERT INTO work VALUES('w_aaaaaaaaaaaa','Some Work',NULL,NULL,NULL,NULL,'x','x')")
db.execute("INSERT INTO work VALUES('w_bbbbbbbbbbbb','Other Work',NULL,NULL,NULL,NULL,'x','x')")
idx = L.Index(db)
W = {"rl_wiki": {"work": "w_aaaaaaaaaaaa", "vols": {"1": ("v_w1", "9783753935874"), "2": ("v_w2", "9783753935881")}}}
w_isbn = {"9783753935874": ("rl_wiki", "v_w1"), "9783753935881": ("rl_wiki", "v_w2")}
for lw, tail in (("w_aaaaaaaaaaaa", ")"), ("w_bbbbbbbbbbbb", ", CONFLICT)")):
    with contextlib.redirect_stdout(io.StringIO()) as out:
        lines, _, _ = B.build(recs, {}, idx, W, w_isbn, link_work={"dnb:1200000000": lw})
    eq("link_work on a merged line: the ISBNs decide (%s)" % lw,
       [(l["role"], l["work"], l.get("via")) for l in lines][0][:2], ("merged", "w_aaaaaaaaaaaa"))
    eq("link_work on a merged line: one build-log line (%s)" % lw, out.getvalue(),
       "  link_work dnb:1200000000: line is merged by ISBN under w_aaaaaaaaaaaa (link_work %s%s\n" % (lw, tail))

# test_artifact.run_link_work: merged / sibling ship under the corrected work -> pass; another work -> fail
import test_artifact as TA
catf = os.path.join(tempfile.mkdtemp(prefix="krcn-cat-"), "catalogue.db")
cat = sqlite3.connect(catf)
cat.executescript(open(os.path.join(ROOT, "schema", "schema.sql"), encoding="utf8").read() + B.STAGING_DDL)
cat.execute("INSERT INTO work VALUES('w_aaaaaaaaaaaa','Some Work',NULL,NULL,NULL,NULL,'x','x')")
for rid, wid in (("rl_wiki", "w_aaaaaaaaaaaa"), ("rl_sib", "w_aaaaaaaaaaaa"), ("rl_lnk", "w_aaaaaaaaaaaa")):
    cat.execute("INSERT INTO release_line(id,work_id,medium,market,language,created_at,updated_at) "
                "VALUES(?,?,'manga','DE','de','x','x')", (rid, wid))
for key, rid, role in (("dnb:10", "rl_wiki", "merged"), ("dnb:11", "rl_sib", "sibling"),
                       ("dnb:12", "rl_lnk", "linked"), ("dnb:13", "rl_oos", "out_of_scope")):
    cat.execute("INSERT INTO dnb_line(key,rl_id,role,exported) VALUES(?,?,?,1)", (key, rid, role))
cat.commit()
cat.close()
_saved_dir = CORR.DIR
try:
    for key, wid, want in (("dnb:10", "w_aaaaaaaaaaaa", 0), ("dnb:11", "w_aaaaaaaaaaaa", 0),
                           ("dnb:12", "w_aaaaaaaaaaaa", 0), ("dnb:10", "w_bbbbbbbbbbbb", 1),
                           ("dnb:11", "w_bbbbbbbbbbbb", 1), ("dnb:13", "w_aaaaaaaaaaaa", 1),
                           ("dnb:99", "w_aaaaaaaaaaaa", 0)):
        CORR.DIR = tempfile.mkdtemp(prefix="krcn-corr-")
        with open(os.path.join(CORR.DIR, "lines.json"), "w") as f:
            json.dump([{"line_key": key, "link_work": wid, "source_url": "x", "checked": "x"}], f)
        del TA.FAILS[:]
        with contextlib.redirect_stdout(io.StringIO()):
            TA.run_link_work(catf)
        eq("run_link_work %s -> %s: %d failure(s)" % (key, wid, want), len(TA.FAILS), want)
finally:
    CORR.DIR = _saved_dir
    del TA.FAILS[:]

# ---- Task 6: LoC MARC parsing --------------------------------------------------------------------------
import loc_marc as LM


def lrec(leader, f008, *fields, cid="1"):
    """A LoC record in dnb_marc's dict shape. fields: (tag, [(code, value), ...])."""
    return {"leader": leader, "cf": {"001": cid, "008": f008}, "df": [(t, " ", " ", list(s)) for t, s in fields]}


DLC = ("040", [("a", "DLC"), ("b", "eng"), ("e", "rda"), ("c", "DLC")])
VOL338 = ("338", [("a", "volume"), ("b", "nc")])
# spike cache f6427d408fe7b27ee63f7614921af690.xml -- the canary, Solo Leveling set record (trimmed to 5 volumes)
SL = lrec("05074cam a2200721 i 4500", "201115m20219999nyua     6    000 1 eng  ",
          ("010", [("a", "  2020950228")]),
          ("020", [("a", "9781975319434"), ("q", "v. 1"), ("q", "trade paperback")]),
          ("020", [("a", "9781975319458"), ("q", "v. 2"), ("q", "trade paperback")]),
          ("020", [("a", "9781975336516"), ("q", "v. 3"), ("q", "trade paperback")]),
          ("020", [("a", "9798400904646"), ("q", "v. 14 ;"), ("q", "trade paperback")]),
          ("020", [("a", "9798400904660"), ("q", "v. 15 ;"), ("q", "trade paperback")]),
          ("040", [("a", "DLC"), ("b", "eng"), ("e", "rda"), ("c", "DLC"), ("d", "DLC"), ("d", "DLC-MRC")]),
          ("041", [("a", "eng"), ("h", "kor")]), ("050", [("a", "PN8323.C43"), ("b", "N313 2021")]),
          ("082", [("a", "741.5/9519"), ("2", "23/eng/20250916")]),
          ("100", [("a", "Chang, Sŏng-nak,"), ("d", "1985-2022")]),
          ("240", [("a", "Na honja man lebel ŏp."), ("l", "English")]),
          ("245", [("a", "Solo leveling /"), ("c", "Dubu (Redice Studio) ; original story, Chugong ; translation, "
                                                  "Hye Young Im ; rewrite, J. Torres ; lettering, Abigail Blackman.")]),
          ("264", [("a", "New York, NY :"), ("b", "Yen Press/Ize Press,"), ("c", "2021-")]),
          ("300", [("a", "volumes"), ("b", "color illustrations")]), VOL338,
          ("655", [("a", "Webcomics")]), ("655", [("a", "Fantasy comics")]), ("655", [("a", "Fiction")]),
          ("700", [("a", "Im, Hye-Young"), ("e", "translator"), ("4", "http://id.loc.gov/vocabulary/relators/trl")]),
          ("700", [("a", "Torres, J.,"), ("e", "adapter"), ("4", "http://id.loc.gov/vocabulary/relators/adp")]),
          ("700", [("i", "Graphic novelization of (work):"), ("a", "Chugong."), ("t", "Na honjaman rebereop.")]),
          cid="21800815")
eq("lccn normalised", LM.lccn(SL), "2020950228")
for raw, want in (("   85012345 ", "85012345"), ("sf 99999999 ", "sf99999999"), ("2021-12345", "2021012345"),
                  ("85-2", "85000002"), ("2001-1114/AC/r932", "2001001114"), ("n  78890351 ", "n78890351"), ("", None)):
    eq("normalise_lccn %r" % raw, LM.normalise_lccn(raw), want)
eq("DLC", (LM.f040a(SL), LM.is_dlc(SL)), ("DLC", True))
eq("set record: >= 2 volume-qualified ISBNs", LM.is_set(SL), True)
eq("volume ISBNs incl. 'v. 14 ;'", sorted(LM.volume_isbns(SL), key=int), ["1", "2", "3", "14", "15"])
eq("origin 041$h kor, explicit", LM.origin(SL), ("kor", True))
eq("comic despite 655 'Fiction' (a comic signal is present)", LM.classify(SL), "comic")
eq("a set record never dates a volume (008 m2021)", LM.volume_date(SL, set_record=True), None)
eq("title proper without the ISBD ' /'", LM.title_proper(SL), "Solo leveling")
eq("original title from 240", LM.original_titles(SL), ["Na honja man lebel ŏp"])
eq("publisher family Yen/Ize", (LM.publisher(SL), LM.pubfam(LM.publisher(SL))), ("Yen Press/Ize Press", "yen"))
eq("creators: 100, the 700 source author, 245$c minus translator/rewrite/lettering",
   LM.creators(SL), ["Chang, Sŏng-nak", "Chugong", "Dubu (Redice Studio)"])
eq("url", LM.url("2020950228"), "https://lccn.loc.gov/2020950228")

# spike cache 632fc012e4541e27d5a39f9ace42f0b9.xml -- Semantic error, Ize Press, ECIP level 5, no 041
SE = lrec("02127cam a22004215i 4500", "240622m20249999nyua     6    000 1 eng  ",
          ("010", [("a", "  2024941070")]),
          ("020", [("a", "9798400902628"), ("q", "(v. 1 ;"), ("q", "trade paperback)")]),
          ("020", [("a", "9798400902642"), ("q", "(v. 2 ;"), ("q", "trade paperback)")]),
          ("020", [("z", "9798400902635"), ("q", "(ebook)")]), DLC,
          ("245", [("a", "Semantic error /"), ("c", "Angy, J. Soori.")]),
          ("264", [("a", "New York :"), ("b", "Ize Press,"), ("c", "2024.")]), ("300", [("a", "volumes cm")]), VOL338,
          cid="23743592")
eq("level 5 is preliminary", (LM.encoding_level(SE), LM.is_prelim(SE)), ("5", True))
eq("'(v. 1 ;' parses; $z (ebook) never read", sorted(LM.volume_isbns(SE)), ["1", "2"])
eq("Ize with no 041: origin by imprint, NOT explicit", LM.origin(SE), ("kor", False))
eq("level-5 Ize: class unresolved (no 082/050/655)", LM.classify(SE), "unresolved")

# spike cache 22ce8d0fffaff324c6c7389a91b3522b.xml -- I shall master this family: binding FIRST, 263 2610
IS = lrec("03868cam a22006258i 4500", "260330m20269999nyu    d 6    000 1 eng  ",
          ("010", [("a", "  2025045144")]),
          ("020", [("a", "9798217224234"), ("q", "trade paperback"), ("q", "v. 1")]),
          ("020", [("a", "9798217224241"), ("q", "hardcover"), ("q", "v. 1")]),
          ("020", [("z", "9798217224258"), ("q", "ebook"), ("q", "v. 1")]),
          ("020", [("a", "9798217224265"), ("q", "trade paperback"), ("q", "v. 2")]),
          DLC, ("041", [("a", "eng"), ("h", "kor")]), ("082", [("a", "741.5/973")]),
          ("245", [("a", "I shall master this family /"), ("c", "Mon (ANT Studio) ; original story by Roah Kim ; "
                                                               "English translation by Ciel.")]),
          ("263", [("a", "2610")]), ("264", [("b", "Ink Pop/RH Graphic,"), ("c", "2026-")]), VOL338,
          ("655", [("a", "Manhwa")]), cid="in00024521448")
v1 = LM.volume_isbns(IS)["1"]
eq("volume from the SECOND $q (P4)", [i for i, _ in v1], ["9798217224234", "9798217224241"])
eq("pick: the paperback", LM.pick_isbn(v1), "9798217224234")
eq("pick: the ISBN an OpenTome volume already has wins", LM.pick_isbn(v1, existing={"9798217224241"}), "9798217224241")
eq("pick: 'pbk.' counts as paperback (P5)", LM.pick_isbn([("9790000000001", "hardcover"), ("9790000000002", "v. 1 : pbk.")]),
   "9790000000002")
eq("263 YYMM -> YYYY-MM", LM.planned_month(IS), "2026-10")
eq("creators: 'original story by' label dropped, translator skipped", LM.creators(IS), ["Mon (ANT Studio)", "Roah Kim"])
# its ebook twin (same file, in00024522018): 338 online resource
ISE = lrec("03865nam a22006378i 4500", "260330m20269999nyu    do6    000 1 eng  ", ("010", [("a", "  2025045145")]),
           DLC, ("041", [("a", "eng"), ("h", "kor")]), ("300", [("a", "1 online resource")]),
           ("338", [("a", "online resource")]), cid="in00024522018")
eq("the ebook twin is not print", (LM.is_print(IS), LM.is_print(ISE)), (True, False))

# spike cache 089b92dbaca6989296fc485f1e27a845.xml -- Where's Joon?: 263 1111 = unknown
WJ = lrec("01689cam a22004218i 4500", "230302s2023    wau    b 6    000 1 eng  ", DLC, ("263", [("a", "1111")]))
eq("263 1111 is never a date", (LM.planned_month(WJ), LM.volume_date(WJ, set_record=False)), (None, None))
eq("a CIP (level 8) single record: its 008 date1 is an estimate -> no published date",
   LM.volume_date(WJ, set_record=False), None)
ym = "%d-%02d" % (Y, datetime.date.today().month)
CIPOK = lrec("01689cam a22004218i 4500", "230302s%d    wau    b 6    000 1 eng  " % Y, DLC, ("263", [("a", ym[2:4] + ym[5:7])]))
eq("a CIP single record with a real 263: projected month", LM.volume_date(CIPOK, set_record=False), (ym, "month", "projected"))

# spike cache 63dffb827013cb587ea4f9f676907640.xml -- Mystery Science Detectives book 3, single volume
MS = lrec("04168cam a2200637 i 4500", "250325s2025    mnua   c 6    000 1 eng  ",
          ("010", [("a", "  2025007302")]), ("020", [("a", "9798765627495"), ("q", "library binding")]),
          ("020", [("a", "9798765627549"), ("q", "paperback")]), DLC, ("041", [("a", "eng"), ("h", "kor")]),
          ("082", [("a", "741.5/973")]),
          ("245", [("a", "The case of the underwater aliens /"),
                   ("c", "Chi-hyeon Ahn ; illustrated by Gyung-hyo Kang ; translated from the Korean by Gloria Ohe.")]),
          ("300", [("a", "135 pages"), ("b", "color illustrations")]), VOL338,
          ("490", [("a", "Mystery Science Detectives ;"), ("v", "book 3")]), ("655", [("a", "Graphic novels")]))
eq("single volume: not a set", LM.is_set(MS), False)
eq("single volume: 008 s, deposited -> year published", LM.volume_date(MS, set_record=False), ("2025", "year", "published"))
eq("single volume: pages", LM.pages(MS), 135)
eq("single volume: number from 490 $v 'book 3'", LM.volume_number(MS), "3")
eq("single volume: the paperback ISBN", LM.pick_isbn([(i, q) for _, i, q in LM.qualified_isbns(MS)]), "9798765627549")

# spike cache cc3d41a4a6d0e888803b217b53434e3f.xml -- The three-body problem (comic), 041$h chi; its 880 is a 700's
TB = lrec("05270cam a2200673 i 4500", "240521m20249999nyua     6    000 1 eng  ", DLC,
          ("041", [("a", "eng"), ("h", "chi")]), ("050", [("a", "PN6790.C44")]), ("082", [("a", "741.5/951")]),
          ("245", [("a", "The three-body problem :"), ("b", "the comic edition /")]),
          ("880", [("6", "700-64/$1"), ("i", "Graphic novelization of"), ("a", "刘慈欣"), ("t", "三体")]))
eq("041$h chi -> manhua origin", LM.origin(TB), ("chi", True))
eq("comic by 050 PN6790 + 082 741.5", LM.classify(TB), "comic")
eq("an 880 linked to a 700 is not a native title", LM.native_titles(TB), [])
eq("880 linked to 245 is", LM.native_titles(lrec("", "", ("880", [("6", "245-01/$1"), ("a", "나 혼자만 레벨업 /")]))),
   ["나 혼자만 레벨업"])

# spike cache 63dffb827013cb587ea4f9f676907640.xml -- Please look after mom (prose)
PM = lrec("01196cam a2200325 a 4500", "100901s2011    nyu           000 1 eng  ", ("040", [("a", "DLC"), ("c", "DLC")]),
          ("041", [("a", "eng"), ("h", "kor")]), ("050", [("a", "PL992.73.K94")]), ("082", [("a", "895.7/3")]),
          ("245", [("a", "Please look after mom :"), ("b", "a novel /")]))
eq("prose: 082 895.7 + 050 PL", LM.classify(PM), "prose")
eq("both a comic and a prose signal -> both (review)",
   LM.classify(lrec("", "", ("082", [("a", "895.73")]), ("655", [("a", "Graphic novels")]))), "both")

# synthesised shape (spike 073e4d0f… is a ZCU/OCLC record -- never copied): a non-DLC
# copy-catalogued record. Only its 040 $a is read (R4: a non-DLC record is not read past is_dlc);
# the field checks run on the same shape as a DLC record, a Korean-LANGUAGE original held by LoC.
KO_FIELDS = (("041", [("a", "kor"), ("h", "kor")]), ("020", [("a", "9791191841466"), ("q", "volume 1")]))
KO = lrec("03986cam a2200721 i 4500", "230802m20239999ko a     6    000 1 kor d",
          ("040", [("a", "ZCU"), ("d", "DLC")]), *KO_FIELDS)
KO_DLC = lrec("03986cam a2200721 i 4500", "230802m20239999ko a     6    000 1 kor d", DLC, *KO_FIELDS)
eq("non-DLC is not DLC (040 $d DLC does not make it LoC-created)", LM.is_dlc(KO), False)
eq("a Korean-language original is out of scope", LM.origin(KO_DLC), (None, False))
eq("'$q volume 1' parses too (P4)", list(LM.volume_isbns(KO_DLC)), ["1"])
eq("box set excluded", LM.excluded_kind(lrec("", "", ("245", [("a", "Solo leveling box set /")]))), "bundle")
eq("art book excluded", LM.excluded_kind(lrec("", "", ("245", [("a", "The art of Solo leveling /")]))), "extra")
src = open(os.path.join(HERE, "loc_marc.py"), encoding="utf8").read()
eq("loc_marc never names 520 / 856 / 906 / 923 / 925 / 955 as a tag",
   [t for t in ("520", "856", "906", "923", "925", "955") if '"%s"' % t in src or "'%s'" % t in src], [])

LOCXML = ('<?xml version="1.0"?><zs:searchRetrieveResponse xmlns:zs="http://www.loc.gov/zing/srw/"><zs:version>1.1'
          '</zs:version><zs:numberOfRecords>1</zs:numberOfRecords><zs:records><zs:record><zs:recordSchema>marcxml'
          '</zs:recordSchema><zs:recordData><record xmlns="http://www.loc.gov/MARC21/slim"><leader>05074cam a2200721 i '
          '4500</leader><controlfield tag="001">21800815</controlfield><controlfield tag="008">201115m20219999nyua     '
          '6    000 1 eng  </controlfield><datafield tag="010" ind1=" " ind2=" "><subfield code="a">  2020950228'
          '</subfield></datafield><datafield tag="040" ind1=" " ind2=" "><subfield code="a">DLC</subfield>'
          '</datafield></record></zs:recordData></zs:record></zs:records></zs:searchRetrieveResponse>')
eq("dnb_marc.records parses LoC marcxml (same MARC21 slim namespace)",
   [(LM.lccn(r), LM.is_dlc(r)) for r in M.records(LOCXML)], [("2020950228", True)])

# ---- Task 6 review fixes ----------------------------------------------------------------------------
# spike cache f58430827d9be5719f7d55f1ffd3817d.xml -- Ransei ni eiyū arawaru: a JAPANESE translation of a Chinese comic
RS = lrec("02104cam a22005174a 4500", "080804s1990    ja ab         000 c jpn  ", ("040", [("a", "DLC"), ("c", "DLC")]),
          ("041", [("a", "jpn"), ("h", "chi")]), ("050", [("a", "PN6790.C44")]),
          ("245", [("a", "Ransei ni eiyū arawaru /")]))
eq("origin: a LoC line is English -- 008 jpn with 041 $h chi is not KR/CN", LM.origin(RS), (None, False))
# spike cache f6a8890ec5bdf5ffe5f71c0df5a118ef.xml -- The blue dragon: $h fre + $h chi (a relay translation)
BD = lrec("01593cam a2200409 a 4500", "110531s2011    onca          000 0 eng  ", ("010", [("a", "  2011930915")]),
          ("040", [("a", "DLC"), ("c", "DLC"), ("d", "DLC")]), ("041", [("a", "eng"), ("b", "chi"), ("h", "fre"), ("h", "chi")]),
          ("245", [("a", "The blue dragon /")]))
eq("origin: an 041 $h naming a non-KR/CN language too is not KR/CN", LM.origin(BD), (None, False))
eq("origin: $h kor + $h chi still reads (a subset of KR/CN)",
   LM.origin(lrec("", "x" * 35 + "eng", DLC, ("041", [("a", "eng"), ("h", "chi"), ("h", "kor")]))), ("kor", True))

# synthesised shape: the Solo Leveling: Ragnarok set record (not in the spike cache as DLC)
RAG = lrec("02000cam a2200400 i 4500", "240801m20249999nyua     6    000 1 eng  ", DLC, ("041", [("a", "eng"), ("h", "kor")]),
           ("020", [("a", "9798400904646"), ("q", "v. 1"), ("q", "trade paperback")]),
           ("020", [("a", "9798400904660"), ("q", "v. 2"), ("q", "trade paperback")]),
           ("245", [("a", "Solo leveling :"), ("b", "Ragnarok /"), ("c", "Daul ; original story, Chugong.")]))
eq("full title keeps 245 $b (a sequel is not its parent)", LM.full_title(RAG), "Solo leveling : Ragnarok")
eq("the full title is a linker title (variant_titles, read by build_krcn._loc_titles)",
   LM.variant_titles(RAG), ["Solo leveling : Ragnarok"])
eq("no $b: no extra variant", LM.variant_titles(SL), [])
PT = lrec("", "", ("245", [("a", "Tower of god."), ("n", "Part 2,"), ("p", "The floor of death /")]))
eq("title proper carries $n / $p (§5)", LM.title_proper(PT), "Tower of god. Part 2. The floor of death")
eq("bare title strips a trailing $n number",
   LM.bare_title(lrec("", "", ("245", [("a", "Tower of god."), ("n", "1 /")]))), "Tower of god")

# spike cache 9ba96fe121a928a66a6490da7b24628e.xml -- Bottom-tier character Tomozaki ('v. 6.5 : pbk.'), shape
HV = lrec("", "", DLC, ("020", [("a", "9781975319458"), ("q", "v. 5 : pbk.")]),
          ("020", [("a", "9781975320386"), ("q", "v. 5.5 : pbk.")]), ("020", [("a", "9781975338404"), ("q", "v. 05")]))
hv = LM.volume_isbns(HV)
eq("decimal volume stays its own number; '05' canonicalises", sorted(hv), ["5", "5.5"])
eq("pick for vol 5 never takes the 5.5 ISBN, even when an OpenTome volume has it",
   LM.pick_isbn(hv["5"], existing={"9781975320386"}), "9781975319458")
eq("vol 5.5 picks its own", LM.pick_isbn(hv["5.5"]), "9781975320386")
# spike cache shapes: Karneval 'pbk. : v. 1' (4d90fc5d…), Btooom! '1 : pbk' (ee535b32…), The irregular at Magic
# High School 'bk. 1' (3a989100…), The twelve kingdoms 'hbk. : v. 1 : alk paper' (4e76926a…), '6-pack' (885abf93…)
for q, want in (("pbk. : v. 3", "3"), ("1 : pbk", "1"), ("2 : pbk.", "2"), ("bk. 4", "4"), ("hbk. : v. 7 : alk paper", "7"),
                ("(v. 1 ;", "1"), ("v. 14 ;", "14"), ("volume 1", "1"), ("trade paperback", None), ("6-pack", None),
                ("26 light : pbk", None), ("(ebook)", None), ("hardcover", None)):
    eq("$q %r -> volume %r" % (q, want),
       [n for n, _, _ in LM.qualified_isbns(lrec("", "", ("020", [("a", "9781975319434"), ("q", q)]))) ], [want])

SG = lrec("01515cam a22003135i 4500", "240731s2024    nyu           000 0 eng  ", DLC,
          ("020", [("a", "9781975397838"), ("q", "(v. 1 ;"), ("q", "trade paperback)")]),
          ("020", [("a", "9798855412048"), ("q", "(v. 2 ;"), ("q", "trade paperback)")]),
          ("245", [("a", "I Picked Up This World's Strategy Guide /")]))   # spike cache a78527b9530285a6678adc8cd81cc762.xml
eq("a title with 'Guide' is not an extra", LM.excluded_kind(SG), None)
eq("'The Genius Prince's Guide' single record is not an extra",
   LM.excluded_kind(lrec("", "", ("245", [("a", "The genius prince's guide to raising a nation out of debt /")]))), None)
eq("an official guide is", LM.excluded_kind(lrec("", "", ("245", [("a", "Solo leveling official visual guide /")]))), "extra")
eq("a guidebook is", LM.excluded_kind(lrec("", "", ("245", [("a", "Tower of god guidebook /")]))), "extra")
eq("a SET record is never an extra on its title words",
   LM.excluded_kind(lrec("", "", ("245", [("a", "The art of war /")]), ("020", [("a", "9781975397838"), ("q", "v. 1")]),
                         ("020", [("a", "9798855412048"), ("q", "v. 2")]))), None)
eq("a single 'art of' record still is", LM.excluded_kind(lrec("", "", ("245", [("a", "The art of war /")]))), "extra")

# spike cache c71306a3711ed5a62a382ca2e5499f7a.xml -- 'viii, 120 p. :'
for a, want in (("viii, 106 p.", 106), ("ix, 326 pages", 326), ("135 pages", 135), ("volumes", None), ("1 online resource", None)):
    eq("pages %r" % a, LM.pages(lrec("", "", ("300", [("a", a)]))), want)

eq("040 $a DLC with a non-LoC $d (OCoLC) is still LoC-created (§2)",
   LM.is_dlc(lrec("", "", ("040", [("a", "DLC"), ("b", "eng"), ("c", "DLC"), ("d", "OCoLC"), ("d", "DLC")]))), True)


# ---- Task 7: lib_sru (against a fake SRU server), BnF parsing, BnF channels -----------------------------
import email.message, urllib.error, urllib.parse
import lib_sru as SRU, bnf_unimarc as U, bnf_sru as BS


def mxc_rec(i, extra=""):
    return ('<mxc:record xmlns:mxc="info:lc/xmlns/marcxchange-v2"><mxc:leader>     cam  22        450 </mxc:leader>'
            '<mxc:controlfield tag="001">FRBNF%08d0000000</mxc:controlfield><mxc:controlfield tag="003">'
            'http://catalogue.bnf.fr/ark:/12148/cb%08dx</mxc:controlfield>%s</mxc:record>' % (i, i, extra))


FAKE = {"ids": list(range(1, 6)), "refuse": 0, "diag": None, "fail_page": None, "short": False}
FCALLS, FAT, CLOCK = [], [], [2_000_000.0]


class _R:
    def __init__(self, t):
        self.t = t.encode()

    def read(self):
        return self.t

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_sru(req, timeout=None):
    FCALLS.append(req.full_url)
    FAT.append(CLOCK[0])
    UA_SEEN.append(req.get_header("User-agent"))
    if FAKE["refuse"]:
        FAKE["refuse"] -= 1
        h = email.message.Message()
        h["Retry-After"] = "7"
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many", h, None)
    q = urllib.parse.parse_qs(urllib.parse.urlparse(req.full_url).query)
    start, size = int(q["startRecord"][0]), int(q["maximumRecords"][0])
    if FAKE["diag"] or (FAKE["fail_page"] and start == FAKE["fail_page"]):
        return _R('<srw:searchRetrieveResponse xmlns:srw="x"><srw:numberOfRecords>%d</srw:numberOfRecords>'
                  '<srw:diagnostics><sd:diagnostic xmlns:sd="y"><sd:uri>info:srw/diagnostic/1/%s</sd:uri>'
                  '<sd:message>boom</sd:message></sd:diagnostic></srw:diagnostics></srw:searchRetrieveResponse>'
                  % (len(FAKE["ids"]), FAKE["diag"] or "61"))
    ids = FAKE["ids"][start - 1:start - 1 + size]
    if FAKE["short"]:
        ids = ids[:-1]
    return _R('<srw:searchRetrieveResponse xmlns:srw="x"><srw:numberOfRecords>%d</srw:numberOfRecords><srw:records>%s'
              '</srw:records></srw:searchRetrieveResponse>' % (len(FAKE["ids"]), "".join(mxc_rec(i) for i in ids)))


def fsleep(s):
    SLEEPS2.append(s)
    CLOCK[0] += s


UA_SEEN, SLEEPS2 = [], []
_src_tmp = tempfile.mkdtemp(prefix="krcn-sru-")
T = SRU.Source("tst", "http://x.invalid/sru", "1.2", "unimarcxchange", 2, "test data", budget=0)
T.relocate(_src_tmp, _src_tmp)
T.offline, T.refresh_days, T.urlopen, T.sleep, T.now = False, 0, fake_sru, fsleep, lambda: CLOCK[0]
n, pages = T.search("q1")
eq("cold search: every page (5 records at 2 per page = 3 requests), complete", (n, T.distinct(pages), len(FCALLS)), (5, 5, 3))
eq("throttle: >= 3 s between requests", min(b - a for a, b in zip(FAT, FAT[1:])) >= 3.0, True)
eq("descriptive User-Agent", "OpenTome/0.1" in UA_SEEN[0] and ">=3s" in UA_SEEN[0], True)
eq("manifest written after completeness", json.load(open(T.sets_path))["q1"]["n"], 5)
k = len(FCALLS)
T.search("q1")
eq("rerun: zero requests", len(FCALLS) - k, 0)
eq("netlog: one line per live request", sum(1 for _ in open(T.netlog)), len(FCALLS))
FAKE["short"] = True
try:
    T.search("q2")
    eq("a page short of records: incomplete", "no exception", "SourceIncomplete")
except SRU.SourceIncomplete:
    eq("a page short of records: incomplete, nothing cached", T.cached_set("q2"), None)
FAKE["short"] = False
FAKE["refuse"] = 1
T.search("q3")
eq("one 429: waits out Retry-After (7 s), then succeeds", 7 in SLEEPS2, True)
FAKE["refuse"] = 1
try:
    T.search("q4")
    eq("a second 429 in the run stops it", "no exception", "SourceIncomplete")
except SRU.SourceIncomplete as e:
    eq("a second 429 in the run stops it (no cached set: incomplete)", "SourceThrottled" in str(e), True)
T.refusals = 0
FAKE["diag"] = "10"
u = T.url_for("q5", 1, 1)
try:
    T.get(u)
    eq("a diagnostic raises", "no exception", "SourceDiagnostic")
except SRU.SourceDiagnostic as e:
    eq("a diagnostic raises with its code, and is not cached", (e.code, os.path.exists(T.cache_path(u))), ("10", False))
FAKE["diag"] = None
T.offline = True
try:
    T.search("q-never")
    eq("offline: a miss raises", "no exception", "SourceOfflineMiss")
except SRU.SourceOfflineMiss:
    eq("offline: a miss raises", True, True)
T.offline, T.refresh_days = False, 1
CLOCK[0] += 3 * 86400                               # q1 is stale now
FAKE["ids"], FAKE["fail_page"] = list(range(1, 7)), 3
n, pages = T.search("q1", refresh=True)
eq("refresh fails on page 2 (bounded retry spent): the previous complete set is kept, whole",
   (n, T.distinct(pages), bool(T.degraded), "q1" in T.degraded_queries), (5, 5, True, True))
FAKE["fail_page"] = None
T.degraded, T.degraded_queries = None, []
T.budget, T.live = 1, 1
try:
    T.fetch(T.url_for("q6"))
    eq("budget: <NAME>_MAX_REQUESTS stops the run", "no exception", "SourceBudget")
except SRU.SourceBudget:
    eq("budget: <NAME>_MAX_REQUESTS stops the run", True, True)

# ---- Task 7 review fixes: lib_sru -------------------------------------------------------------------
import socket, http.client

T.budget, T.live = 0, 0
FAKE["ids"] = list(range(1, 6))


def fake_raising(exc):
    def f(req, timeout=None):
        FCALLS.append(req.full_url)
        FAT.append(CLOCK[0])
        UA_SEEN.append(req.get_header("User-agent"))

        class _X(_R):
            def read(self):
                raise exc
        return _X("")
    return f


def netlog_statuses():
    return [line.split("\t")[1] for line in open(T.netlog, encoding="utf8")]


for label, exc in (("socket.timeout", socket.timeout("timed out")),
                   ("http.client.IncompleteRead", http.client.IncompleteRead(b"x", 10))):
    T.urlopen, k = fake_raising(exc), len(netlog_statuses())
    try:
        T.search("q-cold-" + label)
        eq("a read failure (%s) on a cold set" % label, "no exception", "SourceIncomplete")
    except SRU.SourceIncomplete as e:
        eq("a read failure (%s) on a cold set: 3 ERR netlog lines, SourceIncomplete(URLError)" % label,
           (netlog_statuses()[k:], "URLError" in str(e)), (["ERR"] * 3, True))
T.urlopen = fake_raising(socket.timeout("timed out"))
CLOCK[0] += 3 * 86400
n, pages = T.search("q1", refresh=True)
eq("a read timeout refreshing a stale cached set: degraded, the previous set kept whole",
   (n, T.distinct(pages), "URLError" in (T.degraded or ""), "q1" in T.degraded_queries), (5, 5, True, True))
T.urlopen = fake_sru
k = len(FCALLS)
for label, url, force in (("a miss", T.url_for("q-miss", 1, 1), False), ("a force of a cached page", T.url_for("q1", 1), True)):
    try:
        T.get(url, force=force)
        eq("get() while degraded: %s raises" % label, "no exception", "SourceIncomplete")
    except SRU.SourceIncomplete:
        eq("get() while degraded: %s raises SourceIncomplete, zero requests" % label, len(FCALLS) - k, 0)
T.degraded, T.degraded_queries = None, []
T.refusals = 2
try:
    T.fetch(T.url_for("q-sticky"))
    eq("the 429 stop is sticky", "no exception", "SourceThrottled")
except SRU.SourceThrottled:
    eq("the 429 stop is sticky: SourceThrottled before anything is sent", len(FCALLS) - k, 0)
T.refusals = 0
os.utime(T.stamp, (CLOCK[0] + 1e6, CLOCK[0] + 1e6))
j = len(SLEEPS2)
T.fetch(T.url_for("q-future-stamp"))
eq("a future-dated stamp: the throttle waits at most one interval", max(SLEEPS2[j:] or [0]) <= T.interval, True)
two = ('<srw:searchRetrieveResponse xmlns:srw="x"><srw:numberOfRecords>2</srw:numberOfRecords>%s'
       '</srw:searchRetrieveResponse>')
T.store_set("q-verify", 2, [("http://x.invalid/v1", two % (mxc_rec(1) + mxc_rec(2)))])
eq("cached_set: a whole set reads back", T.cached_set("q-verify")[0], 2)
with open(T.cache_path("http://x.invalid/v1"), "w", encoding="utf8") as f:
    f.write(two % mxc_rec(1))
eq("cached_set: a page no longer holding n distinct records is not a cached set", T.cached_set("q-verify"), None)
T.search("q-empty")
CLOCK[0] += 3 * 86400
FAKE["ids"] = []
n, pages = T.search("q-empty", refresh=True)
eq("a refresh announcing 0 records while the cached set holds 5: kept, degraded",
   (n, T.distinct(pages), bool(T.degraded), "q-empty" in T.degraded_queries), (5, 5, True, True))
FAKE["ids"] = list(range(1, 6))
T.degraded, T.degraded_queries = None, []

# BnF records, transcribed from spike cache c03c4c6db8ca8f4a16acb184655af793.xml (Kbooks), 27560a21… (Xiao Pan),
# 2086741f… (Tokebi)
def bdf(tag, *subs, ind2=" "):
    return '<mxc:datafield tag="%s" ind1=" " ind2="%s">%s</mxc:datafield>' % (
        tag, ind2, "".join('<mxc:subfield code="%s">%s</mxc:subfield>' % s for s in subs))


GAMER = ('<srw:searchRetrieveResponse xmlns:srw="x"><srw:numberOfRecords>1</srw:numberOfRecords><srw:records>'
         '<mxc:record xmlns:mxc="info:lc/xmlns/marcxchange-v2"><mxc:leader>     cam  22        450 </mxc:leader>'
         '<mxc:controlfield tag="001">FRBNF472537730000009</mxc:controlfield>'
         '<mxc:controlfield tag="003">http://catalogue.bnf.fr/ark:/12148/cb47253773p</mxc:controlfield>'
         + bdf("010", ("a", "978-2-38288-037-1"), ("b", "br."), ("d", "14,95 EUR"))
         + bdf("100", ("a", "20230525d2023    m  y0frey50      ba")) + bdf("101", ("a", "fre"), ("c", "kor"))
         + bdf("200", ("a", "The gamer"), ("h", "1"), ("b", "Texte imprimé"), ("f", "histoire, Seong Sang-Yeong"))
         + bdf("214", ("a", "Paris"), ("c", "Kbooks"), ("d", "DL 2023"), ind2="0")
         + bdf("215", ("a", "1 vol. (235 p.)"), ("c", "ill. en coul."))
         + bdf("461", ("0", "47268502"), ("t", "The gamer"), ("v", "1"))
         + bdf("700", ("a", "Seong"), ("b", "Sang-Yeong"), ("4", "070")) + bdf("702", ("a", "Sang-A"), ("4", "440"))
         + bdf("856", ("u", "770731"), ("b", "Première de couverture"))
         + '</mxc:record></srw:records></srw:searchRetrieveResponse>')
g = U.records(GAMER)[0]
eq("ark from 003, https url", (U.ark(g), U.url(U.ark(g))),
   ("ark:/12148/cb47253773p", "https://catalogue.bnf.fr/ark:/12148/cb47253773p"))
eq("ark order is numeric, check character ignored", U.ark_number("ark:/12148/cb47253773p"), 47253773)
eq("ISBN (hyphens) -> 13", U.isbns(g), ["9782382880371"])
eq("origin 101 $c kor; monograph; not a set record", (U.origin(g), U.is_monograph(g), U.is_set_record(g)), ("kor", True, False))
eq("volume 200 $h, series 461 $t, publisher, year from 214 $d", (U.volume_number(g), U.series(g), U.publisher(g), U.year(g)),
   ("1", "The gamer", "Kbooks", "2023"))
eq("pages '1 vol. (235 p.)'", U.pages(g), 235)
eq("creators 070 + 440", U.creators(g), ["Seong Sang-Yeong", "Sang-A"])
eq("Kbooks family", (U.pubfam("Kbooks"), U.pubfam("Delcourt-Kbooks"), U.pubfam("Groupe Delcourt-Kbooks")),
   ("kbooks", "kbooks", "kbooks"))


def brec(*fields, leader="     cam  22        450 ", cf3="http://catalogue.bnf.fr/ark:/12148/cb00000001x"):
    return {"leader": leader, "cf": {"001": "FRBNF1", "003": cf3}, "df": [(t, " ", " ", list(s)) for t, s in fields]}


box = brec(("010", [("a", "978-2-38288-170-5"), ("b", "rel. sous étui")]), ("200", [("a", "Solo leveling"), ("h", "Volumes 4-6")]),
           ("215", [("a", "3 vol. (258, 258, 268 p.)")]))
eq("'Volumes 4-6', 'sous étui': a box, not a volume", U.excluded_kind(box), "bundle")
eq("a 3-volume extent gives no page count", U.pages(box), None)
jen = brec(("010", [("a", "2-940380-07-4")]), ("101", [("a", "fre"), ("c", "chi")]), ("200", [("a", "Jenni")]),
           ("210", [("c", "Xiao Pan"), ("d", "2006")]), ("215", [("a", "226 p.")]))
eq("ISBN-10 converted; chi origin; one-shot (no number)", (U.isbns(jen), U.origin(jen), U.volume_number(jen)),
   (["9782940380077"], "chi", None))
niu = brec(("101", [("a", "fre")]), ("200", [("a", "Niumao"), ("h", "2")]))
eq("no 101 $c: out of scope (the French manhua gap, §4)", U.origin(niu), None)
omega = brec(("101", [("a", "fre"), ("c", "kor")]), ("200", [("a", "Omega")]), ("210", [("c", "Tokebi"), ("d", "2003-")]),
             ("454", [("t", "The hum")]), leader="     nam  22        450 ")
eq("an open-dated record with no 200 $h is a set record (P8)", U.is_set_record(omega), True)
eq("original title 454 $t", U.original_titles(omega), ["The hum"])
# review fixes: 10+ volume extents, the 214 publication statement by ind2, roman / word volume numbers,
# 101 $b relay language (information only)
for a in ("10 vol. (180, 176 p.)", "12 vol.", "3 vol."):
    eq("pages %r: several volumes, no page count" % a, U.pages(brec(("215", [("a", a)]))), None)
eq("pages '1 vol. (235 p.)' still read", U.pages(brec(("215", [("a", "1 vol. (235 p.)")]))), 235)
printer_first = {"leader": "     cam  22        450 ", "cf": {"001": "FRBNF1"},
                 "df": [("214", " ", "3", [("a", "Barcelone"), ("c", "Impr. Liberduplex"), ("d", "impr. 2019")]),
                        ("214", " ", "0", [("a", "Paris"), ("c", "Kbooks"), ("d", "DL 2023")])]}
eq("214 ind2 0 is the publisher and date, whatever the field order (ind2 3 = the printer)",
   (U.publisher(printer_first), U.year(printer_first)), ("Kbooks", "2023"))
for h, want in (("IV", "4"), ("Tome I", "1"), ("Vol. VI", "6"), ("XX", "20"), ("One", "1"), ("three", "3"),
                ("XXI", None), ("Volume", None)):
    eq("200 $h %r -> volume %r" % (h, want), U.volume_number(brec(("200", [("a", "X"), ("h", h)]))), want)
relayed = brec(("101", [("a", "fre"), ("b", "eng"), ("c", "kor")]))
eq("101 $b relay language exposed; origin unaffected (a relayed French edition stays in scope)",
   (U.relay_languages(relayed), U.origin(relayed), U.relay_languages(g)), (["eng"], "kor", []))
src = open(os.path.join(HERE, "bnf_unimarc.py"), encoding="utf8").read()
eq("bnf_unimarc never names 856", '"856"' in src or "'856'" in src, False)
eq("BnF channels: the §4 allowlist, 8 channels", len(BS.CHANNELS), 8)
eq("BnF page size 500, budget 60, >= 3 s", (BS.BNF.page, BS.BNF.budget >= 20, BS.BNF.interval >= 3.0), (500, True, True))


# ---- Task 8: LoC client (fake gateway with diagnostic 61) -------------------------------------------------
import loc_sru as LS

LREC = ('<zs:record><zs:recordData><record xmlns="http://www.loc.gov/MARC21/slim"><leader>00000cam a2200000 i 4500'
        '</leader><controlfield tag="001">%s</controlfield><controlfield tag="008">210101s2021    nyu           000 1 eng  '
        '</controlfield><datafield tag="010" ind1=" " ind2=" "><subfield code="a">  %s</subfield></datafield>'
        '<datafield tag="040" ind1=" " ind2=" "><subfield code="a">%s</subfield></datafield>%s</record></zs:recordData></zs:record>')
DIAG61 = ('<?xml version="1.0"?><zs:searchRetrieveResponse xmlns:zs="http://www.loc.gov/zing/srw/"><zs:version>1.1'
          '</zs:version><zs:numberOfRecords>%d</zs:numberOfRecords><zs:diagnostics xmlns:diag="http://www.loc.gov/zing/'
          'srw/diagnostic/"><diag:diagnostic><diag:uri>info:srw/diagnostic/1/%s</diag:uri><diag:details></diag:details>'
          '<diag:message>First record position out of range</diag:message></diag:diagnostic></zs:diagnostics>'
          '</zs:searchRetrieveResponse>')
LOCDB = {}                      # id -> (isbns, dlc)
LRULE = {"fail": lambda q, start, size, seen: False, "code": "61"}
LSEEN, LCALLS = {}, []


def loc_matches(q, isbns):
    m = re.fullmatch(r"bath\.isbn=(\d+)(\*?)", q)
    if m:
        return any((i.startswith(m.group(1)) if m.group(2) else i == m.group(1)) for i in isbns)
    return q == 'dc.subject="webcomics"'


def _lwin(query, ids, start, size):
    win = ids[start - 1:start - 1 + size]
    return win[:-1] if LRULE.get("short", lambda q, st, sz: False)(query, start, size) else win


def fake_loc(req, timeout=None):
    LCALLS.append(req.full_url)
    q = urllib.parse.parse_qs(urllib.parse.urlparse(req.full_url).query)
    query, start, size = q["query"][0], int(q["startRecord"][0]), int(q["maximumRecords"][0])
    ids = sorted(i for i, (isb, _) in LOCDB.items() if loc_matches(query, isb))
    ids = LRULE.get("seq", lambda q, ids, sz: ids)(query, ids, size)     # duplicate positions
    key = (query, start, size)
    LSEEN[key] = LSEEN.get(key, 0) + 1
    if LRULE.get("drop", lambda q, st, sz: False)(query, start, size):
        raise http.client.RemoteDisconnected("Remote end closed connection without response")
    if "raw" in LRULE and query in LRULE["raw"]:
        return _R(LRULE["raw"][query])
    if size > 1 and LRULE["fail"](query, start, size, LSEEN[key]):
        return _R(DIAG61 % (len(ids), LRULE["code"]))
    if start > 1 and start > len(ids):                  # the real gateway: past the end is 61
        return _R(DIAG61 % (len(ids), "61"))
    body = "".join(LREC % (i, "20%08d" % int(i), "DLC" if LOCDB[i][1] else "ZCU",
                           "".join('<datafield tag="020" ind1=" " ind2=" "><subfield code="a">%s</subfield></datafield>' % x
                                   for x in LOCDB[i][0])) for i in _lwin(query, ids, start, size))
    return _R('<?xml version="1.0"?><zs:searchRetrieveResponse xmlns:zs="http://www.loc.gov/zing/srw/"><zs:numberOfRecords>'
              '%d</zs:numberOfRecords><zs:records>%s</zs:records></zs:searchRetrieveResponse>' % (len(ids), body))


_ltmp = tempfile.mkdtemp(prefix="krcn-loc-")
LS.LOC.relocate(_ltmp, _ltmp)
eq("LoC: 20 s between requests by default (LOC_INTERVAL overrides), transport errors stop the run",
   (LS.LOC.interval == 20.0 or "LOC_INTERVAL" in os.environ, LS.LOC.transport_stops), (True, True))
LS.LOC.offline, LS.LOC.refresh_days, LS.LOC.budget, LS.LOC.interval = False, 0, 0, 3.0
LS.LOC.urlopen, LS.LOC.sleep, LS.LOC.now = fake_loc, fsleep, lambda: CLOCK[0]


def isbn13(prefix, n):
    s = "%s%0*d" % (prefix, 12 - len(prefix), n)
    return s + str((10 - sum((1 if k % 2 == 0 else 3) * int(c) for k, c in enumerate(s)) % 10) % 10)


LOCDB.update({str(1000 + k): ([isbn13("979885540", k)], True) for k in range(63)})
# 1. transient: page 1 at 100 fails twice, then succeeds unchanged (netlog 11:03-11:04 shape)
LRULE["fail"] = lambda q, start, size, seen: (start, size) == (1, 100) and seen <= 2
SLEEPS2.clear()
n, pages = LS.search_set("bath.isbn=979885540*")
eq("rung 1: two diagnostic-61 retries 10 s apart, then the page", (n, LS.LOC.distinct(pages), SLEEPS2.count(10)), (63, 63, 2))
# 2. page-size dependent: at 100 it never works, at 50 it does (the 978168579* shape: 63 records)
LRULE["fail"] = lambda q, start, size, seen: size == 100
n, pages = LS.search_set("bath.isbn=9798855400*")         # the same 63 records, a new set
eq("rung 2: the range re-paged at 50 (1-50, 51-63)", (n, LS.LOC.distinct(pages)), (63, 63))
urls = json.load(open(LS.LOC.sets_path))["bath.isbn=9798855400*"]["urls"]
eq("... the manifest records the 50-size pages", [re.search(r"maximumRecords=(\d+)&startRecord=(\d+)", u).groups() for u in urls],
   [("50", "1"), ("50", "51")])
# 3. 50 fails for the second half too -> 25
LRULE["fail"] = lambda q, start, size, seen: size == 100 or (size == 50 and start == 51)
n, pages = LS.search_set("bath.isbn=97988554*")
eq("rung 2 again: 51-63 at 25", (n, LS.LOC.distinct(pages)), (63, 63))
# 4. start=1 fails at EVERY size on the stem -> rung 3: ten next-digit prefixes; a set record under
#    two prefixes is counted once (union, not sum)
LOCDB["9999"] = ([isbn13("9798855401", 1), isbn13("9798855402", 1)], True)
LRULE["fail"] = lambda q, start, size, seen: q == "bath.isbn=979885540*"
LS.LOC.degraded, LS.LOC.degraded_queries = None, []
_k4 = len(LCALLS)
n, pages = LS.LOC.search("bath.isbn=979885540*", force=True, pager=LS.pager)   # cached in case 1: refetch
eq("rung 3 requests: stem count 1 + 9 failed pages + 10 slice counts + 3 pages + 1 re-probe (was 27)",
   len(LCALLS) - _k4, 24)
eq("rung 3: ISBN slices, union == the stem's count (65 slice hits, 64 records)",
   (n, LS.LOC.distinct(pages), LS.LOC.degraded), (64, 64, None))
# 5. another diagnostic raises at once (no ladder, nothing cached)
LRULE["fail"], LRULE["code"] = (lambda q, start, size, seen: True), "10"
try:
    LS.search_set("bath.isbn=9798855*")
    eq("a non-61 diagnostic is not laddered", "no exception", "SourceIncomplete")
except SRU.SourceIncomplete as e:
    eq("a non-61 diagnostic is not laddered (no cached set: the stage fails)", "diagnostic 10" in str(e), True)
LRULE["code"] = "61"
# 6. subject channel exhausted, YEAR_INDEX unconfirmed: no slices -> no cached set -> fails;
#    with a previous complete set and a refresh -> degraded, the cached set kept whole
FLIP = [CLOCK[0] + 3600]                                   # paging below takes seconds, not an hour
LRULE["fail"] = lambda q, start, size, seen: q == 'dc.subject="webcomics"' and seen > 0 and CLOCK[0] > FLIP[0]
_YI, _NY = LS.YEAR_INDEX, LS.NO_YEAR
LS.YEAR_INDEX = None
n, pages = LS.search_set('dc.subject="webcomics"')          # before FLIP: succeeds, cached complete
CLOCK[0] += 29 * 86400
LS.LOC.refresh_days = 28
n2, pages2 = LS.search_set('dc.subject="webcomics"')
eq("degraded: the ladder exhausted on a stale set keeps the previous complete set",
   (n2 == n, bool(LS.LOC.degraded), 'dc.subject="webcomics"' in LS.LOC.degraded_queries), (True, True, True))
LS.LOC.refresh_days, LS.LOC.degraded, LS.LOC.degraded_queries = 0, None, []
LS.YEAR_INDEX, LS.NO_YEAR = _YI, _NY
LRULE["fail"] = lambda q, start, size, seen: False
# 7. the canary: exactly one DLC record
LOCDB["21800815"] = (["9781975319434"], True)
LS.canary()
eq("canary: 1 DLC record passes", True, True)
LOCDB["21800815"] = (["9781975319434"], False)
try:
    LS.canary()
    eq("canary: a non-DLC answer fails the stage", "no exception", "LocCanaryFailed")
except LS.LocCanaryFailed:
    eq("canary: a non-DLC answer fails the stage", True, True)
del LOCDB["21800815"]
try:
    LS.canary()
    eq("canary: zero records fails the stage", "no exception", "LocCanaryFailed")
except LS.LocCanaryFailed:
    eq("canary: zero records fails the stage", True, True)
eq("slices of an ISBN stem: its ten next-digit prefixes", LS.slices("bath.isbn=97988554*"),
   ["bath.isbn=97988554%d*" % d for d in range(10)])
eq("the §4 stems and subject channels", (len(LS.STEMS), len(LS.SUBJECTS)), (14, 10))
eq("LoC: page 100, >= 3 s, sizes 100/50/25", (LS.LOC.page, LS.LOC.interval >= 3.0, LS.SIZES), (100, True, (100, 50, 25)))

# ---- Task 8 deviation: live 2026-09-27, 97988554* paged 542 distinct of 562 with every page full ----
LOCDB.update({str(3000 + k): ([isbn13("979885549", k)], True) for k in range(80)})     # the stem: 144 records
# a short page (fewer records than its range) is a failed page: retried, then re-paged smaller
LRULE["short"] = lambda q, st, sz: q == "bath.isbn=979885549*" and sz == 100
n, pages = LS.search_set("bath.isbn=979885549*")
urls = json.load(open(LS.LOC.sets_path))["bath.isbn=979885549*"]["urls"]
eq("short page: laddered like diagnostic 61 (re-paged at 50)",
   (n, LS.LOC.distinct(pages), [re.search(r"maximumRecords=(\d+)", u).group(1) for u in urls]), (80, 80, ["50", "50"]))
LRULE.pop("short")
# ---- controller ruling 2026-09-27: duplicate positions (one record at two positions of a set) ----
def lmask(ids, *pos):
    """Positions pos show their predecessor instead: a duplicate that masks a record."""
    out = list(ids)
    for p in pos:
        out[p] = out[p - 1]
    return out


def ldups():
    return json.load(open(os.path.join(_ltmp, "loc-dups.json")))


# A. a genuine duplicate position (81 positions, 80 records); the read at 50 adds nothing: complete
LRULE["seq"] = lambda q, ids, sz: ids[:50] + [ids[10]] + ids[50:] if q == "bath.isbn=9798855491*" else ids
LOCDB.update({str(3100 + k): ([isbn13("9798855491", k)], True) for k in range(80)})
n, pages = LS.search_set("bath.isbn=9798855491*")
man = json.load(open(LS.LOC.sets_path))["bath.isbn=9798855491*"]
eq("duplicate position confirmed by a second read at 50: complete, cached with distinct < n",
   (n, LS.LOC.distinct(pages), man["distinct"], sorted({re.search(r"maximumRecords=(\d+)", u).group(1) for u in man["urls"]})),
   (81, 80, 80, ["100", "50"]))
eq("... duplicate positions reported (count + 001s)",
   {k: ldups()["bath.isbn=9798855491*"][k] for k in ("positions", "dup_ids")}, {"positions": 1, "dup_ids": ["3110"]})
k = len(LCALLS)
eq("... served whole from the cache afterwards", (LS.search_set("bath.isbn=9798855491*")[0], len(LCALLS) - k), (81, 0))
# B. at 100 a duplicate masks record 3160; the read at 50 reveals it -> union, third read at 25 adds nothing
LRULE["seq"] = (lambda q, ids, sz: (lambda base: lmask(base, 61) if sz == 100 else base)(ids[:50] + [ids[10]] + ids[50:])
                if q == "bath.isbn=9798855491*" else ids)
n, pages = LS.search_set("bath.isbn=9798855491*", force=True)
eq("masked record: revealed at 50, unioned, the third read at 25 confirms",
   (n, LS.LOC.distinct(pages), [r[0] for r in ldups()["bath.isbn=9798855491*"]["reads"]], LS.LOC.degraded),
   (81, 80, [100, 50, 25], None))
# C. every read finds a record the earlier ones lacked: incomplete (no slices -- not a failed page)
LOCDB.update({str(3200 + k): ([isbn13("9798855492", k)], True) for k in range(80)})
LRULE["seq"] = lambda q, ids, sz: lmask(ids, 60, 70) if sz == 100 else lmask(ids, 70) if sz == 50 else ids
k = len(LCALLS)
try:
    LS.search_set("bath.isbn=9798855492*")
    eq("still growing at 25: incomplete, the stage fails with no cached set", "no exception", "SourceIncomplete")
except SRU.SourceIncomplete as e:
    eq("still growing at 25: incomplete, the stage fails with no cached set",
       ("LocIncomplete" in str(e), any("9798855492" in u and re.search(r"isbn%3D9798855492\d", u) for u in LCALLS[k:])),
       (True, False))
n0 = json.load(open(LS.LOC.sets_path))['dc.subject="webcomics"']["n"]
n, pages = LS.LOC.search('dc.subject="webcomics"', force=True, pager=LS.pager)
eq("still growing on a cached subject set: degraded, the cached set kept",
   (n, bool(LS.LOC.degraded), 'dc.subject="webcomics"' in LS.LOC.degraded_queries), (n0, True, True))
LRULE.pop("seq")
LS.LOC.degraded, LS.LOC.degraded_queries = None, []
# enumerate_loc: build/loc-report.json per channel -- announced, distinct, DLC share, duplicates
LOCDB["21800815"] = (["9781975319434"], True)
_ch, _rp = LS.CHANNELS, LS.REPORT
LS.CHANNELS, LS.REPORT = [("isbn 9798855491", "bath.isbn=9798855491*")], os.path.join(_ltmp, "loc-report.json")
recs, rep = LS.enumerate_loc(verbose=False)
c = json.load(open(LS.REPORT))["channels"]["isbn 9798855491"]
eq("loc-report.json: announced, distinct, dlc, share, duplicate positions + 001s",
   (c["records"], c["distinct"], c["dlc"], c["dlc_share"], c["duplicates"]["bath.isbn=9798855491*"]["positions"],
    c["duplicates"]["bath.isbn=9798855491*"]["dup_ids"], len(recs)), (81, 80, 80, 1.0, 1, ["3110", "3159"], 80))
# (served from case B's cached set: 3110 is the genuine duplicate, 3159 the one that masked 3160 at 100)
LS.CHANNELS, LS.REPORT = _ch, _rp
del LOCDB["21800815"]
for k in range(80):
    del LOCDB[str(3100 + k)], LOCDB[str(3200 + k)]
for k in range(80):
    del LOCDB[str(3000 + k)]

# ---- Task 8 review fixes ----------------------------------------------------------------------------
LOCDB.update({str(4000 + k): ([isbn13("97988556", k)], True) for k in range(120)})
# 1. the set changes during paging (a record lands after page 1): incomplete, not laddered, not stored
LRULE["seq"] = lambda q, ids, sz: ids + ["4999"] if q == "bath.isbn=97988556*" and LSEEN.get((q, 1, 100), 0) else ids
LOCDB["4999"] = ([isbn13("97988557", 1)], True)
k = len(LCALLS)
try:
    LS.search_set("bath.isbn=97988556*")
    eq("a set that changes during paging fails (cold)", "no exception", "SourceIncomplete")
except SRU.SourceIncomplete as e:
    eq("a set that changes during paging fails (cold): LocIncomplete, 3 requests, no manifest entry",
       ("changed during paging" in str(e), len(LCALLS) - k, "bath.isbn=97988556*" in json.load(open(LS.LOC.sets_path))),
       (True, 3, False))
LRULE.pop("seq")
# 3. transport errors: the first is retried, the second anywhere in the run is the sticky stop
LS.LOC.refusals = 0
LRULE["drop"] = lambda q, st, sz: q == "bath.isbn=97988556*" and st == 101 and not LRULE.setdefault("dropped", 0) \
    and LRULE.update(dropped=1) is None
j = len(SLEEPS2)
n, pages = LS.search_set("bath.isbn=97988556*")
eq("one dropped connection: retried after 30 s, the set completes",
   (n, LS.LOC.distinct(pages), LS.LOC.refusals, 30 in SLEEPS2[j:]), (120, 120, 1, True))
LRULE["drop"] = lambda q, st, sz: True
k = len(LCALLS)
try:
    LS.search_set("bath.isbn=97988556*", force=True)
    raised = False
except SRU.SourceIncomplete:
    raised = True
eq("a second transport error: the stop (SourceThrottled after 1 request), degraded on the cached set",
   (raised, bool(LS.LOC.degraded) and "SourceThrottled" in LS.LOC.degraded, len(LCALLS) - k), (False, True, 1))
LS.LOC.degraded, LS.LOC.degraded_queries = None, []
try:
    LS.LOC.fetch(LS.LOC.url_for("bath.isbn=97988556*", 1, 1))
    eq("... and the stop is sticky", "no exception", "SourceThrottled")
except SRU.SourceThrottled:
    eq("... and the stop is sticky (no request sent)", len(LCALLS) - k, 1)
# 4. the canary: gateway down with a cached canary -> LocCanaryFailed, never the cached copy
LS.LOC.refusals = 0
LRULE.pop("drop"), LRULE.pop("dropped")
LOCDB["21800815"] = (["9781975319434"], True)
LS.canary()
LRULE["drop"] = lambda q, st, sz: True
try:
    LS.canary()
    eq("canary: cached copy + failing gateway fails the stage", "no exception", "LocCanaryFailed")
except LS.LocCanaryFailed as e:
    eq("canary: cached copy + failing gateway fails the stage (LocCanaryFailed)", "RemoteDisconnected" in str(e)
       or "SourceThrottled" in str(e), True)
LRULE.pop("drop")
LS.LOC.refusals = 0
del LOCDB["21800815"]
# 4. duplicate info is replaced as a family when the set is stored: no stale slice entry survives
d = ldups()
d["bath.isbn=979885569*"] = {"positions": 9, "dup_ids": ["x"]}           # a stale slice of the stem
SRU._store(os.path.join(_ltmp, "loc-dups.json"), json.dumps(d))
LS.search_set("bath.isbn=97988556*", force=True)
eq("stored stem: its stale slice entries are cleared", "bath.isbn=979885569*" in ldups(), False)
# 4. the generic sources keep the old manifest: no 'distinct' key, transport_stops off
eq("generic / BnF manifest: no 'distinct' key", [k for k, e in json.load(open(T.sets_path)).items() if "distinct" in e], [])
eq("BnF: transport errors keep the generic rule", (BS.BNF.transport_stops, BS.BNF.accept), (False, None))
for k in range(120):
    del LOCDB[str(4000 + k)]
del LOCDB["4999"]

# ---- Task 8 re-review: a shrinking set answers diagnostic 61 past its end; a malformed canary ----
LOCDB.update({str(5000 + k): ([isbn13("97988558", k)], True) for k in range(101)})
LRULE["seq"] = lambda q, ids, sz: ids[:-1] if q == "bath.isbn=97988558*" and LSEEN.get((q, 1, 100), 0) else ids
k = len(LCALLS)
try:
    LS.search_set("bath.isbn=97988558*")
    eq("a set shrinking 101 -> 100 after page 1 is refused", "no exception", "SourceIncomplete")
except SRU.SourceIncomplete as e:
    eq("a set shrinking 101 -> 100 after page 1: diagnostic 61 with 100 -> LocIncomplete in <= 3 requests",
       ("changed during paging: 101 announced, page says 100" in str(e), len(LCALLS) - k <= 3), (True, True))
LRULE.pop("seq")
for k in range(101):
    del LOCDB[str(5000 + k)]
LRULE["raw"] = {LS.CANARY: '<?xml version="1.0"?><zs:searchRetrieveResponse xmlns:zs="http://www.loc.gov/zing/srw/">'
                           '<zs:numberOfRecords>1</zs:numberOfRecords><zs:records><record'}
try:
    LS.canary()
    eq("canary: a malformed body fails the stage", "no exception", "LocCanaryFailed")
except LS.LocCanaryFailed as e:
    eq("canary: a malformed body fails the stage (LocCanaryFailed)", "malformed" in str(e), True)
LRULE.pop("raw")

# ---- Task 9: DNB KR/CN origin, select(in_scope=) --------------------------------------------------------
def orec(*fields):
    return drec("1", *fields)


eq("041$h kor: explicit", M.krcn_origin(orec(("041", [("a", "ger"), ("h", "kor")]))), ("kor", True))
eq("041$h chi: explicit", M.krcn_origin(orec(("041", [("a", "ger"), ("h", "chi")]))), ("chi", True))
eq("041$h jpn (a relay translation): out", M.krcn_origin(orec(("041", [("a", "ger"), ("h", "jpn")]))), (None, False))
eq("no 041, 'aus dem Koreanischen': explicit",
   M.krcn_origin(orec(("245", [("a", "X"), ("c", "Text: A ; aus dem Koreanischen von Y")]))), ("kor", True))
eq("no 041, 'aus dem Chinesischen': explicit",
   M.krcn_origin(orec(("245", [("a", "X"), ("c", "aus dem Chinesischen von Z")]))), ("chi", True))
eq("no 041, keyword Manhwa only: kor, NOT explicit (§9.2)", M.krcn_origin(orec(("653", [("a", "Manhwa")]))), ("kor", False))
eq("no 041, keyword Manhua only: chi, not explicit", M.krcn_origin(orec(("653", [("a", "Manhua")]))), ("chi", False))
eq("nothing said: out of the KR/CN round", M.krcn_origin(orec(("245", [("a", "X")]))), (None, False))
# DNB 96968777X Hekigan-Roku (live spo=chi slice, 2026-09-27): 041 $a ger $h chi $h jpn -- 17 such
# dual-origin records made imprint-split fail; a record naming Japanese among its origins is the JP round's
DUAL = orec(("041", [("a", "ger"), ("h", "chi"), ("h", "jpn")]))
eq("041$h chi + jpn (dual origin): the JP round's, out of the KR/CN round", M.krcn_origin(DUAL), (None, False))
for r_ in (orec(("041", [("a", "ger"), ("h", "kor")])), orec(("245", [("a", "X"), ("c", "aus dem Koreanischen von Y")])),
           orec(("653", [("a", "Webtoon")])), orec(("041", [("a", "ger"), ("h", "jpn")])), orec(("245", [("a", "X")])),
           DUAL, orec(("041", [("a", "ger"), ("h", "jpn"), ("h", "kor")]))):
    eq("never in scope for BOTH rounds", M.origin_in_scope(r_) and M.krcn_in_scope(r_), False)
kr = {r["cf"]["001"]: r for r in (dvol("1310000001", "1", "9783753935898", "1210000000", origin=("h", "kor")),
                                  dvol("1310000002", "1", "9783753935874", "1220000000"))}
kept_default, _ = B.select(kr)
kept_krcn, _ = B.select(kr, in_scope=M.krcn_in_scope)
eq("select() default = the JP predicate; in_scope= the KR/CN one",
   ([v["idn"] for v in kept_default], [v["idn"] for v in kept_krcn]), (["1310000002"], ["1310000001"]))
import dnb_enumerate as E
eq("KR/CN channels: spo=kor / spo=chi print, jhr-sliced from 2015 (P20)",
   [(c[0], c[1], c[2], c[3]) for c in E.KRCN_CHANNELS],
   [("print_kor", "spo=kor and bbg=A*", 2015, (2000, 2005, 2010)), ("print_chi", "spo=chi and bbg=A*", 2015, (2000, 2005, 2010))])

# ---- Task 10: lines per source ---------------------------------------------------------------------------
import krcn_lines as KL

# DNB: two Korean volumes of one set + a Chinese light novel
dk = {r["cf"]["001"]: r for r in (
    dvol("1400000001", "1", "9783753900001", "1390000000", title="Raeliana", origin=("h", "kor")),
    dvol("1400000002", "2", "9783753900018", "1390000000", title="Raeliana", origin=("h", "kor")),
    drec("1400000003", ("041", [("a", "ger"), ("h", "chi")]), ("926", [("a", "FYS")]),
         ("245", [("a", "Grandmaster of Demonic Cultivation"), ("n", "1")]), ("264", [("b", "Bramble")]),
         ("020", [("a", "9783753900025")])))}
lines, lost, st = KL.dnb_lines(dk, {})
by = {l["key"]: l for l in lines}
eq("DNB: a Korean set -> one manhwa line keyed by its parent IDN, explicit, comic",
   {k: (l["medium"], l["explicit"], l["comic"], len(l["vols"])) for k, l in by.items() if l["origin"] == "kor"},
   {"dnb:1390000000": ("manhwa", True, True, 2)})
eq("DNB: a Chinese light novel -> a novel line (not comic)",
   [(l["medium"], l["comic"]) for l in lines if l["origin"] == "chi"], [("novel", False)])
eq("DNB members are dnb:<IDN>", sorted(by["dnb:1390000000"]["members"]), ["dnb:1400000001", "dnb:1400000002"])
eq("DNB stats: no review lines here", st["review"], {})

# LoC: the Solo Leveling set record (Task 6 SL) + a single-volume DLC twin of its v. 1 + Mystery Science
# Detectives books 3 and 4 + records that must drop
SL1 = lrec("01000cam a2200000 i 4500", "210302s2021    nyu           000 1 eng  ", ("010", [("a", "  2021011111")]),
           ("020", [("a", "9781975319434")]), DLC, ("041", [("a", "eng"), ("h", "kor")]), ("082", [("a", "741.5")]),
           ("245", [("a", "Solo leveling."), ("n", "1")]), ("300", [("a", "320 pages")]), VOL338, cid="twin1")
MS4 = lrec("04031cam a2200625 i 4500", "250709s2026    mnua   c 6    000 1 eng  ", ("010", [("a", "  2025024337")]),
           ("020", [("a", "9798765627556"), ("q", "paperback")]), DLC, ("041", [("a", "eng"), ("h", "kor")]),
           ("082", [("a", "741.5/973")]), ("245", [("a", "The case of the carnival monster /")]),
           ("300", [("a", "128 pages")]), VOL338, ("490", [("a", "Mystery Science Detectives ;"), ("v", "book 4")]),
           cid="in00024277995")
NON = dict(KO, cf={"001": "zcu1", "008": KO["cf"]["008"].replace(" kor d", " eng d")},
           df=KO["df"] + [("010", " ", " ", [("a", "  2026377465")])])          # an LCCN, but 040 $a ZCU
lines, lost, st = KL.loc_lines({r["cf"]["001"]: r for r in (SL, SL1, MS, MS4, SE, ISE, NON)})
by = {l["key"]: l for l in lines}
eq("LoC: a set record IS a line, keyed loc:<its LCCN>", "loc:2020950228" in by, True)
sl = by["loc:2020950228"]
eq("... its 5 volumes; v.1 also has the single twin as a member", (len(sl["vols"]),
   sorted(next(v for v in sl["vols"] if v["number"] == "1")["members"])), (5, ["loc:2020950228#1", "loc:2021011111"]))
eq("... v.1 is dated by the SINGLE record, never by the set", next(v for v in sl["vols"] if v["number"] == "1")["date"],
   ("2021", "year", "published"))
eq("... v.2 (set record only) is undated", next(v for v in sl["vols"] if v["number"] == "2")["date"], None)
eq("single-volume records cluster by series + publisher family, keyed by the lowest LCCN",
   [(k, sorted(v["number"] for v in l["vols"])) for k, l in by.items() if "Mystery" in (l["name"] or "")],
   [("loc:2025007302", ["3", "4"])])
eq("the Ize ECIP set: medium unresolved, origin by imprint (not explicit)",
   (by["loc:2024941070"]["medium"], by["loc:2024941070"]["explicit"]), (None, False))
eq("dropped: the ebook twin (not print) and the non-DLC record, counted",
   (st["dropped"].get("not_print"), st["dropped"].get("non_dlc")), (1, 1))
eq("loc_member rows carry 040 $a, level, date type, set flag",
   sorted((row[0], row[1], row[2], row[5]) for row in sl["loc"])[:2],
   [("2020950228", "1", "DLC", 1), ("2020950228", "14", "DLC", 1)])

# controller ruling 1: is_dlc() before anything else -- a non-DLC record's 010 is never read, and
# no_lccn counts DLC records only
_lccn_seen, _lccn_real = [], LM.lccn
LM.lccn = lambda r: (_lccn_seen.append(r["cf"]["001"]), _lccn_real(r))[1]
NON2 = dict(KO, cf={"001": "zcu2", "008": KO["cf"]["008"]})                        # non-DLC, no 010 at all
NOLC = lrec("01000cam a2200000 i 4500", "210302s2021    nyu           000 1 eng  ", DLC, cid="dlc-no-010")
try:
    _, _, st = KL.loc_lines({r["cf"]["001"]: r for r in (NON, NON2, NOLC, SL)})
finally:
    LM.lccn = _lccn_real
eq("ruling 1: LM.lccn is never called on a non-DLC record", sorted(x for x in _lccn_seen if x.startswith("zcu")), [])
eq("ruling 1: both non-DLC records count non_dlc (with or without an 010); no_lccn only the DLC one",
   (st["dropped"].get("non_dlc"), st["dropped"].get("no_lccn")), (2, 1))

# controller ruling 2: 245 $b keeps a sequel apart -- the Ragnarok set (synthesised shape, its own ISBNs)
# must not share Solo Leveling's signature, name or linker titles
RAGS = lrec("02000cam a2200400 i 4500", "240801m20249999nyua     6    000 1 eng  ", ("010", [("a", "  2024950001")]),
            DLC, ("041", [("a", "eng"), ("h", "kor")]),
            ("020", [("a", isbn13("979840099", 1)), ("q", "v. 1"), ("q", "trade paperback")]),
            ("020", [("a", isbn13("979840099", 2)), ("q", "v. 2"), ("q", "trade paperback")]),
            ("245", [("a", "Solo leveling :"), ("b", "Ragnarok /"), ("c", "Daul ; original story, Chugong.")]),
            ("264", [("b", "Ize Press,"), ("c", "2024-")]), VOL338, cid="rag")
# a single Solo Leveling v. 16 (no set ISBN) and a single Ragnarok v. 3 ($b before $n)
SL16 = lrec("01000cam a2200000 i 4500", "250302s2025    nyu           000 1 eng  ", ("010", [("a", "  2025011116")]),
            ("020", [("a", isbn13("979840099", 16))]), DLC, ("041", [("a", "eng"), ("h", "kor")]),
            ("082", [("a", "741.5")]), ("245", [("a", "Solo leveling."), ("n", "16")]),
            ("264", [("b", "Yen Press/Ize Press,")]), VOL338, cid="sl16")
RAG3 = lrec("01000cam a2200000 i 4500", "250302s2025    nyu           000 1 eng  ", ("010", [("a", "  2025011103")]),
            ("020", [("a", isbn13("979840099", 3))]), DLC, ("041", [("a", "eng"), ("h", "kor")]),
            ("245", [("a", "Solo leveling :"), ("b", "Ragnarok."), ("n", "3")]),
            ("264", [("b", "Ize Press,")]), VOL338, cid="rag3")
lines, lost, st = KL.loc_lines({r["cf"]["001"]: r for r in (SL, RAGS, SL16, RAG3)})
by = {l["key"]: l for l in lines}
eq("ruling 2: two lines -- Solo Leveling and Ragnarok", sorted(by), ["loc:2020950228", "loc:2024950001"])
eq("ruling 2: the Ragnarok line is named by its full title", by["loc:2024950001"]["name"], "Solo leveling : Ragnarok")
eq("ruling 2: its linker titles never reduce to 'Solo leveling'",
   [t for t in by["loc:2024950001"]["titles"] if L.fold(t, False) == "sololeveling"], [])
eq("ruling 2: the non-twin SL v. 16 single joins the Solo Leveling set by signature (unique set there)",
   sorted((v["number"] for v in by["loc:2020950228"]["vols"]), key=int), ["1", "2", "3", "14", "15", "16"])
eq("ruling 2: the Ragnarok v. 3 single ($b before $n) joins Ragnarok, not Solo Leveling",
   sorted(v["number"] for v in by["loc:2024950001"]["vols"]), ["1", "2", "3"])

# controller ruling 4: a colliding 6-character publisher family never merges different titles
PA = lrec("01000cam a2200000 i 4500", "250302s2025    nyu           000 1 eng  ", ("010", [("a", "  2025020001")]),
          ("020", [("a", isbn13("97817", 20001))]), DLC, ("041", [("a", "eng"), ("h", "kor")]), ("082", [("a", "741.5")]),
          ("245", [("a", "Moon river."), ("n", "1")]), ("264", [("b", "Cambria Press,")]), VOL338, cid="pa")
PB = lrec("01000cam a2200000 i 4500", "250302s2025    nyu           000 1 eng  ", ("010", [("a", "  2025020002")]),
          ("020", [("a", isbn13("97817", 20002))]), DLC, ("041", [("a", "eng"), ("h", "kor")]), ("082", [("a", "741.5")]),
          ("245", [("a", "Sun valley."), ("n", "2")]), ("264", [("b", "Cambridge University Press,")]), VOL338, cid="pb")
eq("ruling 4: Cambria / Cambridge share the family 'cambri'",
   (LM.pubfam("Cambria Press"), LM.pubfam("Cambridge University Press")), ("cambri", "cambri"))
lines, _, _ = KL.loc_lines({"pa": PA, "pb": PB})
eq("ruling 4: ... but two different titles stay two lines", sorted(l["name"] for l in lines), ["Moon river", "Sun valley"])
eq("ruling 4 (BnF): Saphira / Saphir Éditions share the family 'saphir'",
   (U.pubfam("Saphira"), U.pubfam("Saphir Éditions")), ("saphir", "saphir"))
bl = KL.bnf_lines({U.ark(r): r for r in (
    brec(("010", [("a", isbn13("97823", 1))]), ("101", [("a", "fre"), ("c", "kor")]), ("200", [("a", "Chiro"), ("h", "1")]),
         ("210", [("c", "Saphira"), ("d", "2006")]), cf3="http://catalogue.bnf.fr/ark:/12148/cb40000001x"),
    brec(("010", [("a", isbn13("97823", 2))]), ("101", [("a", "fre"), ("c", "kor")]), ("200", [("a", "Veritas"), ("h", "2")]),
         ("210", [("c", "Saphir Éditions"), ("d", "2006")]), cf3="http://catalogue.bnf.fr/ark:/12148/cb40000002x"))})[0]
eq("ruling 4 (BnF): ... but two different titles stay two lines", sorted(l["name"] for l in bl), ["Chiro", "Veritas"])
eq("BnF family: an 'Éd.' word is dropped ('Éd. Ki-oon' = 'Ki-oon', Warlord), 'Pika éd.' = 'pika'",
   (U.pubfam("Éd. Ki-Oon"), U.pubfam("Ki-oon"), U.pubfam("Pika éd.")), ("kion", "kion", "pika"))

# controller ruling 5: titles are keyed per field -- an English 245 and a Hangul 880 each give their own key;
# a mixed Latin + Hangul field is one native title
HB = lrec("01000cam a2200000 i 4500", "250302s2025    nyu           000 1 eng  ", ("010", [("a", "  2025030001")]),
          ("020", [("a", isbn13("97817", 30001))]), DLC, ("041", [("a", "eng"), ("h", "kor")]), ("082", [("a", "741.5")]),
          ("245", [("a", "Tower of god."), ("n", "1")]), ("246", [("a", "Tower of God 신의 탑")]),
          ("880", [("6", "245-01/$1"), ("a", "신의 탑 /")]), VOL338, cid="hb")
hb = KL.loc_lines({"hb": HB})[0][0]
eq("ruling 5: the English title keys everywhere, the Hangul and the mixed field are native titles",
   (hb["titles"], hb["native"]), (["Tower of god. 1", "Tower of god"], ["신의 탑", "Tower of God 신의 탑"]))
eq("ruling 5: one key per field (the Hangul 880 keys on its own, not only inside the mixed field)",
   {L.fold(t, False) for t in hb["native"]} >= {"신의탑"} and "towerofgod" in L.keys(hb["titles"]), True)
eq("script_title: Hangul / Hanzi yes, Latin no", (KL.script_title("신의 탑"), KL.script_title("三体"),
                                               KL.script_title("Tower of god")), (True, True, False))

# controller ruling 3 (KR/CN medium mapping; dnb_marc.classify untouched), synthetic shapes of the real
# DNB records named in the ruling (2026-09-27 cache): Altraverse web-NOVEL editions classed 741.5 / XAM
def kv(idn, num, parent, title, pages, *extra, ddc="741.5"):
    return drec(idn, ("041", [("a", "ger"), ("h", "kor")]), ("082", [("a", ddc)]), ("926", [("a", "XAMG")]),
                ("245", [("a", title), ("n", num)]), ("264", [("b", "Altraverse GmbH")]),
                ("020", [("a", isbn13("97837539", int(idn[-5:-1])))]), ("300", [("a", "%d Seiten" % pages)]),
                ("773", [("w", "(DE-101)" + parent)]), *extra)


AUT = ("100", [("a", "Chu gong"), ("4", "aut")])
dp = {p["cf"]["001"]: p for p in (
    drec("1235188582", ("245", [("a", "Solo leveling"), ("c", "Chugong")]), parent=True),
    drec("1306452414", ("245", [("a", "Solo leveling"), ("c", "Story: Chugong ; Artwork: Peperon")]),
         ("700", [("a", "Peperon"), ("4", "ill")]), parent=True),
    drec("1398947172", ("245", [("a", "Penelope - das Böse ist dem Tod geweiht"), ("b", "Roman")]), parent=True),
    drec("1380593565", ("245", [("a", "The Horizon")]), parent=True),
    drec("1326442465", ("245", [("a", "Ennead")]), ("100", [("a", "Mojito"), ("4", "aut"), ("4", "art")]), parent=True))}
dr = {r["cf"]["001"]: r for r in (
    # dnb:1235188582 -- Solo Leveling novel, vols 1-7 'K' / XAMG, vol 8 'Solo Leveling Roman 08' 741.5
    kv("1219161251", "1", "1235188582", "Solo leveling", 382, AUT, ddc="K"),
    kv("1226876781", "2", "1235188582", "Solo leveling", 360, AUT, ddc="K"),
    kv("1270356976", "8", "1235188582", "Solo Leveling Roman 08", 400, AUT),
    # dnb:1306452414 -- the paperback novel run: Roman in a member's 490, an illustrator (Peperon) credited
    kv("1293527131", "1", "1306452414", "Solo leveling", 424, AUT, ("700", [("a", "Peperon"), ("4", "ill")]), ddc="K"),
    kv("1305974204", "2", "1306452414", "Solo leveling", 399, AUT, ("490", [("a", "Solo Leveling. Roman"), ("v", "2")]), ddc="K"),
    # dnb:1398947172 -- Penelope vols 1-2: writer only, 414 / 396 pages; the SET record's 245 $b says 'Roman'
    kv("1368765815", "1", "1398947172", "Penelope - das Böse ist dem Tod geweiht", 414,
       ("100", [("a", "Gwon, Gyeo eul"), ("4", "aut")]), ddc="K"),
    kv("1380091810", "2", "1398947172", "Penelope - das Böse ist dem Tod geweiht", 396,
       ("100", [("a", "Gwon, Gyeo eul"), ("4", "aut")]), ddc="K"),
    # dnb:1402480407 -- Penelope Roman 03 / 04 (no set record fetched: keyed by the lowest member IDN)
    drec("1402480407", ("041", [("a", "ger"), ("h", "kor")]), ("082", [("a", "741.5")]),
         ("245", [("a", "Penelope - Das Böse ist dem Tod geweiht Roman 03")]), ("264", [("b", "Altraverse GmbH")]),
         ("490", [("a", "Penelope - Das Böse ist dem Tod geweiht. Roman"), ("v", "3")]),
         ("020", [("a", isbn13("97837539", 2407))]), ("300", [("a", "432 Seiten")])),
    drec("1412476909", ("041", [("a", "ger"), ("h", "kor")]), ("082", [("a", "741.5")]),
         ("245", [("a", "Penelope - Das Böse ist dem Tod geweiht Roman 04")]), ("264", [("b", "Altraverse GmbH")]),
         ("490", [("a", "Penelope - Das Böse ist dem Tod geweiht. Roman"), ("v", "4")]),
         ("020", [("a", isbn13("97837539", 6909))]), ("300", [("a", "300 Seiten")])),
    # dnb:1412477255 -- Solo Leveling: Ragnarok Roman 01
    drec("1412477255", ("041", [("a", "ger"), ("h", "kor")]), ("082", [("a", "741.5")]),
         ("245", [("a", "Solo Leveling: Ragnarok Roman 01")]), ("264", [("b", "Altraverse GmbH")]),
         ("490", [("a", "Solo Leveling: Ragnarok. Roman"), ("v", "1")]), ("100", [("a", "Daul"), ("4", "aut")]),
         ("020", [("a", isbn13("97837539", 7255))]), ("300", [("a", "400 Seiten")])),
    # dnb:1395619670 -- Under the Oak Tree: the Roman and the Webtoon under one series statement (C Lines)
    *[drec(i, ("041", [("a", "ger"), ("h", "kor")]), ("082", [("a", "741.5")]), ("245", [("a", t)]),
           ("264", [("b", "C Lines")]), ("490", [("a", "Under the Oak Tree"), ("v", n)]),
           ("020", [("a", isbn13("97837539", int(i[-5:-1])))]), ("300", [("a", "%d Seiten" % p)]), *x)
      for i, t, n, p, x in (("1395619670", "Under the Oak Tree (Roman) 2", "2", 432, ()),
                            ("139562769X", "Under the Oak Tree (Roman) 1", "1", 432, ()),
                            ("1395622647", "Under the Oak Tree (Webtoon) 1", "1", 256, (("700", [("a", "P"), ("4", "ill")]),)),
                            ("1395628068", "Under the Oak Tree (Webtoon) 2", "2", 256, (("700", [("a", "P"), ("4", "ill")]),)))],
    # dnb:1380593565 -- The Horizon (JH, Manhwa Cult): writer only, 360 pages -> review, never auto-manhwa
    kv("1380593566", "1", "1380593565", "The Horizon", 360, ("100", [("a", "JH"), ("4", "aut")])),
    # controls: the same shape with an illustrator relator / a drawing role in 245 $c / < 320 pages / a
    # 'nach dem Roman' credit in 245 $c (a comic adaptation) stays manhwa
    kv("1500000001", "1", "1500000000", "Control ill", 360, ("700", [("a", "X"), ("4", "ill")])),
    drec("1500000011", ("041", [("a", "ger"), ("h", "kor")]), ("082", [("a", "741.5")]),
         ("245", [("a", "Control zeichn"), ("n", "1"), ("c", "Text: A ; Zeichnungen: B")]), ("264", [("b", "C Lines")]),
         ("020", [("a", isbn13("97837539", 11))]), ("300", [("a", "360 Seiten")]), ("773", [("w", "(DE-101)1500000010")])),
    kv("1500000021", "1", "1500000020", "Control short", 250),
    # dnb:1326442465 -- Ennead: writer-only volumes (324 pages), the 'art' credit sits on the set record only
    kv("1326442466", "1", "1326442465", "Ennead", 324, ("100", [("a", "Mojito"), ("4", "aut")])),
    drec("1500000031", ("041", [("a", "ger"), ("h", "kor")]), ("082", [("a", "741.5")]),
         ("245", [("a", "Control adaptation"), ("n", "1"), ("c", "Zeichnungen: B ; nach dem Roman von A")]),
         ("264", [("b", "C Lines")]), ("020", [("a", isbn13("97837539", 31))]), ("300", [("a", "360 Seiten")]),
         ("773", [("w", "(DE-101)1500000030")])))}
lines, lost, st = KL.dnb_lines(dr, dp)
by = {l["key"]: l for l in lines}
got = {k: (by[k]["medium"], by[k]["medium_why"], by[k]["medium_guess"], by[k]["comic"]) for k in sorted(by)}
eq("ruling 3: the real cases and the controls",
   got, {"dnb:1235188582": ("novel", None, None, False),        # (a) Roman on a member's 245 $a
         "dnb:1306452414": ("novel", None, None, False),        # (a) Roman in a member's 490, despite an illustrator
         "dnb:1326442465": ("manhwa", None, None, True),        # the illustrator credit on the set record counts
         "dnb:1380593565": (None, "writer_only", "manhwa", True),   # (b)
         "dnb:1395619670": (None, "duplicate_numbers", "novel", False),  # (c) before (a)
         "dnb:1398947172": ("novel", None, None, False),        # (a) Roman in the set record's 245 $b
         "dnb:1402480407": ("novel", None, None, False),        # (a) Roman in 245 $a / 490
         "dnb:1412477255": ("novel", None, None, False),        # (a)
         "dnb:1500000000": ("manhwa", None, None, True),        # an illustrator relator
         "dnb:1500000010": ("manhwa", None, None, True),        # a drawing role in 245 $c
         "dnb:1500000020": ("manhwa", None, None, True),        # writer only, but < 320 pages
         "dnb:1500000030": ("manhwa", None, None, True)})       # 'nach dem Roman' in 245 $c is not a Roman token
eq("ruling 3: review counted by reason", st["review"], {"duplicate_numbers": 1, "writer_only": 1})
eq("ruling 3: the duplicate numbers are in lost", sorted(m for m, f, k in lost if f == "dropped_duplicate_number"),
   ["dnb:139562769X", "dnb:1395628068"])
eq("dnb_marc.classify is unchanged: the Roman volume is still 'manga' to the JP round", M.classify(dr["1270356976"]), "manga")

# ruling 3c for BnF and LoC too: a number left over twice -> review
bdup = KL.bnf_lines({U.ark(r): r for r in (
    brec(("010", [("a", isbn13("97823", 11))]), ("101", [("a", "fre"), ("c", "kor")]), ("200", [("a", "Yureka"), ("h", "1")]),
         ("210", [("c", "Tokebi"), ("d", "2003")]), cf3="http://catalogue.bnf.fr/ark:/12148/cb39065080j"),
    brec(("010", [("a", isbn13("97823", 12))]), ("101", [("a", "fre"), ("c", "kor")]), ("200", [("a", "Yureka"), ("h", "1")]),
         ("210", [("c", "Tokebi"), ("d", "2009")]), cf3="http://catalogue.bnf.fr/ark:/12148/cb42168281g"))})
eq("BnF: a re-edition under a new ISBN, same number -> review 'duplicate_numbers', guess manhwa",
   [(l["medium"], l["medium_why"], l["medium_guess"]) for l in bdup[0]] + [bdup[2]["review"]],
   [(None, "duplicate_numbers", "manhwa"), {"duplicate_numbers": 1}])
LD1 = lrec("01000cam a2200000 i 4500", "250302s2025    nyu           000 1 eng  ", ("010", [("a", "  2025040001")]),
           ("020", [("a", isbn13("97817", 40001))]), DLC, ("041", [("a", "eng"), ("h", "kor")]), ("082", [("a", "741.5")]),
           ("245", [("a", "Lookism."), ("n", "1")]), VOL338, cid="ld1")
LD2 = dict(LD1, cf={"001": "ld2", "008": LD1["cf"]["008"]},
           df=[f if f[0] not in ("010", "020") else (f[0], " ", " ", [("a", "  2025040002" if f[0] == "010" else isbn13("97817", 40002))])
               for f in LD1["df"]])
ll = KL.loc_lines({"ld1": LD1, "ld2": LD2})
eq("LoC: two single records of one number (different ISBNs) -> review 'duplicate_numbers'",
   [(l["medium"], l["medium_why"], l["medium_guess"]) for l in ll[0]], [(None, "duplicate_numbers", "manhwa")])

# controller ruling 6: relays through English (BnF 101 $b eng, DNB 041 $h eng + kor) stay in scope
rl = KL.bnf_lines({U.ark(r): r for r in (
    brec(("010", [("a", isbn13("97823", 21))]), ("101", [("a", "fre"), ("b", "eng"), ("c", "kor")]),
         ("200", [("a", "Relayed"), ("h", "1")]), ("210", [("c", "Kbooks"), ("d", "2024")]),
         cf3="http://catalogue.bnf.fr/ark:/12148/cb40000021x"),)})[0]
eq("ruling 6: a French edition translated via English is a line", [(l["name"], l["medium"]) for l in rl], [("Relayed", "manhwa")])
dl = KL.dnb_lines({r["cf"]["001"]: r for r in (dvol("1600000001", "1", isbn13("97837539", 8001), "1600000000",
                                                     title="Via English", origin=("h", "eng")),)}, {})[0]
dl2 = KL.dnb_lines({r["cf"]["001"]: r for r in (drec("1600000011", ("041", [("a", "ger"), ("h", "eng"), ("h", "kor")]),
                                                     ("082", [("a", "741.5")]), ("245", [("a", "Via English"), ("n", "1")]),
                                                     ("020", [("a", isbn13("97837539", 8011))])),)}, {})[0]
eq("ruling 6: DNB 041 $h eng + kor stays in (only a jpn relay is out); $h eng alone names no KR/CN origin",
   ([(l["origin"], l["explicit"]) for l in dl2], dl), ([("kor", True)], []))

# BnF: The gamer 1 (Task 7 GAMER) + The gamer 2 + the 4-6 box + Omega (a set record) + Niumao (no 101 $c)
g2 = brec(("010", [("a", "978-2-38288-038-8")]), ("101", [("a", "fre"), ("c", "kor")]),
          ("200", [("a", "The gamer"), ("h", "2")]), ("214", [("c", "Kbooks"), ("d", "DL 2023")]),
          ("215", [("a", "1 vol. (230 p.)")]), ("461", [("t", "The gamer"), ("v", "2")]),
          cf3="http://catalogue.bnf.fr/ark:/12148/cb09999999z")
g2["df"] = [(t, i1, "0" if t == "214" else i2, s_) for t, i1, i2, s_ in g2["df"]]   # the publication statement (Task 7: ind2 0)
box["cf"]["003"] = "http://catalogue.bnf.fr/ark:/12148/cb47137369q"
box["df"].append(("101", " ", " ", [("a", "fre"), ("c", "kor")]))
omega["cf"]["003"] = "http://catalogue.bnf.fr/ark:/12148/cb39076808g"
lines, lost, st = KL.bnf_lines({U.ark(r): r for r in (g, g2, box, omega, niu)})
eq("BnF: one line, keyed by the numerically lowest ark (cb09999999z < cb47253773p)",
   [(l["key"], sorted(v["number"] for v in l["vols"]), l["medium"], l["explicit"]) for l in lines],
   [("bnf:ark:/12148/cb09999999z", ["1", "2"], "manhwa", True)])
eq("BnF drops: the box, the set record, the record without 101 $c",
   (st["dropped"].get("bundle"), st["dropped"].get("set_record"), st["dropped"].get("origin_out_of_scope")), (1, 1, 1))

# the Ize order (§7): 1. an existing line's ISBN, 2. a DNB/BnF line's title, 3. review
ize = [dict(key="loc:1", source="loc", medium=None, medium_why=None, origin="kor", name="Semantic error",
            vols=[{"isbns": ["9798400902628"]}]),
       dict(key="loc:2", source="loc", medium=None, medium_why=None, origin="kor", name="The Star Seekers",
            vols=[{"isbns": ["9798400900648"]}]),
       dict(key="loc:3", source="loc", medium=None, medium_why=None, origin="kor", name="Finding Camellia",
            vols=[{"isbns": ["9798400909999"]}]),
       dict(key="dnb:9", source="dnb", medium="manhwa", medium_why=None, origin="kor", name="The Star Seekers",
            titles=["The Star Seekers"], vols=[]),
       dict(key="dnb:8", source="dnb", medium=None, medium_why="writer_only", origin="kor", name="Finding Camellia",
            titles=["Finding Camellia"], vols=[])]
KL.resolve_media(ize, {"9798400902628": "manhwa"})
eq("Ize order: ISBN on an existing line, then a DE/FR title, else unresolved (review); a line in review is no source",
   [(l["key"], l["medium"], l.get("medium_via")) for l in ize[:3]],
   [("loc:1", "manhwa", "isbn"), ("loc:2", "manhwa", "title"), ("loc:3", None, None)])

# ---- Task 10 review fixes: keys from kept volumes, 225 without $v, 461 $0 heads, Ize title step, reasons ----
def fr(ark8, *fields, h=None, c="kor"):
    """A BnF volume record, ark cb<ark8>x; h: its series head's record number (461 $0)."""
    f = [("101", [("a", "fre")] + ([("c", c)] if c else []))] + list(fields)
    if h:
        f.append(("461", [("0", h), ("t", dict(fields).get("200", [("a", "")])[0][1])] +
                  ([("v", dict(dict(fields)["200"]).get("h"))] if dict(dict(fields)["200"]).get("h") else [])))
    return brec(*f, cf3="http://catalogue.bnf.fr/ark:/12148/cb%sx" % ark8)


# 1. the key is the lowest ark / LCCN among the KEPT volumes (FR Dr. Brain: its lowest ark was dropped)
drb = KL.bnf_lines({U.ark(r): r for r in (
    fr("47364934", ("010", [("a", isbn13("97823", 101))]), ("200", [("a", "Dr. Brain")]), ("225", [("a", "Dr. Brain"), ("v", "")]),
       ("210", [("c", "Kbooks"), ("d", "2021")])),
    fr("48631246", ("010", [("a", isbn13("97823", 102))]), ("200", [("a", "Dr. Brain"), ("h", "2")]),
       ("225", [("a", "Dr. Brain"), ("v", "2")]), ("210", [("c", "Kbooks"), ("d", "2022")])))})
eq("BnF key: the lowest ark among the KEPT volumes, never a dropped record's",
   ([(l["key"], [v["number"] for v in l["vols"]]) for l in drb[0]], drb[1]),
   ([("bnf:ark:/12148/cb48631246x", ["2"])],
    [("bnf:ark:/12148/cb47364934x", "dropped_unnumbered", "bnf:ark:/12148/cb48631246x")]))
LK1 = lrec("01000cam a2200000 i 4500", "250302s2025    nyu           000 1 eng  ", ("010", [("a", "  2025050001")]),
           ("020", [("a", isbn13("97817", 50001))]), DLC, ("041", [("a", "eng"), ("h", "kor")]), ("082", [("a", "741.5")]),
           ("245", [("a", "Omnibus of stars /")]), ("490", [("a", "Star saga ;"), ("v", "omnibus")]), VOL338, cid="lk1")
LK2 = lrec("01000cam a2200000 i 4500", "250302s2025    nyu           000 1 eng  ", ("010", [("a", "  2025050002")]),
           ("020", [("a", isbn13("97817", 50002))]), DLC, ("041", [("a", "eng"), ("h", "kor")]), ("082", [("a", "741.5")]),
           ("245", [("a", "The first star /")]), ("490", [("a", "Star saga ;"), ("v", "2")]), VOL338, cid="lk2")
lk = KL.loc_lines({"lk1": LK1, "lk2": LK2})
eq("LoC singles key: the lowest LCCN among the KEPT volumes",
   ([(l["key"], [v["number"] for v in l["vols"]]) for l in lk[0]], lk[1]),
   ([("loc:2025050002", ["2"])], [("loc:2025050001", "dropped_unnumbered", "loc:2025050002")]))

# 2. a bare 225 $a (no $v, no 461) is a collection, not a series: two one-shots stay two lines
pp = KL.bnf_lines({U.ark(r): r for r in (
    fr("43485033", ("010", [("a", isbn13("97823", 111))]), ("200", [("a", "Coup de foudre")]),
       ("225", [("a", "Petit Pierre et Ieiazel")]), ("210", [("c", "Ieiazel"), ("d", "2011")])),
    fr("43830362", ("010", [("a", isbn13("97823", 112))]), ("200", [("a", "Golden glove")]),
       ("225", [("a", "Petit Pierre et Ieiazel")]), ("210", [("c", "Ieiazel"), ("d", "2012")])))})
eq("225 $a without $v / 461: each one-shot is its own one-volume line (not one dropped group)",
   sorted((l["name"], [v["number"] for v in l["vols"]]) for l in pp[0]), [("Coup de foudre", ["1"]), ("Golden glove", ["1"])])
eq("225 $a WITH $v still names the series", U.series(brec(("225", [("a", "Dr. Brain"), ("v", "2")]))), "Dr. Brain")
eq("... and a bare 225 $a does not", U.series(brec(("225", [("a", "KBL")]))), None)

# 3. 461 $0: a volume with no 101 $c inherits its series head's origin; two heads never merge; a volume
# with no 461 $0 joins the one head of its signature
HEAD = brec(("101", [("a", "fre"), ("c", "kor")]), ("200", [("a", "Chonchu")]), ("210", [("c", "Tokebi"), ("d", "2003-")]),
            leader="     nam  22        450 ", cf3="http://catalogue.bnf.fr/ark:/12148/cb39026600x")
HEAD2 = brec(("101", [("a", "fre"), ("c", "kor")]), ("200", [("a", "Chonchu")]), ("210", [("c", "Tokebi"), ("d", "2007-")]),
             leader="     nam  22        450 ", cf3="http://catalogue.bnf.fr/ark:/12148/cb43300000x")
cs = [fr("39026622", ("010", [("a", isbn13("97823", 121))]), ("200", [("a", "Chonchu"), ("h", "1")]),
         ("210", [("c", "Tokebi"), ("d", "2003")]), h="39026600"),
      fr("39026700", ("010", [("a", isbn13("97823", 127))]), ("200", [("a", "Chonchu"), ("h", "7")]),
         ("210", [("c", "Tokebi"), ("d", "2004")]), h="39026600", c=None),                      # no 101 $c of its own
      fr("39026800", ("010", [("a", isbn13("97823", 128))]), ("200", [("a", "Chonchu"), ("h", "8")]),
         ("210", [("c", "Tokebi"), ("d", "2004")])),                                            # no 461 $0: joins
      fr("43300001", ("010", [("a", isbn13("97823", 131))]), ("200", [("a", "Chonchu"), ("h", "1")]),
         ("210", [("c", "Tokebi"), ("d", "2007")]), h="43300000"),                               # another head
      fr("43300002", ("010", [("a", isbn13("97823", 132))]), ("200", [("a", "Orphan"), ("h", "1")]),
         ("210", [("c", "Tokebi"), ("d", "2007")]), h="99999999", c=None)]                      # head unknown
shape = lambda res: sorted((l["key"][-11:], sorted((v["number"] for v in l["vols"]), key=int), l["origin"], l["medium_why"])
                           for l in res[0])
ch = KL.bnf_lines({U.ark(r): r for r in [HEAD, HEAD2] + cs[:2] + cs[3:]})
eq("461 $0: two heads of one title + publisher are two lines (never merged, no duplicate-number review); "
   "a volume with no 101 $c inherits its head's kor",
   shape(ch), [("cb39026622x", ["1", "7"], "kor", None), ("cb43300001x", ["1"], "kor", None)])
eq("... inherited origin counted; a volume under an unknown head with no 101 $c stays out",
   (ch[2]["origin_inherited"], ch[2]["dropped"].get("origin_out_of_scope"), ch[2]["dropped"].get("set_record")), (1, 1, 2))
eq("461 $0: a volume without 461 $0 joins the ONE head line of its signature",
   shape(KL.bnf_lines({U.ark(r): r for r in [HEAD] + cs[:3]})), [("cb39026622x", ["1", "7", "8"], "kor", None)])
eq("... and stays apart when two heads share its signature",
   shape(KL.bnf_lines({U.ark(r): r for r in [HEAD, HEAD2] + cs[:4]})),
   [("cb39026622x", ["1", "7"], "kor", None), ("cb39026800x", ["8"], "kor", None), ("cb43300001x", ["1"], "kor", None)])

# 4. the Ize title step resolves only to a comic medium
iz = [dict(key="loc:4", source="loc", medium=None, medium_why=None, origin="kor", name="Semantic error",
           vols=[{"isbns": []}]),
      dict(key="loc:5", source="loc", medium=None, medium_why=None, origin="kor", name="Penelope", vols=[{"isbns": []}]),
      dict(key="dnb:7", source="dnb", medium="novel", medium_why=None, origin="kor", name="Semantic error",
           titles=["Semantic error"], vols=[]),
      dict(key="dnb:6", source="dnb", medium="novel", medium_why=None, origin="kor", name="Penelope",
           titles=["Penelope"], vols=[]),
      dict(key="bnf:5", source="bnf", medium="manhwa", medium_why=None, origin="kor", name="Semantic error",
           titles=["Semantic error"], vols=[])]
KL.resolve_media(iz, {})
eq("Ize title step: a novel-only match, or a novel beside a comic, leaves the LoC line in review",
   [(l["key"], l["medium"], l.get("medium_via")) for l in iz[:2]], [("loc:4", None, None), ("loc:5", None, None)])

# 5. every review reason is kept: 'both' AND duplicate numbers -> 'duplicate_numbers+both'
LB1 = lrec("01000cam a2200000 i 4500", "250302s2025    nyu           000 1 eng  ", ("010", [("a", "  2025060001")]),
           ("020", [("a", isbn13("97817", 60001))]), DLC, ("041", [("a", "eng"), ("h", "kor")]),
           ("082", [("a", "895.73")]), ("655", [("a", "Graphic novels")]), ("245", [("a", "Dual."), ("n", "1")]),
           VOL338, cid="lb1")
LB2 = lrec("01000cam a2200000 i 4500", "250302s2025    nyu           000 1 eng  ", ("010", [("a", "  2025060002")]),
           ("020", [("a", isbn13("97817", 60002))]), DLC, ("041", [("a", "eng"), ("h", "kor")]), ("082", [("a", "741.5")]),
           ("245", [("a", "Dual."), ("n", "1")]), VOL338, cid="lb2")
lb = KL.loc_lines({"lb1": LB1, "lb2": LB2})
eq("both reasons kept, '+'-joined in rule order", [(l["medium"], l["medium_why"], l["medium_why"].split("+")) for l in lb[0]],
   [(None, "duplicate_numbers+both", ["duplicate_numbers", "both"])])
eq("stats count the joined reason", lb[2]["review"], {"duplicate_numbers+both": 1})

# ---- Task 11: identity ------------------------------------------------------------------------------------
import krcn_identity as KI
from load import _id


def carry_file(name, lines, works=(), krcn_lines=None, ints=None):
    """lines: [(tome_id, work, name, medium, language, [(number, isbn)])] -> a minimal carried artifact."""
    p = os.path.join(tempfile.mkdtemp(prefix="krcn-carry-"), name + ".sqlite")
    A = sqlite3.connect(p)
    A.executescript("""CREATE TABLE series (gcd_series_id INTEGER PRIMARY KEY, name TEXT, tome_id TEXT,
                         tome_work_id TEXT, medium TEXT, language TEXT, country TEXT);
                       CREATE TABLE volumes (gcd_series_id INTEGER, tome_id TEXT, volume_number INTEGER, isbn13 TEXT,
                         release_date_raw TEXT);
                       CREATE TABLE id_map (opentome_id TEXT PRIMARY KEY, int_id INTEGER, kind TEXT);
                       CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);""")
    for k, (tid, w, nm, med, lang, vols) in enumerate(lines, 1):
        i = (ints or {}).get(tid, k * 10)
        A.execute("INSERT INTO series VALUES(?,?,?,?,?,?,NULL)", (i, nm, tid, w, med, lang))
        A.execute("INSERT INTO id_map VALUES(?,?,'release_line')", (tid, i))
        for n, isbn in vols:
            A.execute("INSERT INTO volumes VALUES(?,?,?,?,NULL)", (i, _id("v_", tid, n), int(n), isbn))
    if krcn_lines is not None:
        A.execute("INSERT INTO meta VALUES('krcn_ids',?)", (json.dumps({"works": list(works), "lines": krcn_lines}),))
    A.commit()
    return p


def bl(key, source, name, vols):
    return {"key": key, "source": source, "name": name,
            "vols": [{"number": n, "isbns": [i] if i else []} for n, i in vols]}


I5 = [("%d" % n, "97984009%05d" % n) for n in range(1, 6)]
eq("no carry: every id minted from its key", (lambda l: (KI.line_ids([l], None), l["tome_id"], l["carried"]))(
    bl("loc:2023941160", "loc", "Semantic error", I5))[1:], (_id("rl_", "loc:2023941160"), False))
K = KI.read_carry(carry_file("c1", [("rl_old", "w_lib", "Semantic error", "manhwa", "en", I5)],
                             works=["w_lib"], krcn_lines={"rl_old": "loc"}))
ln = bl("loc:2022000001", "loc", "Semantic error", I5 + [("6", "9798400900006")])  # an older record joined: key moved
KI.line_ids([ln], K)
eq("carry lookup: the re-keyed line keeps its published id (strict majority of ISBNs)", (ln["tome_id"], ln["carried"]),
   ("rl_old", True))
ln = bl("loc:2022000001", "loc", "Semantic error", I5[:2])
KI.line_ids([ln], K)
eq("2 of 5: no majority -> minted", ln["tome_id"], _id("rl_", "loc:2022000001"))
ln = bl("dnb:1", "dnb", "Semantic error", I5)
KI.line_ids([ln], K)
eq("another source never takes a carried library line", ln["tome_id"], _id("rl_", "dnb:1"))
K2 = KI.read_carry(carry_file("c2", [("rl_a", "w_1", "X", "manhwa", "en", I5[:3]), ("rl_b", "w_1", "X", "manhwa", "en", I5[3:])],
                              works=["w_1"], krcn_lines={"rl_a": "loc", "rl_b": "loc"}, ints={"rl_a": 20, "rl_b": 10}))
ln = bl("loc:9", "loc", "X", I5)
KI.line_ids([ln], K2)
eq("two carried lines merge: the older integer's id wins, the other is absorbed", (ln["tome_id"], ln["absorbed_ids"]),
   ("rl_b", ["rl_a"]))
K3 = KI.read_carry(carry_file("c3", [("rl_r", "w_2", "Raeliana", "manhwa", "de", [("1", None), ("2", None)])],
                              works=["w_2"], krcn_lines={"rl_r": "dnb"}))
ln = bl("dnb:77", "dnb", "Raeliana", [("1", None), ("2", None)])
KI.line_ids([ln], K3)
eq("no ISBNs anywhere: volume numbers + the same folded name", ln["tome_id"], "rl_r")
eq("older(): lowest carried integer; a work's is its lines' minimum", (KI.older(["rl_a", "rl_b"], K2), KI.older(["w_1"], K2)),
   ("rl_b", "w_1"))

# attach in any direction
E = {"rl_x": {"work": "w_wiki", "medium": "manhwa", "vols": {"1": ("v1", "a1"), "2": ("v2", "a2"), "3": ("v3", "a3")}}}
e_isbn = {"a1": ("rl_x", "v1"), "a2": ("rl_x", "v2"), "a3": ("rl_x", "v3")}


def att(carried_lib, x_carried, ints):
    K_ = {"series_ids": ({"rl_lib"} if carried_lib else set()) | ({"rl_x"} if x_carried else set()),
          "int": ints, "works": set(), "lines": {}}
    a = {"key": "loc:1", "tome_id": "rl_lib", "carried": carried_lib,
         "vols": [{"number": n, "isbns": [i]} for n, i in (("1", "a1"), ("2", "a2"), ("3", "a3"))]}
    b = {"key": "loc:2", "tome_id": "rl_lib2", "carried": False, "vols": [{"number": "1", "isbns": ["a1"]}]}
    KI.attach_roles([a, b], E, e_isbn, K_)
    return a.get("role"), a.get("target"), b.get("role"), a.get("work")


eq("new library line + an existing line: merged into it (the existing id kept)", att(False, False, {})[:1], ("merged",))
eq("a carried library line + an uncarried Wikipedia newcomer: the library line adopts it (R1)",
   att(True, False, {"rl_lib": 5}), ("adopting", "rl_x", "sibling", "w_wiki"))
eq("both carried: the older integer wins (library 5 < wiki 9)", att(True, True, {"rl_lib": 5, "rl_x": 9})[0], "adopting")
eq("both carried: the older integer wins (wiki 3 < library 5)", att(True, True, {"rl_lib": 5, "rl_x": 3})[0], "merged")

# rename_work and adopt_line on a real schema
db = schema_db()
db.execute("INSERT INTO work VALUES('w_wiki','Wiki',NULL,NULL,NULL,NULL,'x','x')")
db.execute("INSERT INTO work_title VALUES('w_wiki','en','Wiki','official')")
line_row(db, "rl_x", "w_wiki", "manhwa", "EN", "en")
line_row(db, "rl_lib", "w_wiki", "manhwa", "EN", "en")
db.execute("INSERT INTO claim VALUES('work','w_wiki','author','[\"A\"]','wikipedia',NULL,'facts_only','x')")
KI.rename_work(db.cursor(), "w_wiki", "w_lib")
eq("rename_work: every row follows", [db.execute(q).fetchone()[0] for q in (
    "SELECT COUNT(*) FROM work WHERE id='w_lib'", "SELECT COUNT(*) FROM work_title WHERE work_id='w_lib'",
    "SELECT COUNT(*) FROM release_line WHERE work_id='w_lib'", "SELECT COUNT(*) FROM claim WHERE entity_id='w_lib'",
    "SELECT COUNT(*) FROM work WHERE id='w_wiki'")], [1, 1, 2, 1, 0])
for vid, rid, n, isbn, date, prec in (("v_l1", "rl_lib", "1", "a1", "2021", "year"), ("v_x1", "rl_x", "1", "a1", "2021-03-02", "day"),
                                      ("v_x2", "rl_x", "2", "a2", "2021-06-01", "day")):
    db.execute("INSERT INTO volume(id,release_line_id,number,isbn13,release_date,release_date_precision,"
               "release_date_type,created_at,updated_at) VALUES(?,?,?,?,?,?,'published','x','x')", (vid, rid, n, isbn, date, prec))
    db.execute("INSERT INTO claim VALUES('volume',?,'release_date',?,?,NULL,'x','x')",
               (vid, date, "loc" if rid == "rl_lib" else "wikipedia"))
KI.adopt_line(db.cursor(), "rl_x", "rl_lib")
eq("adopt_line: the internal line is gone", db.execute("SELECT COUNT(*) FROM release_line WHERE id='rl_x'").fetchone()[0], 0)
eq("adopt_line: vol 1 keeps the public id, takes the finer Wikipedia date and its claim",
   (db.execute("SELECT release_date FROM volume WHERE id='v_l1'").fetchone()[0],
    sorted(r[0] for r in db.execute("SELECT source FROM claim WHERE entity_id='v_l1'"))), ("2021-03-02", ["loc", "wikipedia"]))
eq("adopt_line: vol 2 moves over under the public line's volume id",
   db.execute("SELECT id FROM volume WHERE release_line_id='rl_lib' AND number='2'").fetchone()[0], _id("v_", "rl_lib", "2"))

# ---- Task 11 deviations: split collisions, dangling references, determinism -----------------------------------
# A carried line minted from loc:100 split this build: loc:200 holds 3 of its 5 ISBNs and takes the id by the
# carry lookup; loc:100 (2 of 5) would mint the same id again. One id for two lines is never emitted.
rl100 = _id("rl_", "loc:100")
K4 = KI.read_carry(carry_file("c4", [(rl100, "w_4", "Split", "manhwa", "en", I5)], works=["w_4"], krcn_lines={rl100: "loc"}))
split = [bl("loc:100", "loc", "Split", I5[:2]), bl("loc:200", "loc", "Split", I5[2:])]
try:
    KI.line_ids(split, K4)
    eq("a split of a carried line whose natural key re-mints the taken id: refused", "no error", "ValueError")
except ValueError as e:
    eq("a split of a carried line whose natural key re-mints the taken id: refused, naming the id and both keys",
       (rl100 in str(e), "loc:100" in str(e), "loc:200" in str(e)), (True, True, True))
eq("the same split with the natural-key line alone: it keeps its id by its key (no carry majority needed)",
   (lambda l: (KI.line_ids([l], K4), l["tome_id"], l["carried"]))(bl("loc:100", "loc", "Split", I5[:2]))[1:], (rl100, True))
K5 = KI.read_carry(carry_file("c5", [("rl_t", "w_5", "Tie", "manhwa", "en", I5[:4])], works=["w_5"], krcn_lines={"rl_t": "loc"}))
tie = [bl("loc:7", "loc", "Tie", I5[:2]), bl("loc:8", "loc", "Tie", I5[2:4])]
rep = KI.line_ids(tie, K5)
eq("2 + 2 of 4: no strict majority for anyone -> not taken, both minted", ([l["tome_id"] for l in tie], rep["ambiguous"]),
   ([_id("rl_", "loc:7"), _id("rl_", "loc:8")], []))
rev = [dict(bl("loc:9", "loc", "X", I5[:3])), dict(bl("loc:10", "loc", "X", I5[3:]))]
KI.line_ids(rev, K2)
fwd = [dict(bl("loc:10", "loc", "X", I5[3:])), dict(bl("loc:9", "loc", "X", I5[:3]))]
KI.line_ids(fwd, K2)
eq("line_ids is order-independent", sorted((l["key"], l["tome_id"]) for l in rev), sorted((l["key"], l["tome_id"]) for l in fwd))
eq("read_carry without meta krcn_ids: no library-born lines, so nothing is looked up",
   KI.read_carry(carry_file("c6", [("rl_q", "w_q", "Q", "manga", "en", I5)]))["lines"], {})

# existing_lines: two lines of one market sharing an ISBN -> the lowest line id holds it, whatever the row order
for order in (("rl_b2", "rl_a2"), ("rl_a2", "rl_b2")):
    dbe = schema_db()
    dbe.execute("INSERT INTO work VALUES('w_e','E',NULL,NULL,NULL,NULL,'x','x')")
    for rid in order:
        line_row(dbe, rid, "w_e", "manhwa", "EN", "en")
        dbe.execute("INSERT INTO volume(id,release_line_id,number,isbn13,created_at,updated_at) VALUES(?,?,'1','i1','x','x')",
                    ("v_" + rid, rid))
    E2, ei2 = KI.existing_lines(dbe, "EN")
    eq("existing_lines: a shared ISBN goes to the lowest line id (%s first)" % order[0], (sorted(E2), ei2["i1"]),
       (["rl_a2", "rl_b2"], ("rl_a2", "v_rl_a2")))

# adopt_line / rename_work: redirects, compositions and DNB staging that name the internal ids follow them
db2 = schema_db()
db2.executescript(B.STAGING_DDL)
db2.execute("INSERT INTO work VALUES('w_i','I',NULL,NULL,NULL,NULL,'x','x')")
db2.execute("INSERT INTO work VALUES('w_p','P',NULL,NULL,NULL,NULL,'x','x')")
line_row(db2, "rl_i", "w_i", "manhwa", "DE", "de")
line_row(db2, "rl_p", "w_p", "manhwa", "DE", "de")
for vid, rid, n in (("v_i1", "rl_i", "1"), ("v_i2", "rl_i", "2"), ("v_p1", "rl_p", "1")):
    db2.execute("INSERT INTO volume(id,release_line_id,number,created_at,updated_at) VALUES(?,?,?,'x','x')", (vid, rid, n))
for vid in ("v_i1", "v_p1"):
    db2.execute("INSERT INTO composition VALUES(?,'chapter','[1,2]',NULL)", (vid,))
db2.execute("INSERT INTO id_redirect VALUES('rl_old_de','rl_i','release_line','correction','x')")
db2.execute("INSERT INTO id_redirect VALUES('v_old1','v_i1','volume','correction','x')")
db2.execute("INSERT INTO id_redirect VALUES('v_old2','v_i2','volume','correction','x')")
db2.execute("INSERT INTO id_redirect VALUES('w_old','w_i','work','duplicate_merge','x')")
db2.execute("INSERT INTO dnb_line(key,rl_id,role,wiki_line,truth_work,exported) VALUES('dnb:5','rl_x5','sibling','rl_i','w_i',1)")
c2 = db2.cursor()
eq("adopt_line: one volume moved, one merged (identical composition rows collapse)", KI.adopt_line(c2, "rl_i", "rl_p"), (1, 1))
KI.rename_work(c2, "w_i", "w_i2")
eq("adopt_line / rename_work: every redirect still names a present id",
   sorted(db2.execute("SELECT old_id, new_id FROM id_redirect")),
   [("rl_old_de", "rl_p"), ("v_old1", "v_p1"), ("v_old2", _id("v_", "rl_p", "2")), ("w_old", "w_i2")])
eq("adopt_line: the public volume keeps one composition row", db2.execute(
    "SELECT volume_id, COUNT(*) FROM composition GROUP BY volume_id").fetchall(), [("v_p1", 1)])
eq("adopt_line / rename_work: dnb_line's Wikipedia line and truth work follow",
   db2.execute("SELECT wiki_line, truth_work FROM dnb_line").fetchone(), ("rl_p", "w_i2"))
try:
    KI.rename_work(c2, "w_i2", "w_p")
    eq("rename_work onto an existing work: refused", "no error", "ValueError")
except ValueError:
    eq("rename_work onto an existing work: refused", True, True)

# ==== summary ====
print()
if FAILS:
    print("%d FAILED: %s" % (len(FAILS), FAILS))
    sys.exit(1)
print("all krcn tests passed")
