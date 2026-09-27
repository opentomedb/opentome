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
    if size > 1 and LRULE["fail"](query, start, size, LSEEN[key]):
        return _R(DIAG61 % (len(ids), LRULE["code"]))
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

# ==== summary ====
print()
if FAILS:
    print("%d FAILED: %s" % (len(FAILS), FAILS))
    sys.exit(1)
print("all krcn tests passed")
