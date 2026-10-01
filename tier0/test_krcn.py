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
eq("duplicate position: one read, cached with distinct < n (option 1, one read)",
   (n, LS.LOC.distinct(pages), man["distinct"], sorted({re.search(r"maximumRecords=(\d+)", u).group(1) for u in man["urls"]})),
   (81, 80, 80, ["100"]))
eq("... duplicate positions reported (count + 001s)",
   {k: ldups()["bath.isbn=9798855491*"][k] for k in ("positions", "dup_ids")}, {"positions": 1, "dup_ids": ["3110"]})
k = len(LCALLS)
eq("... served whole from the cache afterwards", (LS.search_set("bath.isbn=9798855491*")[0], len(LCALLS) - k), (81, 0))
# B. at 100 a duplicate masks record 3160: one read only (option 1), so the gap stays and is reported
LRULE["seq"] = (lambda q, ids, sz: (lambda base: lmask(base, 61) if sz == 100 else base)(ids[:50] + [ids[10]] + ids[50:])
                if q == "bath.isbn=9798855491*" else ids)
n, pages = LS.search_set("bath.isbn=9798855491*", force=True)
eq("masked record: one read, no re-read -- the gap (2) is reported unconfirmed",
   (n, LS.LOC.distinct(pages), [r[0] for r in ldups()["bath.isbn=9798855491*"]["reads"]], LS.LOC.degraded),
   (81, 79, [100], None))
# C. every read finds a record the earlier ones lacked (live C0 2026-09-29: LoC hands out a Yen stem's
#    records differently on each read). Option 1, one read (Nick 2026-09-29): the read is accepted and the
#    gap (announced - distinct) is recorded per set as unconfirmed; not degraded, never re-read or sliced for it.
LOCDB.update({str(3200 + k): ([isbn13("9798855492", k)], True) for k in range(80)})
LRULE["seq"] = lambda q, ids, sz: lmask(ids, 60, 70) if sz == 100 else lmask(ids, 70) if sz == 50 else lmask(ids, 30)
k = len(LCALLS)
n, pages = LS.search_set("bath.isbn=9798855492*")
dd = ldups()["bath.isbn=9798855492*"]
eq("records missing from the read: accepted with the gap (2) recorded as unconfirmed, no re-read",
   (n, LS.LOC.distinct(pages), dd["positions"], dd["unconfirmed"], [r[2] for r in dd["reads"]], LS.LOC.degraded,
    any(re.search(r"isbn%3D9798855492\d", u) for u in LCALLS[k:])),
   (80, 78, 2, True, [0], None, False))
eq("... and stored: a later offline read serves the set", json.load(open(LS.LOC.sets_path))["bath.isbn=9798855492*"]["n"], 80)
n, pages = LS.search_set('dc.subject="webcomics"', force=True)
eq("still growing on a subject set: accepted the same way, not degraded",
   (LS.LOC.degraded, ldups()['dc.subject="webcomics"']["unconfirmed"]), (None, True))
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
    c["duplicates"]["bath.isbn=9798855491*"]["dup_ids"], len(recs)), (81, 79, 79, 1.0, 2, ["3110", "3159"], 79))
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

# ---- C0 ruling 2026-09-29: a stem announcing more than the reachable window is sliced before any page ----
# (runner C0 run 36523225783: 97988554* announced 564, reads at 100/50/25 kept finding new records [0, 9, 5])
LOCDB.update({str(6000 + k): ([isbn13("97988559%d" % (k % 10), k)], True) for k in range(520)})
LRULE["seq"] = lambda q, ids, sz: ((lmask(ids, 100, 200) if sz == 100 else lmask(ids, 300) if sz == 50 else lmask(ids, 400))
                                   if q == "bath.isbn=97988559*" else ids)
LS.LOC.degraded, LS.LOC.degraded_queries = None, []
k = len(LCALLS)
n, pages = LS.search_set("bath.isbn=97988559*")
stem_pages = [u for u in LCALLS[k:] if "query=bath.isbn%3D97988559%2A&" in u and "maximumRecords=1&" not in u]
slice_qs = {urllib.parse.parse_qs(urllib.parse.urlparse(u).query)["query"][0] for u in LCALLS[k:]} - {"bath.isbn=97988559*"}
eq("a stem over the window: no stem page is read, its ten prefixes are, the union is complete",
   (len(stem_pages), len(slice_qs), n, LS.LOC.distinct(pages), LS.LOC.degraded), (0, 10, 520, 520, None))
LRULE.pop("seq")
for k in range(520):
    del LOCDB[str(6000 + k)]

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
eq("ruling 4 (BnF): Saphir / Saphir Éditions share the family 'saphir' (not 'Saphira', which is"
   " now the samji/tokebi/saphira rename family below)",
   (U.pubfam("Saphir"), U.pubfam("Saphir Éditions")), ("saphir", "saphir"))
bl = KL.bnf_lines({U.ark(r): r for r in (
    brec(("010", [("a", isbn13("97823", 1))]), ("101", [("a", "fre"), ("c", "kor")]), ("200", [("a", "Chiro"), ("h", "1")]),
         ("210", [("c", "Saphir"), ("d", "2006")]), cf3="http://catalogue.bnf.fr/ark:/12148/cb40000001x"),
    brec(("010", [("a", isbn13("97823", 2))]), ("101", [("a", "fre"), ("c", "kor")]), ("200", [("a", "Veritas"), ("h", "2")]),
         ("210", [("c", "Saphir Éditions"), ("d", "2006")]), cf3="http://catalogue.bnf.fr/ark:/12148/cb40000002x"))})[0]
eq("ruling 4 (BnF): ... but two different titles stay two lines", sorted(l["name"] for l in bl), ["Chiro", "Veritas"])
eq("BnF family: an 'Éd.' word is dropped ('Éd. Ki-oon' = 'Ki-oon', Warlord), 'Pika éd.' = 'pika'",
   (U.pubfam("Éd. Ki-Oon"), U.pubfam("Ki-oon"), U.pubfam("Pika éd.")), ("kion", "kion", "pika"))

# P10 triggered (2026-09-28): Samji = Tokebi = Saphira, an imprint rename mid-series (14 French KR
# titles, e.g. Chiro: Saphira 1-4, Samji 5-8) -- a headless volume under the old and the new imprint
# now share one family, so the two join into one line instead of splitting on the rename
eq("Samji / Tokebi / Saphira are one publisher family",
   (U.pubfam("Saphira"), U.pubfam("Samji"), U.pubfam("Tokebi"), U.pubfam("éd. Tokebi")),
   ("samji", "samji", "samji", "samji"))
chiro = KL.bnf_lines({U.ark(r): r for r in (
    brec(("010", [("a", isbn13("97823", 201))]), ("101", [("a", "fre"), ("c", "kor")]), ("200", [("a", "Chiro"), ("h", "1")]),
         ("210", [("c", "Saphira"), ("d", "2006")]), cf3="http://catalogue.bnf.fr/ark:/12148/cb45000001x"),
    brec(("010", [("a", isbn13("97823", 205))]), ("101", [("a", "fre"), ("c", "kor")]), ("200", [("a", "Chiro"), ("h", "5")]),
         ("210", [("c", "Samji"), ("d", "2009")]), cf3="http://catalogue.bnf.fr/ark:/12148/cb45000002x"))})[0]
eq("a Saphira 1-4 + Samji 5-8 pair (here vols 1 and 5) is one line, not two",
   [(l["name"], sorted((v["number"] for v in l["vols"]), key=int)) for l in chiro], [("Chiro", ["1", "5"])])

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


def carry_file(name, lines, works=(), krcn_lines=None, ints=None, pubs=None):
    """lines: [(tome_id, work, name, medium, language, [(number, isbn)])] -> a minimal carried artifact;
    pubs: {tome_id: series.publisher}."""
    p = os.path.join(tempfile.mkdtemp(prefix="krcn-carry-"), name + ".sqlite")
    A = sqlite3.connect(p)
    A.executescript("""CREATE TABLE series (gcd_series_id INTEGER PRIMARY KEY, name TEXT, tome_id TEXT,
                         tome_work_id TEXT, medium TEXT, language TEXT, country TEXT, publisher TEXT);
                       CREATE TABLE volumes (gcd_series_id INTEGER, tome_id TEXT, volume_number INTEGER, isbn13 TEXT,
                         release_date_raw TEXT);
                       CREATE TABLE id_map (opentome_id TEXT PRIMARY KEY, int_id INTEGER, kind TEXT);
                       CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);""")
    for k, (tid, w, nm, med, lang, vols) in enumerate(lines, 1):
        i = (ints or {}).get(tid, k * 10)
        A.execute("INSERT INTO series VALUES(?,?,?,?,?,?,NULL,?)", (i, nm, tid, w, med, lang, (pubs or {}).get(tid)))
        A.execute("INSERT INTO id_map VALUES(?,?,'release_line')", (tid, i))
        for n, isbn in vols:
            A.execute("INSERT INTO volumes VALUES(?,?,?,?,NULL)", (i, _id("v_", tid, n), int(n), isbn))
    if krcn_lines is not None:
        A.execute("INSERT INTO meta VALUES('krcn_ids',?)", (json.dumps({"works": list(works), "lines": krcn_lines}),))
    A.commit()
    return p


def bl(key, source, name, vols, publisher=None):
    return {"key": key, "source": source, "name": name, "publisher": publisher,
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
eq("a lone part with 2 of 5 keeps the published id (plurality, controller ruling 2026-09-27)",
   (ln["tome_id"], ln["carried"]), ("rl_old", True))
ln = bl("loc:2022000001", "loc", "Semantic error", [("1", "9798400999991"), ("2", "9798400999992")])
KI.line_ids([ln], K)
eq("a line holding none of the carried line's volumes never takes it -> minted", ln["tome_id"], _id("rl_", "loc:2022000001"))
ln = bl("dnb:1", "dnb", "Semantic error", I5)
KI.line_ids([ln], K)
eq("another source never takes a carried library line", ln["tome_id"], _id("rl_", "dnb:1"))
K2 = KI.read_carry(carry_file("c2", [("rl_a", "w_1", "X", "manhwa", "en", I5[:3]), ("rl_b", "w_1", "X", "manhwa", "en", I5[3:])],
                              works=["w_1"], krcn_lines={"rl_a": "loc", "rl_b": "loc"}, ints={"rl_a": 20, "rl_b": 10}))
ln = bl("loc:9", "loc", "X", I5)
KI.line_ids([ln], K2)
eq("two carried lines meet in one built line: it takes the older integer's id, the other is NOT absorbed (continuity "
   "ruling: left to 7b)", (ln["tome_id"], ln["absorbed_ids"]), ("rl_b", []))
K3 = KI.read_carry(carry_file("c3", [("rl_r", "w_2", "Raeliana", "manhwa", "de", [("1", None), ("2", None)])],
                              works=["w_2"], krcn_lines={"rl_r": "dnb"}, pubs={"rl_r": "Altraverse"}))
ln = bl("dnb:77", "dnb", "Raeliana", [("1", None), ("2", None)], "Altraverse GmbH")
KI.line_ids([ln], K3)
eq("no ISBNs anywhere: volume numbers + the same folded name + the same publisher family (final ruling (b))",
   ln["tome_id"], "rl_r")
ln = bl("dnb:77", "dnb", "Raeliana", [("1", None), ("2", None)])
KI.line_ids([ln], KI.read_carry(carry_file("c3b", [("rl_r", "w_2", "Raeliana", "manhwa", "de", [("1", None), ("2", None)])],
                                           works=["w_2"], krcn_lines={"rl_r": "dnb"})))
eq("... with no carried publisher and another minting key: minted (final ruling (c) fails)", ln["tome_id"], _id("rl_", "dnb:77"))
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

# ---- Task 11: the frozen acceptance set -- controller ruling 2026-09-27 "continuity first" ------------------------
# 1. a line whose own-key id is carried keeps it (never takes / absorbs); 2. the lookup only for the others, only vs
# unclaimed carried library lines: (a) >= 2 shared ISBNs | (b) same folded name + same non-empty publisher family;
# 3. no absorption: every carried id neither kept nor taken is left to 7b.
import copy, pickle
M = lambda k: _id("rl_", k)
YEN, SEAS = "Yen Press", "Seven Seas Entertainment"
I10 = [("%d" % n, "97984010%05d" % n) for n in range(1, 11)]


def carry(name, rows, pubs=None, ints=None, src="loc"):
    """rows: [(tome_id, name, [(number, isbn)])] -> read_carry of library-born lines of one source."""
    return KI.read_carry(carry_file(name, [(t, "w_" + name, nm, "manhwa", "en", v) for t, nm, v in rows], works=["w_" + name],
                                    krcn_lines={t: src for t, _, _ in rows}, ints=ints, pubs=pubs))


def run(lines, K_, **kw):
    rep_ = KI.line_ids(lines, K_, **kw)
    return [(l["key"], l["tome_id"], l["carried"]) for l in lines], rep_


# A
got, r = run([bl("loc:500", "loc", "Other", [("1", I10[0][1]), ("2", "9798400888882")], YEN)],
             carry("fA", [("rl_tw", "Tower", I10)], pubs={"rl_tw": YEN}))
eq("A: an unrelated new line holding 1 of T's 10 ISBNs does not take T (T left to 7b)", (got, r["left"]),
   ([("loc:500", M("loc:500"), False)], ["rl_tw"]))
# B
lnb = bl("loc:600", "loc", "Alpha", I10[:9] + [("10", I5[0][1])], YEN)
got, r = run([lnb], carry("fB", [("rl_al", "Alpha", I10), ("rl_be", "Beta", I5)], pubs={"rl_al": YEN, "rl_be": YEN},
                         ints={"rl_al": 20, "rl_be": 10}))
eq("B: 9 of 10 of T plus 1 stray ISBN of the older T2: takes T, absorbs nothing, T2 left to 7b",
   (got, lnb["absorbed_ids"], r["left"], r["taken_weak"]), ([("loc:600", "rl_al", True)], [], ["rl_be"], []))
# C
gid = M("loc:100")
KCf = carry("fC", [(gid, "Gamma", I5)], pubs={gid: YEN})
got, r = run([bl("loc:100", "loc", "Gamma", [("1", "9798400777771")], YEN), bl("loc:300", "loc", "Delta", [("1", I5[0][1])], YEN)], KCf)
eq("C: the key-maker holding none of T keeps T (continuity); the different-name stray-ISBN line mints its own key",
   got, [("loc:100", gid, True), ("loc:300", M("loc:300"), False)])
# E
te = M("loc:100")
KEf = carry("fE", [(te, "Eps", I5)], pubs={te: YEN}, ints={te: 10})
le = [bl("loc:100", "loc", "Eps", I5[:2], YEN), bl("loc:200", "loc", "Eps", I5[2:], YEN)]
got, r = run(le, KEf)
eq("E: the carried line keeps its own id (continuity); the other part mints its own key",
   got, [("loc:100", te, True), ("loc:200", M("loc:200"), False)])
EX = {"rl_xe": {"work": "w_we", "medium": "manhwa", "vols": {n: ("vx" + n, i) for n, i in I5[:2]}}}
KI.attach_roles([le[0]], EX, {i: ("rl_xe", "vx" + n) for n, i in I5[:2]}, KEf)
eq("E: a carried library line meeting an uncarried existing line adopts it (not merged)", (le[0]["role"], le[0]["target"]),
   ("adopting", "rl_xe"))
# S1 / S2 / N2: another publisher's same-name line
KR = carry("fR", [("rl_rb", "Rebirth", I5)], pubs={"rl_rb": YEN})
KR2 = carry("fR2", [("rl_rb2", "Rebirth", [("1", None), ("2", None)])], pubs={"rl_rb2": YEN})
got, r = run([bl("loc:801", "loc", "Rebirth", [("1", I5[0][1]), ("2", "9798400666662")], SEAS)], KR)
eq("S1: another publisher's 'Rebirth' holding 1 of 5 does not take T", (got, r["left"]),
   ([("loc:801", M("loc:801"), False)], ["rl_rb"]))
got, r = run([bl("loc:802", "loc", "Rebirth", [("1", None), ("2", None)], SEAS)], KR2)
eq("S2: another publisher, 0 ISBNs, bare vols 1-2, same name: does not take T", got, [("loc:802", M("loc:802"), False)])
got, r = run([bl("loc:803", "loc", "Rebirth", [("1", None), ("2", None)], "Ize Press")], KR2)
eq("S2': the same bare vols under T's publisher family (Ize = Yen) take T -- listed weak (0 of 0 ISBNs)",
   (got, r["taken_weak"]), ([("loc:803", "rl_rb2", True)], [("rl_rb2", "loc:803", 0, 0)]))
got, r = run([bl("loc:807", "loc", "Rebirth", [("1", None), ("2", None)], SEAS)], KR)
eq("N2: another publisher's same-name line with bare vols 1-2 against an ISBN'd T: no take", got, [("loc:807", M("loc:807"), False)])
# S3 / S4
got, r = run([bl("loc:804", "loc", "Rebirth", [("3", I5[2][1])], YEN)], KR)
eq("S3_alt same-family-1-of-5: same name + same publisher family holding 1 of 5 takes T (b), listed weak",
   (got, r["taken_weak"]), ([("loc:804", "rl_rb", True)], [("rl_rb", "loc:804", 1, 5)]))
got, r = run([bl("loc:805", "loc", "Rebirth: the renamed edition", I5[:2], SEAS)], KR)
eq("S4_alt renamed-2-ISBN: renamed, another publisher, 2 shared ISBNs takes T (a), listed weak",
   (got, r["taken_weak"]), ([("loc:805", "rl_rb", True)], [("rl_rb", "loc:805", 2, 5)]))
# S5 / S7 / N1: one-volume carried lines
t5 = M("loc:555")
got, r = run([bl("loc:0001", "loc", "Solo", [("1", I5[0][1])]), bl("loc:555", "loc", "Solo", [("1", I5[0][1])])],
             carry("fS5", [(t5, "Solo", I5[:1])]))
eq("S5_alt lower-key-same-name-stray: the real minting line keeps T; the lower-key same-name stray wins no tie and mints its own key",
   got, [("loc:0001", M("loc:0001"), False), ("loc:555", t5, True)])
K7f = carry("fS7", [("rl_one", "Solo", I5[:1])], pubs={"rl_one": YEN})
got, r = run([bl("loc:700", "loc", "An anthology", [("1", I5[0][1])], YEN)], K7f)
eq("S7: a stray line holding the one ISBN of a 1-volume T does not take it", got, [("loc:700", M("loc:700"), False)])
got, r = run([bl("loc:701", "loc", "Solo", [("1", I5[0][1])], SEAS)], K7f)
eq("N1: 1 of 1 is no longer enough: another publisher's same-name line with T's one ISBN does not take it",
   got, [("loc:701", M("loc:701"), False)])
got, r = run([bl("loc:702", "loc", "Solo", [("1", I5[0][1])], "Ize Press")], K7f)
eq("one-volume T, its minting record gone: the same name + family holding its ISBN takes it (1 of 1: not weak)",
   (got, r["taken_weak"]), ([("loc:702", "rl_one", True)], []))
got, r = run([bl("loc:703", "loc", "Solo", [("1", I5[0][1])], YEN)], carry("fS7b", [(M("loc:703"), "Solo", I5[:1])]))
eq("one-volume T whose minting record is still there: kept by continuity", got, [("loc:703", M("loc:703"), True)])
# S6: no carried publisher -- the ruling's (c) is subsumed by continuity
tc = M("loc:900")
KCc = carry("fS6", [(tc, "Gamma", I5)])
got, r = run([bl("loc:900", "loc", "Gamma", I5[:1]), bl("loc:901", "loc", "Gamma", [("4", I5[3][1])])], KCc)
eq("S6_alt no-carried-publisher: no carried publisher: the minting key keeps T (continuity = the old (c)); the same name under another key mints",
   got, [("loc:900", tc, True), ("loc:901", M("loc:901"), False)])
got, r = run([bl("loc:901", "loc", "Gamma", [("4", I5[3][1])])], KCc)
eq("S6_alt no-carried-publisher: ... the minting record gone, the same name, 1 ISBN, no carried publisher: no take (b needs a publisher)",
   (got, r["left"]), ([("loc:901", M("loc:901"), False)], [tc]))
got, r = run([bl("loc:900", "loc", "Gamma renamed", I5[:1]), bl("loc:902", "loc", "Gamma", I5[1:4])], KCc)
eq("S6_alt no-carried-publisher: the minting key under another name still keeps T (continuity is unconditional); the 3-ISBN part mints its own key",
   got, [("loc:900", tc, True), ("loc:902", M("loc:902"), False)])
# R1 .. R6
KR1 = carry("fR1", [(M("loc:1"), "Same", I5[:3]), (M("loc:2"), "Same", I5[3:]), (M("loc:3"), "Other", [("1", "9798400555551")])],
            pubs={M("loc:1"): YEN, M("loc:2"): YEN, M("loc:3"): YEN})
unchanged = [bl("loc:1", "loc", "Same", I5[:3], YEN), bl("loc:2", "loc", "Same", I5[3:], YEN),
             bl("loc:3", "loc", "Other", [("1", "9798400555551")], YEN)]
got, r = run(unchanged, KR1)
eq("R1_alt unchanged-build: an unchanged build keeps every id (3 kept, 0 taken, 0 left)", (got, r["kept"], r["taken"], r["left"]),
   ([("loc:1", M("loc:1"), True), ("loc:2", M("loc:2"), True), ("loc:3", M("loc:3"), True)], 3, [], []))
TA, TB = M("loc:A1"), M("loc:B1")
lb2 = bl("loc:B1", "loc", "Same", I5[3:] + [("1", I5[0][1])], YEN)
got, r = run([lb2], carry("fR2x", [(TA, "Same", I5[:3]), (TB, "Same", I5[3:])], pubs={TA: YEN, TB: YEN}))
eq("R2: line A gone, B (own key carried) holds a stray ISBN of T_A: B keeps T_B, T_A goes to 7b, nothing absorbed",
   (got, lb2["absorbed_ids"], r["left"]), ([("loc:B1", TB, True)], [], [TA]))
KR3 = carry("fR3", [(M("dnb:1"), "Raeliana", [("1", None), ("2", None)]), (M("dnb:2"), "Raeliana", [("1", None), ("2", None), ("3", None)])],
            pubs={M("dnb:1"): "Altraverse", M("dnb:2"): "Altraverse"}, src="dnb")
for order in (("dnb:1", "dnb:2"), ("dnb:2", "dnb:1")):
    r3 = [bl(k, "dnb", "Raeliana", [("1", None), ("2", None)] + ([("3", None)] if k == "dnb:2" else []), "Altraverse")
          for k in order]
    got, r = run(r3, KR3)
    eq("R3: two unchanged same-name/family zero-ISBN lines keep their own ids (%s first)" % order[0],
       sorted(got), [("dnb:1", M("dnb:1"), True), ("dnb:2", M("dnb:2"), True)])
lr4 = bl("loc:1", "loc", "Same", I5, YEN)
got, r = run([lr4], carry("fR4", [(M("loc:1"), "Same", I5[:2]), ("rl_oth", "Same", I5[2:])], pubs={M("loc:1"): YEN, "rl_oth": YEN}))
eq("R4_alt own-key-never-takes: a line whose own key is carried never takes another carried id, even holding all of it",
   (got, lr4["absorbed_ids"], r["left"]), ([("loc:1", M("loc:1"), True)], [], ["rl_oth"]))
lr5 = bl("loc:9", "loc", "X", I5)
got, r = run([lr5], K2)
eq("R5_alt two-carried-older: a lookup line qualifying for two carried lines takes the older (lowest integer); the other is left, not absorbed",
   (got, lr5["absorbed_ids"], r["left"]), ([("loc:9", "rl_b", True)], [], ["rl_a"]))
t6 = M("loc:100")
K6 = carry("fR6", [(t6, "Six", I5)], pubs={t6: YEN})
got, r = run([bl("loc:200", "loc", "Six", I5[2:], YEN), bl("loc:100", "loc", "Six", I5[:2], YEN)], K6)
eq("R6_alt key-maker-minority: the key-maker (2 of 5) wins over a 3-of-5 part, which mints its own key",
   got, [("loc:200", M("loc:200"), False), ("loc:100", t6, True)])
# splits
got, r = run([bl("loc:100", "loc", "Six", I5[:1], YEN), bl("loc:200", "loc", "Six", I5[1:], YEN)], K6)
eq("split: the minting part keeps T even holding 1 of 5", got, [("loc:100", t6, True), ("loc:200", M("loc:200"), False)])
sp = [bl("loc:300", "loc", "Six", I5[3:], YEN), bl("loc:200", "loc", "Six", I5[:3], YEN)]
got, r = run(sp, K6)
eq("split, the minting record gone: plurality -- the 3-of-5 part takes T (not weak), the 2-of-5 part mints its own key",
   (got, r["taken_weak"]), ([("loc:300", M("loc:300"), False), ("loc:200", t6, True)], []))
got2, _ = run(list(reversed(copy.deepcopy(sp))), K6)
eq("split: order-independent", sorted(got2), sorted(got))
# 7b writes the split's volume redirects (R6: the other part's volumes lost their published ids)
import carried_ids as CI7
mk = CI7.MARKET_OF_LANG["en"]
db7 = schema_db()
db7.execute("INSERT INTO work VALUES('w_6','Six',NULL,NULL,NULL,NULL,'x','x')")
for rid, vs in ((t6, I5[:2]), (M("loc:200"), I5[2:])):
    line_row(db7, rid, "w_6", "manhwa", mk, "en")
    for n, i in vs:
        db7.execute("INSERT INTO volume(id,release_line_id,number,isbn13,created_at,updated_at) VALUES(?,?,?,?,'x','x')",
                    (_id("v_", rid, n), rid, n, i))
r7 = CI7.redirects(db7, carry_file("f7b", [(t6, "w_6", "Six", "manhwa", "en", I5)], works=["w_6"], krcn_lines={t6: "loc"}),
                   excluded=set())
eq("7b: the moved volumes' published ids redirect to the other part's volumes by ISBN, no orphans",
   (sorted(r7["written"]), r7["orphans"]),
   (sorted((_id("v_", t6, n), _id("v_", M("loc:200"), n), "volume", "correction") for n in ("3", "4", "5")), []))
# ties (step 2)
K5t = carry("fT", [("rl_t", "Tie", I5[:4])], pubs={"rl_t": YEN})
tie = [bl("loc:7", "loc", "Tie", I5[2:4], YEN), bl("loc:8", "loc", "Tie", I5[:2], YEN)]
got, r = run(tie, K5t)
eq("tie 2 + 2 of 4: the part holding volume 1 takes T (loc:8 over the lower key loc:7), the other mints",
   got, [("loc:7", M("loc:7"), False), ("loc:8", "rl_t", True)])
got2, _ = run(list(reversed(copy.deepcopy(tie))), K5t)
eq("tie: order-independent", sorted(got2), sorted(got))
got, r = run([bl("loc:8", "loc", "Tie", [I5[0], I5[2]], YEN), bl("loc:7", "loc", "Tie", [I5[0], I5[1]], YEN)], K5t)
eq("tie, both holding volume 1: the lowest own key takes T", got, [("loc:8", M("loc:8"), False), ("loc:7", "rl_t", True)])
got, r = run([bl("loc:7", "loc", "Tie", I5[1:2], YEN), bl("loc:8", "loc", "Tie", I5[:1], "Ize Press")],
             carry("fT2", [("rl_g", "Tie", I5)], pubs={"rl_g": YEN}))
eq("tie under (b) (Yen = Ize): the part holding volume 1 takes T, listed weak",
   (got, r["taken_weak"]), ([("loc:7", M("loc:7"), False), ("loc:8", "rl_g", True)], [("rl_g", "loc:8", 1, 5)]))
# precondition: a JP-round id is never an own-key id here (P25 defers such lines before assignment)
try:
    KI.line_ids([bl("dnb:997592818", "dnb", "King of Hell", I5)], None, reserved={M("dnb:997592818")})
    eq("P25 precondition: a line minting a JP-round id is refused", "no error", "AssertionError")
except AssertionError:
    eq("P25 precondition: a line minting a JP-round id is refused", True, True)
eq("read_carry without meta krcn_ids: no library-born lines, so nothing is looked up",
   KI.read_carry(carry_file("c6", [("rl_q", "w_q", "Q", "manga", "en", I5)]))["lines"], {})

# real data (Task 10's lines, build/krcn-t10/lines.pkl, when present): carried under their own minted ids, a rebuild
# on that carry puts 0 lines off their own id
PKL = os.path.join(ROOT, "build", "krcn-t10", "lines.pkl")
if os.path.exists(PKL):
    real = pickle.load(open(PKL, "rb"))
    for sname in sorted(real):
        rl = real[sname][0]
        src = rl[0]["source"] if rl else "loc"
        rows = [(M(l["key"]), "w_real", l["name"], l.get("medium") or "manhwa", l.get("language") or "en",
                 [(v["number"], v.get("isbn") or (v["isbns"][0] if v["isbns"] else None)) for v in l["vols"]
                  if str(v["number"]).isdigit()]) for l in rl]
        Kreal = KI.read_carry(carry_file("real-" + sname, rows, works=["w_real"], krcn_lines={t: src for t, *_ in rows},
                                         pubs={M(l["key"]): l.get("publisher") for l in rl}))
        again = copy.deepcopy(rl)
        rr = KI.line_ids(again, Kreal)
        eq("real data %s (%d lines): a rebuild on its own carry keeps every id (0 off, 0 taken, 0 left)" % (sname, len(rl)),
           (sum(1 for l in again if l["tome_id"] != M(l["key"]) or not l["carried"]), rr["taken"], rr["left"]), (0, [], []))
else:
    print("  skip real-data idempotence: build/krcn-t10/lines.pkl absent")

# ---- Task 11: the reviewer's ORIGINAL scenarios (/tmp/t11rev4/sim.py, re-review 4): every input order, no duplicates ----
import itertools


def perm_run(lines, K_):
    """-> ({key: id}, rep, deterministic): line_ids over every order of `lines`."""
    res, same = None, True
    for perm in itertools.permutations(range(len(lines))):
        ls = [copy.deepcopy(lines[i]) for i in perm]
        rep_ = KI.line_ids(ls, K_)
        ids_ = [l["tome_id"] for l in ls]
        if len(set(ids_)) != len(ids_) or any(l["absorbed_ids"] for l in ls):
            same = False
        got_ = ({l["key"]: l["tome_id"] for l in ls}, rep_)
        if res is not None and got_ != res:
            same = False
        res = got_
    return res[0], res[1], same


def orig(label, K_, lines, expect, left):
    got_, rep_, same = perm_run(lines, K_)
    eq(label, (got_, rep_["left"], same), (expect, sorted(left), True))


T10o = [(str(n), "97811111%05d" % n) for n in range(1, 11)]
T5o = T10o[:5]
rlTo, rlQo = M("loc:100"), M("loc:300")


def K1o(nm, vols):
    return KI.read_carry(carry_file("o-s", [(rlTo, "w_T", nm, "manhwa", "en", vols)], ["w_T"], {rlTo: "loc"}))


orig("S3: the genuine line holds vol 3; a lower-key same-name line holds vol 1 as a stray -> genuine keeps T, the stray mints",
     K1o("Rebirth", T5o), [bl("loc:100", "loc", "Rebirth", [("3", T5o[2][1])]),
                           bl("loc:050", "loc", "Rebirth", [("1", T5o[0][1]), ("2", "9783333300002")])],
     {"loc:100": rlTo, "loc:050": M("loc:050")}, [])
orig("S4: the genuine line holds 4; a same-name line holds 1 stray -> genuine keeps T, the stray mints",
     K1o("Rebirth", T5o), [bl("loc:100", "loc", "Rebirth", T5o[:4]),
                           bl("loc:900", "loc", "Rebirth", [("1", T5o[4][1]), ("2", "9783333300002")])],
     {"loc:100": rlTo, "loc:900": M("loc:900")}, [])
orig("S5: a 1-volume T, the key-maker present, an other-NAME line holds its ISBN -> key-maker keeps T, the other mints",
     K1o("Oneshot", T5o[:1]), [bl("loc:100", "loc", "Oneshot", T5o[:1]),
                               bl("loc:050", "loc", "Other", [("7", T5o[0][1]), ("8", "9783333300002")])],
     {"loc:100": rlTo, "loc:050": M("loc:050")}, [])
Qvo = [("1", "9789999900001"), ("2", "9789999900002")]
K6o = KI.read_carry(carry_file("o-s6", [(rlTo, "w_T", "Tower", "manhwa", "en", T5o), (rlQo, "w_Q", "Quiet", "manhwa", "en", Qvo)],
                               ["w_T", "w_Q"], {rlTo: "loc", rlQo: "loc"}))
orig("S6 (ruled, pinned): T split 3/2 and the minor part loc:300's own key is carried Quiet -> loc:300 KEEPS Quiet's id "
     "(continuity), loc:400 (holding Quiet's volumes) mints its own key",
     K6o, [bl("loc:100", "loc", "Tower", T5o[:3]), bl("loc:300", "loc", "Tower", T5o[3:]), bl("loc:400", "loc", "Quiet", Qvo)],
     {"loc:100": rlTo, "loc:300": rlQo, "loc:400": M("loc:400")}, [])
Ao = [(str(n), "97811111%05d" % n) for n in range(1, 6)]
Bo = [(str(n), "97822222%05d" % n) for n in range(1, 6)]
tAo, tBo = M("loc:100"), M("loc:200")
K2o = KI.read_carry(carry_file("o-r1", [(tAo, "w_A", "Rebirth", "manhwa", "en", Ao), (tBo, "w_B", "Rebirth", "manhwa", "en", Bo)],
                               ["w_A", "w_B"], {tAo: "loc", tBo: "loc"}, ints={tAo: 10, tBo: 20}, pubs={tAo: YEN, tBo: YEN}))
orig("R1: both same-name same-publisher lines present, B holds 1 stray ISBN of A -> each keeps its own id",
     K2o, [bl("loc:100", "loc", "Rebirth", Ao, YEN), bl("loc:200", "loc", "Rebirth", Bo + [("6", Ao[2][1])], YEN)],
     {"loc:100": tAo, "loc:200": tBo}, [])
for src, cp, bp, want in (("loc", "Yen Press", "Yen Press, LLC", True), ("loc", "Ize Press", "Yen Press", True),
                          ("loc", "Yen Press", None, False), ("dnb", "Altraverse", "Altraverse GmbH", True),
                          ("dnb", "Carlsen", "Carlsen Verlag", True), ("dnb", "Carlsen Manga!", "Carlsen", True),
                          ("bnf", "Éd. Ki-oon", "Ki-oon", True), ("bnf", "Kbooks", "Delcourt-Kbooks", True),
                          ("loc", "Press", "Press", False)):
    t4 = _id("rl_", src + ":1")
    K4o = KI.read_carry(carry_file("o-r4", [(t4, "w", "Name", "manhwa", "en", Ao)], ["w"], {t4: src}, pubs={t4: cp}))
    ln4 = bl(src + ":9", src, "Name", Ao[:1], bp)
    KI.line_ids([ln4], K4o)
    eq("R4: publisher family %s %r vs %r (%r / %r) -> takes T: %s" % (src, cp, bp, KI.FAMILY[src](cp), KI.FAMILY[src](bp or ""), want),
       ln4["tome_id"] == t4, want)
tTo, So = M("loc:100"), M("loc:300")
b1o = [bl("loc:100", "loc", "Tower", Ao[:4], YEN), bl("loc:300", "loc", "Tower", [("5", Ao[4][1])], "Ize Press")]
orig("R5 build 1: the keeper holds 4, a same-name same-family 1-ISBN part mints its own key",
     KI.read_carry(carry_file("o-r5a", [(tTo, "w", "Tower", "manhwa", "en", Ao)], ["w"], {tTo: "loc"}, pubs={tTo: YEN})),
     b1o, {"loc:100": tTo, "loc:300": M("loc:300")}, [])
orig("R5 build 2: stable on build 1's carry",
     KI.read_carry(carry_file("o-r5b", [(tTo, "w", "Tower", "manhwa", "en", Ao[:4]), (So, "w", "Tower", "manhwa", "en", Ao[4:])], ["w"],
                              {tTo: "loc", So: "loc"}, ints={tTo: 10, So: 20}, pubs={tTo: YEN, So: "Ize Press"})),
     b1o, {"loc:100": tTo, "loc:300": So}, [])
orig("R5b build 2 with no publishers: stable",
     KI.read_carry(carry_file("o-r5c", [(tTo, "w", "Tower", "manhwa", "en", Ao[:4]), (So, "w", "Tower", "manhwa", "en", Ao[4:])], ["w"],
                              {tTo: "loc", So: "loc"}, ints={tTo: 10, So: 20})),
     [bl("loc:100", "loc", "Tower", Ao[:4]), bl("loc:300", "loc", "Tower", [("5", Ao[4][1])])],
     {"loc:100": tTo, "loc:300": So}, [])
orig("R6: the true line holds vol 3 only, a lower-key same-publisher stray holds vol 1 -> the true line keeps T, the stray mints",
     KI.read_carry(carry_file("o-r6", [(tAo, "w", "Rebirth", "manhwa", "en", Ao)], ["w"], {tAo: "loc"}, pubs={tAo: YEN})),
     [bl("loc:100", "loc", "Rebirth", [("3", Ao[2][1])], YEN), bl("loc:050", "loc", "Rebirth", [("1", Ao[0][1]), ("2", "9783333300002")], YEN)],
     {"loc:100": tAo, "loc:050": M("loc:050")}, [])

# ---- Task 11: adoption / rename / existing_lines ----------------------------------------------------------
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


# minor 2: adopt_line never makes a line its own parent
db3 = schema_db()
db3.execute("INSERT INTO work VALUES('w_3','T',NULL,NULL,NULL,NULL,'x','x')")
for rid in ("rl_i3", "rl_p3", "rl_c3"):
    line_row(db3, rid, "w_3", "manhwa", "EN", "en")
db3.execute("UPDATE release_line SET parent_id='rl_i3' WHERE id IN ('rl_p3','rl_c3')")
KI.adopt_line(db3.cursor(), "rl_i3", "rl_p3")
eq("minor 2: adopt_line: the public line is not its own parent; the internal line's other child follows it",
   sorted(db3.execute("SELECT id, parent_id FROM release_line")), [("rl_c3", "rl_p3"), ("rl_p3", None)])

# ---- Task 12: 3f decisions -------------------------------------------------------------------------------
import build_krcn as BK


def mkline(key, market, name, medium="manhwa", explicit=True, comic=True, carried=False, tome_id=None, **kw):
    ln = {"key": key, "source": key.split(":")[0], "market": market, "language": market.lower(), "name": name,
          "titles": [name], "orig": [], "native": [], "authors": [], "medium": medium, "medium_why": None,
          "origin": "kor", "explicit": explicit, "comic": comic, "vols": [{"number": "1", "isbns": []}],
          "carried": carried, "tome_id": tome_id or _id("rl_", key), "absorbed_ids": []}
    ln.update(kw)
    return ln


db = schema_db()
for wid, title in (("w_kr", "Solo Leveling"), ("w_rae", "Why Raeliana Ended Up at the Duke's Mansion"),
                   ("w_ouro", "Ouroboros"), ("w_nov", "Some Korean Novel"), ("w_wiki", "Lover Boy")):
    db.execute("INSERT INTO work VALUES(?,?,NULL,NULL,NULL,NULL,'x','x')", (wid, title))
line_row(db, "rl_kr", "w_kr", "manhwa", "EN", "en")
line_row(db, "rl_rae", "w_rae", "manhwa", "EN", "en")
line_row(db, "rl_ouro", "w_ouro", "manga", "JP", "ja")
line_row(db, "rl_nov", "w_nov", "novel", "KR", "ko")
line_row(db, "rl_wiki", "w_wiki", "manhwa", "EN", "en")
idx = L.Index(db)
NO_K = None
ls = [mkline("dnb:1", "DE", "Solo Leveling"),                                 # links to an existing KR/CN work
      mkline("dnb:2", "DE", "Ouroboros"),                                     # JP-only work: guard
      mkline("loc:2023000001", "EN", "Men of the Harem"),                      # EN + DE: a new work
      mkline("dnb:3", "DE", "Men of the Harem"),
      mkline("dnb:4", "DE", "Gänseblümchenwiese"),                             # DE only: a new work (the lift)
      mkline("dnb:5", "DE", "Raeliana"),                                      # containment -> review
      mkline("loc:2024000002", "EN", "The Star Seekers", explicit=False),     # Ize-only: no explicit origin
      mkline("loc:2024000003", "EN", "Finding Camellia", medium=None, ize=True),  # Ize medium unresolved
      mkline("dnb:6", "DE", "Some Korean Novel", medium="novel", comic=False),  # novel linked, work has no comic
      mkline("bnf:ark:/12148/cb10000001x", "FR", "Kkk Link", link_work=None)]
plan = BK.decide(ls, idx, NO_K, link_work={"bnf:ark:/12148/cb10000001x": "w_kr"}, comic_works={"w_kr", "w_rae", "w_wiki"})
role = {l["key"]: (l["role"], l["work"], l["reason"]) for l in ls}
eq("linked to the existing KR/CN work", role["dnb:1"][:2], ("linked", "w_kr"))
eq("JP guard: Ouroboros -> review", role["dnb:2"][::2], ("review", "jp-guard"))
w_new = _id("w_", "krcn", "loc:2023000001")
eq("EN + DE cluster: a new work keyed krcn|<EN key>; the DE line ships in it",
   (role["loc:2023000001"][:2], role["dnb:3"][:2], plan["works"][w_new]["created"]),
   (("new_work", w_new), ("new_work", w_new), True))
# the lift (2026-10-01): a DE-only comic cluster is a work anchored on its DE line; only the novel is held
w_de = _id("w_", "krcn", "dnb:4")
eq("DE-only cluster: a new work keyed krcn|<its DE key>, titled with the DE name; only the novel is held",
   (role["dnb:4"], plan["works"][w_de]["anchor"], plan["works"][w_de]["title"], [h["lines"] for h in plan["held"]]),
   (("new_work", w_de, None), "dnb:4", "Gänseblümchenwiese", [["dnb:6"]]))
eq("containment guard: 'Raeliana' is inside the existing work's title -> review", role["dnb:5"][::2], ("review", "containment"))
eq("no explicit origin (imprint only): unlinked, not held (P16)", role["loc:2024000002"][::2], ("unlinked", "no-explicit-origin"))
eq("Ize medium unresolved -> review", role["loc:2024000003"][::2], ("review", "ize-medium"))
eq("a novel line under a work without a comic line -> held", role["dnb:6"][::2], ("held", "novel-without-comic"))
eq("link_work correction wins (R2)", role["bnf:ark:/12148/cb10000001x"][:2], ("linked", "w_kr"))
eq("exported flags follow the roles", sorted(l["key"] for l in ls if l["exported"]),
   ["bnf:ark:/12148/cb10000001x", "dnb:1", "dnb:3", "dnb:4", "loc:2023000001"])
eq("created works join the KR/CN set", w_new in idx.krcn_works, True)
eq("R6: no held line is exported or has a work; no held line is in a work of the plan",
   ([(l["exported"], l["work"]) for l in ls if l["role"] == "held"],
    sorted(k for e in plan["works"].values() for k in e["lines"] if role[k][0] == "held")), ([(False, None)], []))
eq("R6: a held entry names its member keys and reason (the hold file; novel-without-comic is the one reason left)",
   {k: plan["held"][0][k] for k in ("reason", "markets", "members")}, {"reason": "novel-without-comic", "markets": ["DE"],
                                                                        "members": []})
eq("review keys", sorted(plan["review"]), ["dnb:2", "dnb:5", "loc:2024000003"])

# frozen through the carry, adoption (R1)
K = {"works": {"w_libA", "w_libB"}, "lines": {"rl_A": "loc", "rl_B": "dnb"}, "series_ids": {"rl_A", "rl_B", "rl_wiki"},
     "work_ids": {"w_libA", "w_libB", "w_wiki"}, "int": {"rl_A": 7, "rl_B": 30, "rl_wiki": 20},
     "line_work": {"rl_A": "w_libA", "rl_B": "w_libB", "rl_wiki": "w_wiki"}, "line_name": {}, "line_medium": {"rl_B": "manhwa"},
     "line_vols": {}}
idx = L.Index(db)
ls = [mkline("dnb:9", "DE", "Tempel der Sterne", carried=True, tome_id="rl_B"),     # its EN line is gone
      mkline("loc:2021000009", "EN", "Lover Boy", carried=True, tome_id="rl_A")]      # Wikipedia now has the work
plan = BK.decide(ls, idx, K, comic_works={"w_wiki"})
role = {l["key"]: (l["role"], l["work"]) for l in ls}
eq("frozen: a carried library work keeps exporting without an English line (never demoted)", role["dnb:9"], ("new_work", "w_libB"))
eq("adoption: the Wikipedia work w_wiki (published, int 20) meets library w_libA (int 7): the older id is public",
   (plan["adopt_works"], role["loc:2021000009"]), ([("w_wiki", "w_libA")], ("linked", "w_libA")))
g = BK.gate_report(ls, plan, {"taken": [], "taken_weak": [], "left": []}, K)
eq("gate: a published Wikipedia work redirected by adoption is listed (spec-sanctioned, but gated)",
   g["work_redirects"], [["w_wiki", "w_libA", "adopted"]])
eq("gate: an adoption rename is not a carried line changing work", g["carried_work_changed"], [])
K["int"]["rl_A"] = 99
ls = [mkline("loc:2021000009", "EN", "Lover Boy", carried=True, tome_id="rl_A")]
plan = BK.decide(ls, L.Index(db), K, comic_works={"w_wiki"})
eq("adoption: when the Wikipedia work is older it keeps its id (7b redirects the library id)",
   (plan["adopt_works"], ls[0]["work"]), ([], "w_wiki"))
eq("gate: ... and the carried line that moved from its library work to w_wiki is listed",
   BK.gate_report(ls, plan, {}, K)["carried_work_changed"], [["rl_A", "loc:2021000009", "w_libA", "w_wiki", "linked"]])
eq("cluster keys: a romanised original keys within its source only",
   sorted(BK.cluster_keys(mkline("dnb:1", "DE", "Raeliana", orig=["Eo neu nal gong ju"])))[:2],
   [("o", "dnb", "eoneunalgongju"), ("t", "raeliana")])
eq("cluster keys: Hangul 2 syllables admitted, Latin under 5 not",
   BK.cluster_keys(mkline("dnb:1", "DE", "Kiss", native=["괴물"])), {("t", "괴물")})
eq("clusters: a romanised original joins lines of one library, never across libraries",
   [[l["key"] for l in c] for c in BK.clusters([mkline("dnb:1", "DE", "Tempel", orig=["Tem ppal"]),
                                               mkline("dnb:2", "DE", "Overgeared", orig=["Tem ppal"]),
                                               mkline("bnf:x1", "FR", "Forgeron", orig=["Tem ppal"])])],
   [["bnf:x1"], ["dnb:1", "dnb:2"]])

# the frozen path also merges two published library works of one cluster into the older (7b redirects the other)
K2f = {"works": {"w_L1", "w_L2"}, "lines": {"rl_1": "dnb", "rl_2": "loc"}, "series_ids": {"rl_1", "rl_2"},
       "work_ids": {"w_L1", "w_L2"}, "int": {"rl_1": 50, "rl_2": 40}, "line_work": {"rl_1": "w_L1", "rl_2": "w_L2"},
       "line_name": {}, "line_medium": {}, "line_vols": {}}
ls = [mkline("dnb:11", "DE", "Sternentempel", carried=True, tome_id="rl_1"),
      mkline("loc:11", "EN", "Sternentempel", carried=True, tome_id="rl_2")]
plan = BK.decide(ls, L.Index(db), K2f)
eq("frozen merge: two published library works in one cluster -> the older (w_L2); the other listed for 7b",
   ([l["work"] for l in ls], BK.gate_report(ls, plan, {}, K2f)["work_redirects"]),
   (["w_L2", "w_L2"], [["w_L1", "w_L2", "frozen-merge"]]))

# adoption conflict: a Wikipedia work adopts a library work that a frozen cluster of this build also exports
K2c = {"works": {"w_libA"}, "lines": {"rl_A": "loc", "rl_A2": "dnb"}, "series_ids": {"rl_A", "rl_A2"},
       "work_ids": {"w_libA"}, "int": {"rl_A": 7, "rl_A2": 8}, "line_work": {"rl_A": "w_libA", "rl_A2": "w_libA"},
       "line_name": {}, "line_medium": {}, "line_vols": {}}
ls = [mkline("loc:2021000009", "EN", "Lover Boy", carried=True, tome_id="rl_A"),
      mkline("dnb:12", "DE", "Liebesjunge", carried=True, tome_id="rl_A2")]
plan = BK.decide(ls, L.Index(db), K2c, comic_works={"w_wiki"})
eq("adoption conflict (rename_work onto a work 3f also exports): detected and gated, not resolved",
   (plan["adopt_works"], plan["adopt_conflicts"], BK.gate_report(ls, plan, {}, K2c)["adopt_conflicts"]),
   ([("w_wiki", "w_libA")], [("w_wiki", "w_libA")], [["w_wiki", "w_libA"]]))

# review reasons from the line builder (controller ruling): medium_why verbatim, attached or not; link_work ships a guess
db4 = schema_db()
db4.execute("INSERT INTO work VALUES('w_ot','Under the Oak Tree',NULL,NULL,NULL,NULL,'x','x')")
line_row(db4, "rl_ot", "w_ot", "manhwa", "EN", "en")
ls = [mkline("dnb:21", "DE", "Under the Oak Tree", medium=None, medium_why="duplicate_numbers", medium_guess="novel"),
      mkline("loc:21", "EN", "Under the Oak Tree", medium=None, medium_why="duplicate_numbers+both"),
      mkline("dnb:22", "DE", "Radio Storm", medium=None, medium_why="writer_only", medium_guess="manhwa"),
      mkline("dnb:23", "DE", "Radio Storm Zwei", medium=None, medium_why="writer_only", medium_guess="manhwa",
             role="merged", target="rl_ot", work="w_ot"),
      mkline("loc:22", "EN", "Oak Tree Zwei", medium=None, ize=True, role="sibling", target="rl_ot", work="w_ot"),
      mkline("loc:23", "EN", "Heavenly Kiss", medium=None, medium_why="both")]
plan = BK.decide(ls, L.Index(db4), None, link_work={"dnb:22": "w_ot", "loc:23": "w_ot"}, comic_works={"w_ot"},
                 line_medium={"rl_ot": "manhwa"})
got = {l["key"]: (l["role"], l["reason"], l["medium"]) for l in ls}
eq("review reason = medium_why verbatim ('+'-joined), even when the title links",
   (got["dnb:21"], got["loc:21"]), (("review", "duplicate_numbers", None), ("review", "duplicate_numbers+both", None)))
eq("an attached writer-only line stays in review (not auto-exported)", got["dnb:23"], ("review", "writer_only", None))
eq("an attached Ize line with no review reason takes its target's medium class", got["loc:22"], ("sibling", None, "manhwa"))
eq("link_work ships a writer-only line with its medium_guess", got["dnb:22"], ("linked", None, "manhwa"))
eq("link_work cannot ship a 'both' line (no guess): it stays in review", got["loc:23"], ("review", "both", None))

# ruling: a line that took a carried id mints its volume ids from that id (v_(tome_id, number))
Kv = KI.read_carry(carry_file("t12v", [("rl_pub", "w_lib", "Semantic error", "manhwa", "en", I5)],
                              works=["w_lib"], krcn_lines={"rl_pub": "loc"}))
lv = bl("loc:2022000009", "loc", "Semantic error", I5)
repv = KI.line_ids([lv], Kv)
eq("a line that took a carried id mints its volumes under it, not under its own key",
   (repv["taken"], BK.vol_id(lv, "3")), ([("rl_pub", "loc:2022000009")], _id("v_", "rl_pub", "3")))

# P25: a DNB line the JP round mints is deferred before ids; reserved ids refuse it anyway
jp_rows = [("dnb:997592818", "rl_d63204b2411c"), ("dnb:5", "rl_x5")]
keep_, deferred_, reserved_ = BK.defer_jp_round([mkline("dnb:997592818", "DE", "King of Hell"), mkline("dnb:31", "DE", "X")],
                                                jp_rows)
eq("P25: King of Hell's German line stays with the JP round; reserved = the JP keys' ids + rl_ids",
   ([l["key"] for l in keep_], [l["key"] for l in deferred_], reserved_ >= {_id("rl_", "dnb:997592818"), "rl_d63204b2411c", "rl_x5"}),
   (["dnb:31"], ["dnb:997592818"], True))
try:
    KI.line_ids([bl("dnb:997592818", "dnb", "King of Hell", [])], None, reserved=reserved_)
    eq("line_ids refuses a JP-round key", "no error", "AssertionError")
except AssertionError:
    eq("line_ids refuses a JP-round key", True, True)

# gate lists (controller ruling): taken_weak, left, step-1 keeps with 0 ISBN overlap, weak absorptions, P22 thin
Kg = KI.read_carry(carry_file("t12g", [("rl_T", "w_g", "Rebirth", "manhwa", "en", I5),
                                       ("rl_U", "w_g", "Other", "manhwa", "en", [("1", "9790000000011")]),
                                       ("rl_V", "w_g", "Gone", "manhwa", "en", [("1", "9790000000021")]),
                                       ("rl_W", "w_wg", "Wiki line", "manhwa", "en", I10),
                                       ("rl_Y", "w_g", "One shot", "manhwa", "en", [("1", I10[0][1])])],
                              works=["w_g"], krcn_lines={"rl_T": "loc", "rl_U": "loc", "rl_V": "loc", "rl_Y": "loc"},
                              ints={"rl_T": 5, "rl_U": 6, "rl_V": 7, "rl_W": 90, "rl_Y": 3}, pubs={"rl_T": YEN}))
gl = [bl("loc:500", "loc", "Rebirth", [I5[0]], "Ize Press"),                      # takes rl_T via (b), 1 of 5: weak
      dict(bl("loc:600", "loc", "Other", [("1", "9790000000099")]), key="loc:600"),  # own key carried below, 0 overlap
      bl("loc:700", "loc", "One shot", [("1", I10[0][1])])]
gl[1]["key"] = "loc:600"
Kg["series_ids"].add(M("loc:600"))
Kg["line_vols"][M("loc:600")] = [("1", "9790000000011")]
Kg["line_work"][M("loc:600")] = "w_g"
repg = KI.line_ids(gl, Kg)
for l in gl:
    l.update(role="linked", work="w_g", exported=True, reason=None, via="title", tier="medium", link_work="w_g",
             authors=[], target=None)
# a carried one-volume library line adopting the 10-volume carried Wikipedia line rl_W (P22's 2*1 >= min(1, 10))
yl = dict(bl("loc:800", "loc", "One shot", [("1", I10[0][1])]), tome_id="rl_Y", carried=True, absorbed_ids=[],
          role="adopting", target="rl_W", work="w_wg", exported=True, reason=None, via="isbn", tier=None,
          link_work=None, authors=["박"])
gg = BK.gate_report(gl + [yl], {"adopt_works": [], "works": {}}, repg, Kg)
eq("gate: taken_weak and left from line_ids", (gg["taken_weak"], gg["left"]),
   ([["rl_T", "loc:500", 1, 5]], ["rl_U", "rl_V", "rl_Y"]))     # loc:700: 1 ISBN, no publisher -> no take
eq("gate: a step-1 keep sharing 0 ISBNs with its carried line", gg["kept_no_overlap"],
   [[M("loc:600"), "loc:600", 0, 1, 1]])
eq("gate: a carried Wikipedia line's id absorbed by a one-volume adopting line: absorbed_weak + p22_thin",
   (gg["absorbed_weak"], gg["p22_thin"]), ([["rl_W", "rl_Y", "adopting", 1, 10]], [["rl_Y", "loc:800", "rl_W", 10]]))
eq("gate: a line with Hangul-only creator names has no author evidence", gg["hangul_only_authors"], [["loc:800", "adopting", ["박"]]])
yl.update(role="review", exported=False, work=None, reason="low")
eq("gate: a published line that does not export is listed", BK.gate_report([yl], {}, {}, Kg)["carried_not_exported"],
   [["rl_Y", "loc:800", "review", "low"]])

# ruling 5, deferred fixture checks (recorded behaviour; Task 15's fixture labels them)
db5 = schema_db()
for wid, title in (("w_3b", "The Three-Body Problem"), ("w_orv", "Omniscient Reader's Viewpoint")):
    db5.execute("INSERT INTO work VALUES(?,?,NULL,NULL,NULL,NULL,'x','x')", (wid, title))
line_row(db5, "rl_3b", "w_3b", "manhua", "EN", "en")
line_row(db5, "rl_orv", "w_orv", "manhwa", "EN", "en")
db5.execute("""INSERT INTO claim VALUES('work','w_3b','author','["Liu Cixin"]','wikipedia',NULL,'facts_only','x')""")
db5.execute("""INSERT INTO claim VALUES('work','w_orv','author','["Sing Shong"]','wikipedia',NULL,'facts_only','x')""")
idx5 = L.Index(db5)
ls = [mkline("loc:2024000050", "EN", "The three-body problem : the comic edition",
             titles=["The three-body problem : the comic edition"], authors=["Liu, Cixin"], origin="chi"),
      mkline("dnb:51", "DE", "Omniscient Reader's Viewpoint", authors=["싱숑"]),
      mkline("dnb:52", "DE", "Omniscient Reader's Viewpoint", authors=["Sing, Syong"]),
      mkline("dnb:53", "DE", "Allwissender Leser", orig=["Chŏnjijŏk tokcha sijŏm"])]
BK.decide(ls, idx5, None, comic_works={"w_3b", "w_orv"})
got = {l["key"]: (l["role"], l["tier"], l["via"], l["work"]) for l in ls}
eq("fixture check: LoC 'The three-body problem : the comic edition' links LOW (spinoff+author) -> review",
   got["loc:2024000050"], ("review", "low", "spinoff+author", None))
eq("fixture check: a Hangul-only creator name gives no author evidence -> title-only (medium)",
   got["dnb:51"], ("linked", "medium", "title", "w_orv"))
eq("fixture check: a romanisation variant of the creator (Sing Syong vs Sing Shong) is a collision -> low, review",
   got["dnb:52"], ("review", "low", "title, authors differ", None))
eq("fixture check: an MR original title (Chŏnjijŏk tokcha sijŏm) keys nothing against RR/English titles -> linker none (DE only: a new work)",
   got["dnb:53"][:2], ("new_work", "none"))


# ---- Task 12 controller rulings (pre-review): the anchor is an English COMIC line; LoC imprint series ----------
db6 = schema_db()
idx6 = L.Index(db6)
ls = [mkline("loc:2025033006", "EN", "Semantic error", medium="novel", comic=False),     # the Ize novel record
      mkline("dnb:1362777552", "DE", "Semantic error", medium="novel", comic=False),
      mkline("dnb:1369956126", "DE", "Semantic error")]                                   # the DE comic
plan = BK.decide(ls, idx6, None)
w_se = _id("w_", "krcn", "dnb:1369956126")
eq("Semantic Error (c0292): an EN novel and a DE comic -> a work anchored on the DE COMIC line (the novel has the lower "
   "key); the EN novel ships in it as new_work; nothing held",
   ([(l["role"], l["work"]) for l in ls], plan["works"][w_se]["anchor"], plan["held"]),
   ([("new_work", w_se)] * 3, "dnb:1369956126", []))
ls = [mkline("loc:2025000001", "EN", "Dark moon", medium="novel", comic=False),
      mkline("loc:2025000002", "EN", "Dark moon")]
plan = BK.decide(ls, idx6, None)
eq("an English comic line anchors the work even when an English novel line has the lower key",
   (list(plan["works"]), plan["works"][_id("w_", "krcn", "loc:2025000002")]["anchor"]),
   ([_id("w_", "krcn", "loc:2025000002")], "loc:2025000002"))


def dd(cid, lccn, title, s490, isbn):
    return lrec("01000cam a2200000 i 4500", "720302s1972    nyu           000 1 eng  ", ("010", [("a", lccn)]),
                ("020", [("a", isbn)]), DLC, ("041", [("a", "eng"), ("h", "chi")]), ("082", [("a", "741.5")]),
                ("245", [("a", title)]), ("264", [("b", "Doubleday,")]), ("490", s490), VOL338, cid=cid)


# spike cache f6a8890ec5bdf5ffe5f71c0df5a118ef.xml, LCCN 72076226 (trimmed): 490 'A Doubleday Anchor original ; AO-44'
DA = dd("da", "  72076226", "The people's comic book", [("a", "A Doubleday Anchor original ;"), ("v", "AO-44")], isbn13("97803", 1))
DB = dd("db", "  72076227", "Another comic book", [("a", "A Doubleday Anchor original ;"), ("v", "AO-45")], isbn13("97803", 2))
DC = dd("dc", "  72076228", "A third comic", [("a", "An imprint collection")], isbn13("97803", 3))
lines, _, _ = KL.loc_lines({r["cf"]["001"]: r for r in (DA, DB, DC)})
eq("LoC: a publisher series numbered by catalogue code (490 $v AO-44) is neither series key nor name nor title",
   sorted((l["name"], "A Doubleday Anchor original" in l["titles"]) for l in lines),
   [("A third comic", False), ("Another comic book", False), ("The people's comic book", False)])
MSD = [dd("m%d" % n, "  202401705%d" % n, "Mystery science detectives. %d" % n,
          [("a", "Mystery science detectives ;"), ("v", v)], isbn13("97813", n)) for n, v in ((1, "book 2"), (2, "#5"))]
lines, _, _ = KL.loc_lines({r["cf"]["001"]: r for r in MSD})
eq("LoC: a real series ($v 'book 2', '#5') still names and keys the line", [l["name"] for l in lines],
   ["Mystery science detectives"])


# ---- Task 12 review fixes -------------------------------------------------------------------------------------
# 1. a catalogue-coded 490 $v numbers nothing: the one-shot rule gives "1" (Doubleday AO-44, Evergreen E-209, FA259)
EV = dd("ev", "  60006341", "The book of songs", [("a", "An Evergreen book,"), ("v", "E-209")], isbn13("97803", 4))
FA = dd("fa", "  60006342", "Songs of the south", [("a", "A Grove Press book ;"), ("v", "FA259")], isbn13("97803", 5))
lines, _, _ = KL.loc_lines({r["cf"]["001"]: r for r in (DA, EV, FA)})
eq("a catalogue-coded $v never numbers a volume (AO-44, E-209 not '209', unhyphenated FA259): one-shots are vol 1",
   sorted((l["name"], [v["number"] for v in l["vols"]]) for l in lines),
   [("Songs of the south", ["1"]), ("The book of songs", ["1"]), ("The people's comic book", ["1"])])
eq("CATALOGUE_V: codes yes; volume words / numbers no",
   [bool(KL.CATALOGUE_V.match(v)) for v in ("AO-44", "E-209", "FA259", "FA259.", "3", "v. 3", "Book 1", "Vol. 5", "#5",
                                            "Volume 23", "omnibus")],
   [True, True, True, True, False, False, False, False, False, False, False])

# 2. krcn_line.rl_id: the tome_id only when the line exports (R6 / §13: a held line holds no id anywhere)
db7 = schema_db()
db7.executescript(BK.STAGING_DDL)
db7.execute("INSERT INTO krcn_line(key,source,market,rl_id,carried,role,exported) VALUES('dnb:4','dnb','DE',NULL,0,'held',0)")
hl = mkline("dnb:4", "DE", "Gänseblümchenwiese", role="held", exported=False)
el = mkline("dnb:1", "DE", "Solo Leveling", role="linked", exported=True)
eq("staged_rl_id: NULL for a held line, the tome_id for an exported one; the DDL takes a NULL rl_id",
   (BK.staged_rl_id(hl), BK.staged_rl_id(el), db7.execute("SELECT rl_id FROM krcn_line").fetchone()[0]),
   (None, _id("rl_", "dnb:1"), None))

# 3. link_work override_jp_guard (controller ruling): only a correction that says so, with a why, lifts the guard
db8 = schema_db()
db8.execute("INSERT INTO work VALUES('w_72a76ed32ef2','Kurokami',NULL,NULL,NULL,NULL,'x','x')")
line_row(db8, "rl_kuro", "w_72a76ed32ef2", "manga", "JP", "ja")
for ov, want in (({}, ("review", "jp-guard", None, "correction")),
                 ({"loc:2008270303": "Korean creators, first published in Japan"},
                  ("linked", None, "w_72a76ed32ef2", "correction+override_jp_guard"))):
    ls = [mkline("loc:2008270303", "EN", "Black god")]
    plan = BK.decide(ls, L.Index(db8), None, link_work={"loc:2008270303": "w_72a76ed32ef2"}, jp_override=ov)
    eq("Black God -> Kurokami (JP only): %s" % ("override with a why: linked, listed" if ov else "no override: review"),
       (ls[0]["role"], ls[0]["reason"], ls[0]["work"], ls[0]["via"]), want)
eq("gate: the override is listed (line key, work, why)", BK.gate_report(ls, plan, {}, None)["jp_guard_overrides"],
   [["loc:2008270303", "w_72a76ed32ef2", "Korean creators, first published in Japan"]])
ls = [mkline("loc:2008270303", "EN", "Black god", titles=["Black god", "Kurokami"])]
BK.decide(ls, L.Index(db8), None, jp_override={"loc:2008270303": "x"})
eq("an override without a link_work correction lifts nothing (the linker's own JP-guard verdict stays)",
   (ls[0]["role"], ls[0]["reason"]), ("review", "jp-guard"))

# 4a. review reasons are '+'-joined, never overwritten
ls = [mkline("dnb:2", "DE", "Ouroboros", medium=None, medium_why="writer_only", medium_guess="manhwa"),
      mkline("loc:2024000099", "EN", "Some Title", medium=None, ize=True)]
BK.decide(ls, L.Index(db), None)                     # db: the Task 12 catalogue (Ouroboros JP-only)
ls2 = [mkline("bnf:x9", "FR", "Buster", medium=None, medium_why="duplicate_numbers", medium_guess="manhwa")]
db9 = schema_db()
db9.execute("INSERT INTO work VALUES('w_bu','Buster Keaton',NULL,NULL,NULL,NULL,'x','x')")
db9.execute("INSERT INTO work_title VALUES('w_bu','en','Buster','alias')")
line_row(db9, "rl_bu", "w_bu", "manhwa", "EN", "en")
BK.decide(ls2, L.Index(db9), None)
eq("reasons joined: jp-guard+writer_only; low (alias)+duplicate_numbers; an unlinked Ize line: ize-medium",
   (ls[0]["reason"], ls2[0]["reason"], ls[1]["reason"]), ("jp-guard+writer_only", "low+duplicate_numbers", "ize-medium"))

# 4b. a novel-without-comic held entry carries criteria 1-4
ls = [mkline("dnb:6", "DE", "Some Korean Novel", medium="novel", comic=False)]
plan = BK.decide(ls, L.Index(db), None, comic_works={"w_kr"})
eq("novel-without-comic held entry: linker tier, explicit origin, comic, containment, the work",
   plan["held"][0]["criteria"], {"linker": "medium", "explicit_origin": True, "comic": False, "containment": ["w_nov"],
                                  "novel_without_comic": ["w_nov"]})

# 4c. works created in one build guard each other (containment, in cluster key order)
ls = [mkline("loc:2023000011", "EN", "Men of the Harem"),
      mkline("loc:2023000012", "EN", "Men of the Harem Side Stories")]
plan = BK.decide(ls, L.Index(schema_db()), None)
wA = _id("w_", "krcn", "loc:2023000011")
eq("a later cluster whose title contains a work created earlier in this build -> review containment",
   (ls[0]["role"], ls[1]["role"], ls[1]["reason"], ls[1]["candidates"]), ("new_work", "review", "containment", [wA]))

# 4d. a pooled cluster sharing a key with a line linked to a work goes to review with that work (Penelope / Villains)
db10 = schema_db()
db10.execute("INSERT INTO work VALUES('w_vil','Villains Are Destined to Die',NULL,NULL,NULL,NULL,'x','x')")
line_row(db10, "rl_vil", "w_vil", "manhwa", "EN", "en")
ls = [mkline("dnb:41", "DE", "Penelope - Das Böse ist dem Tod geweiht",
             titles=["Penelope - Das Böse ist dem Tod geweiht", "Villains are destined to die"]),
      mkline("dnb:42", "DE", "Penelope - Das Böse ist dem Tod geweiht", edition="Deluxe")]
BK.decide(ls, L.Index(db10), None)
eq("Penelope: the linked line ships; its same-title pooled sibling -> review 'linked-sibling-key' naming the work",
   [(l["role"], l["reason"], l["work"] if l["role"] == "linked" else l["candidates"]) for l in ls],
   [("linked", None, "w_vil"), ("review", "linked-sibling-key", ["w_vil"])])

# 4e. LoC 240 form titles never key a cluster
f1 = mkline("loc:2001000001", "EN", "The rainy spell", orig=["Short stories"], titles=["The rainy spell", "Poems. Selections"])
f2 = mkline("loc:2001000002", "EN", "Dust flowers", orig=["Short stories"])
eq("form titles ('Short stories', 'Poems. Selections') give no key; two collections stay two clusters",
   (sorted(k[-1] for k in BK.cluster_keys(f1)), len(BK.clusters([f1, f2]))), (["rainyspell"], 2))

# 4f. absorbed_weak, merged branch: a carried library line merged into an existing line holding 1 of its 5 ISBNs
Km = KI.read_carry(carry_file("t12m", [("rl_M", "w_m", "Merge me", "manhwa", "en", I5)], works=["w_m"],
                               krcn_lines={"rl_M": "loc"}))
ml = dict(bl("loc:900", "loc", "Merge me", I5), tome_id="rl_M", carried=True, absorbed_ids=[], role="merged",
          target="rl_x9", work="w_x", exported=True, reason=None, via="isbn", tier=None, link_work=None, authors=[])
Em = {"rl_x9": {"work": "w_x", "medium": "manhwa", "vols": {"1": ("v1", I5[0][1]), "2": ("v2", "9790000000777")}}}
eq("gate: a carried library line merged into an existing line holding 1 of its 5 ISBNs -> absorbed_weak",
   BK.gate_report([ml], {}, {"taken": []}, Km, Em)["absorbed_weak"], [["rl_M", "rl_x9", "merged", 1, 5]])
Em["rl_x9"]["vols"].update({n: ("v" + n, i) for n, i in I5})
eq("gate: ... not when the existing line holds a strict majority (5 of 5)",
   BK.gate_report([ml], {}, {"taken": []}, Km, Em)["absorbed_weak"], [])

# ---- Task 13: licence, clean view, meta for the export, publish refusal ----------------------------
import subprocess, shutil
from load import LICENCE
eq("LoC licence label", LICENCE.get("loc"), "us_gov_pd")
db = schema_db()
db.execute("INSERT INTO claim VALUES('volume','v1','isbn13','9781975319434','loc','https://lccn.loc.gov/2020950228','us_gov_pd','x')")
eq("clean_claim lists us_gov_pd (a new label must not fall OUT of the commercial subset)",
   db.execute("SELECT COUNT(*) FROM clean_claim WHERE source='loc'").fetchone()[0], 1)

# record_meta / krcn_ids (controller rulings 1 and 3): what the export copies
db.executescript(BK.STAGING_DDL)
db.execute("""INSERT INTO meta VALUES('dnb:degraded','{"reason": "HTTP 502", "kept_previous": ["jp q"]}')""")
_ln = lambda key, src, tid, role, work: {"key": key, "source": src, "tome_id": tid, "role": role, "work": work,
                                         "exported": role in BK.EXPORTED}
m_lines = [_ln("loc:1", "loc", "rl_n", "new_work", "w_new"), _ln("bnf:2", "bnf", "rl_s", "new_work", "w_new"),
           _ln("dnb:3", "dnb", "rl_l", "linked", "w_wiki"), _ln("dnb:4", "dnb", "rl_m", "merged", "w_wiki"),
           _ln("loc:5", "loc", "rl_h", "held", None), _ln("dnb:6", "dnb", "rl_k", "kept", "w_pub"),
           _ln("loc:7", "loc", "rl_a", "linked", "w_old")]
m_plan = {"works": {"w_new": {"created": True}, "w_pub": {"created": False}, "w_quiet": {"created": True}},
          "adopt_works": [("w_wiki2", "w_old")]}
eq("krcn_ids: library works that ship (created, frozen, adopted public ids), the created ones, "
   "exported library-born lines (not merged, not held)",
   BK.krcn_ids(m_lines, m_plan),
   {"works": ["w_new", "w_old", "w_pub"], "created": ["w_new"],
    "lines": {"rl_n": "loc", "rl_s": "bnf", "rl_l": "dnb", "rl_k": "dnb", "rl_a": "loc"}})
mv = lambda k: (db.execute("SELECT value FROM meta WHERE key=?", (k,)).fetchone() or [None])[0]
with contextlib.redirect_stdout(io.StringIO()):
    BK.record_meta(db, m_lines, m_plan, {
        "loc": {"degraded": "LadderExhausted: p", "degraded_queries": ["bath.isbn=97988554*"]},
        "bnf": {"degraded": None, "degraded_queries": []},
        "dnb": {"degraded": "URLError: t", "degraded_queries": ["spo=kor and jhr=2021"]}})
eq("record_meta: krcn:ids written", json.loads(mv("krcn:ids")), BK.krcn_ids(m_lines, m_plan))
eq("record_meta: a degraded LoC refresh -> loc:degraded {reason, kept_previous}", json.loads(mv("loc:degraded")),
   {"reason": "LadderExhausted: p", "kept_previous": ["bath.isbn=97988554*"]})
eq("record_meta: a clean BnF run writes no bnf:degraded", mv("bnf:degraded"), None)
eq("record_meta: KR/CN DNB degradation merges into 3e's dnb:degraded (3e's value kept)", json.loads(mv("dnb:degraded")),
   {"reason": "HTTP 502", "kept_previous": ["jp q"],
    "krcn": {"reason": "URLError: t", "kept_previous": ["spo=kor and jhr=2021"]}})
with contextlib.redirect_stdout(io.StringIO()):
    BK.record_meta(db, m_lines, m_plan, {"loc": {"degraded": None, "degraded_queries": []}, "dnb": {"degraded": None},
                                         "bnf": {"degraded": None, "degraded_queries": ["q1"]}})
eq("record_meta: a clean LoC run clears loc:degraded; an incomplete BnF set (queries, no reason) is degraded",
   (mv("loc:degraded"), json.loads(mv("bnf:degraded"))), (None, {"reason": "incomplete", "kept_previous": ["q1"]}))
eq("record_meta: a clean KR/CN DNB run never clears 3e's dnb:degraded", json.loads(mv("dnb:degraded"))["reason"], "HTTP 502")
db2 = schema_db()
with contextlib.redirect_stdout(io.StringIO()):
    BK.record_meta(db2, [], {}, {"dnb": {"degraded": "HTTPError: 503", "degraded_queries": ["spo=chi"]},
                                 "loc": {"degraded": None}, "bnf": {"degraded": None}})
eq("record_meta: KR/CN DNB degraded with 3e clean -> dnb:degraded of its own", json.loads(
   db2.execute("SELECT value FROM meta WHERE key='dnb:degraded'").fetchone()[0]),
   {"reason": "HTTPError: 503", "kept_previous": ["spo=chi"], "round": "krcn"})

for label, reps in (("a missing source report", {"LoC": {"degraded": "x"}, "bnf": {"degraded": None},
                                                  "dnb": {"degraded": None}}),
                    ("a report without its 'degraded' key", {"loc": {"degraded_queries": ["q"]},
                                                             "bnf": {"degraded": None}, "dnb": {"degraded": None}})):
    try:
        BK.record_meta(db2, [], {}, reps)
        eq("record_meta: %s raises (never a silent clean run)" % label, "no exception", "ValueError")
    except ValueError:
        eq("record_meta: %s raises (never a silent clean run)" % label, True, True)

# the single KR/CN licence gate (test_artifact.run_krcn_licence): per-source field allowlists, anchored
# urls, ark-only line sources, no library-hosted covers -- the reviewer's bypasses each fail it
import test_artifact as TART


def lic_gate(claims, cover=None, cover_source="openlibrary", staging=""):
    d = tempfile.mkdtemp(prefix="krcn-lic-", dir=os.path.join(ROOT, "build"))
    catp, artp = os.path.join(d, "cat.db"), os.path.join(d, "art.sqlite")
    C = sqlite3.connect(catp)
    C.executescript(open(os.path.join(ROOT, "schema", "schema.sql"), encoding="utf8").read())
    if staging:
        C.executescript(BK.STAGING_DDL + staging)
    base = [("volume", "v_ok", "isbn13", "9781975319434", "loc", "https://lccn.loc.gov/2020950228", "us_gov_pd"),
            ("volume", "v_d", "page_count", "192", "dnb", "https://d-nb.info/1234567890", "cc0"),
            ("volume", "v_b", "volume_number", "1", "bnf", "https://catalogue.bnf.fr/ark:/12148/cb47253773p", "open"),
            ("volume", "v_e", "page_count", "200", "bnf",
             "https://catalogue.bnf.fr/api/SRU?query=bib.isbn+all+%229782811600000%22", "open")]
    C.executemany("INSERT OR REPLACE INTO claim VALUES(?,?,?,?,?,?,?,'x')", base + list(claims))
    C.commit()
    A = sqlite3.connect(artp)
    A.executescript("""CREATE TABLE volumes (cover_url TEXT, cover_source TEXT); CREATE TABLE series (tome_id TEXT);
                       CREATE TABLE id_map (opentome_id TEXT, int_id INTEGER, kind TEXT);
                       CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);""")
    A.execute("INSERT INTO meta VALUES('attribution','... Library of Congress (US government work) ...')")
    if cover or cover_source != "openlibrary":
        A.execute("INSERT INTO volumes VALUES(?, ?)", (cover, cover_source))
    A.commit()
    n = len(TART.FAILS)
    with contextlib.redirect_stdout(io.StringIO()):
        TART.run_krcn_licence(artp, catp)
    got = TART.FAILS[n:]
    del TART.FAILS[n:]
    shutil.rmtree(d)
    return got


eq("licence gate: the clean base passes", lic_gate([]), [])
ALLOW = "dnb / loc / bnf claims outside the source's field allowlist"
eq("licence gate: a loc summary (520) fails the allowlist",
   lic_gate([("work", "w_1", "summary", "A story of...", "loc", "https://lccn.loc.gov/2020950228", "us_gov_pd")]), [ALLOW])
eq("licence gate: a dnb description (856 blurb) fails the allowlist",
   lic_gate([("volume", "v_d", "description", "Klappentext", "dnb", "https://d-nb.info/1234567890", "cc0")]), [ALLOW])
eq("licence gate: a dnb page_count cited to an /04 (cover / TOC) url fails the anchored DNB url",
   lic_gate([("volume", "v_d2", "page_count", "180", "dnb", "https://d-nb.info/1234567890/04", "cc0")]),
   ["dnb claims whose source_url is not https://d-nb.info/<IDN>"])
eq("licence gate: a bnf thumbnail '//...' fails the allowlist and the link-value rule",
   lic_gate([("volume", "v_b", "thumbnail", "//catalogue.bnf.fr/couverture?appName=NE&idArk=x", "bnf",
              "https://catalogue.bnf.fr/ark:/12148/cb47253773p", "open")]),
   [ALLOW, "dnb / loc / bnf claims whose value is a link"])
BNFU = "bnf claims whose source_url is not an ark URL (the per-ISBN lookup: enrichment only)"
eq("licence gate: a bnf line-source claim (isbn13) on the per-ISBN SRU url fails -- ark only",
   lic_gate([("volume", "v_b2", "isbn13", "9782811600001", "bnf",
              "https://catalogue.bnf.fr/api/SRU?query=bib.isbn+all+%229782811600001%22", "open")]), [BNFU])
eq("licence gate: ... and an SRU-cited page_count on an ark-sourced (line-source) volume fails",
   lic_gate([("volume", "v_b", "page_count", "150", "bnf",
              "https://catalogue.bnf.fr/api/SRU?query=bib.isbn+all+%229782811600002%22", "open")]), [BNFU])
COVER = "artifact covers from dnb / loc / bnf (source or host)"
for label, url, want in (("portal.dnb.de alone", "https://portal.dnb.de/opac/mvb/cover?isbn=9783753935874", [COVER]),
                         ("services.dnb.de alone", "https://services.dnb.de/fize-service/gvr/full.jpg?isbn=x", [COVER]),
                         ("d-nb.info alone", "https://d-nb.info/1234567890/04", [COVER]),
                         ("a non-library host (AniList)", "https://s4.anilist.co/file/anilistcdn/media/manga/cover/large/bx1.jpg", [])):
    eq("licence gate: artifact cover_url on %s (cover_source openlibrary)" % label, lic_gate([], cover=url), want)
eq("licence gate: an artifact cover_source 'DNB' (upper case) fails", lic_gate([], cover_source="DNB"), [COVER])
eq("licence gate: a 'DNB'-sourced description on an /04 url fails (source compared lowered)",
   lic_gate([("volume", "v_d3", "description", "Klappentext", "DNB", "https://d-nb.info/1234567890/04", "cc0")]),
   [ALLOW, "dnb claims whose source_url is not https://d-nb.info/<IDN>"])
eq("licence gate: a link embedded mid-string in a publisher fails the link-value rule",
   lic_gate([("release_line", "rl_d", "publisher", "Altraverse (see www.altraverse.de/manhwa)", "dnb",
              "https://d-nb.info/1234567890", "cc0")]), ["dnb / loc / bnf claims whose value is a link"])

# publish.sh refuses loc_degraded / bnf_degraded. publish.sh cd's to its repo root and writes
# build/version.json: run a copy (tier0/test_dnb.py's pattern). The artifact here is cold-start with
# OPENTOME_COLD_START=1, so the degraded flag is the ONLY refusal left: a stub `gh` first on PATH
# (it leaves a marker and fails), GH_TOKEN removed and a dummy REPO / TAG make sure a broken refusal
# can never reach the real release.
pub = tempfile.mkdtemp(prefix="krcn-pub-")
for d_ in ("build", "export", "fakebin"):
    os.makedirs(os.path.join(pub, d_))
shutil.copy(os.path.join(ROOT, "export", "publish.sh"), os.path.join(pub, "export", "publish.sh"))
marker = os.path.join(pub, "gh-was-called")
with open(os.path.join(pub, "fakebin", "gh"), "w") as fh:
    fh.write('#!/bin/sh\ntouch "%s"\nexit 1\n' % marker)
os.chmod(os.path.join(pub, "fakebin", "gh"), 0o755)
penv = {k: v for k, v in os.environ.items() if k not in ("GH_TOKEN", "GITHUB_TOKEN", "CARRY_SHA256", "ROLLBACK_TO")}
penv.update(PATH=os.path.join(pub, "fakebin") + os.pathsep + os.environ["PATH"], REPO="invalid/krcn-test",
            TAG="krcn-test", OPENTOME_COLD_START="1")
for flag in ("loc_degraded", "bnf_degraded"):
    art = os.path.join(pub, "build", "a-%s.sqlite" % flag)
    A = sqlite3.connect(art)
    A.executescript("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT); CREATE TABLE series (x); CREATE TABLE volumes (x);")
    A.executemany("INSERT INTO meta VALUES(?,?)", [("gcd_dump", "opentome-2026-09-28"), ("alias_provenance", "opentome"),
                                                   ("licence", "x"), ("carried_from", "cold-start"),
                                                   (flag, "SourceThrottled: test")])
    A.commit()
    A.close()
    r = subprocess.run(["bash", os.path.join(pub, "export", "publish.sh"), art], cwd=pub,
                       env=dict(penv, PUBLISH="1"), capture_output=True, text=True)
    eq("publish.sh refuses a build with meta.%s (and never reaches gh)" % flag,
       (r.returncode, "refusing: meta.%s is set" % flag in r.stderr, os.path.exists(marker)), (1, True, False))
    r = subprocess.run(["bash", os.path.join(pub, "export", "publish.sh"), art], cwd=pub,
                       env=dict(penv, PUBLISH="0"), capture_output=True, text=True)
    eq("... its dry run passes and names the flag", (r.returncode, flag in r.stderr, os.path.exists(marker)),
       (0, True, False))


def pub_art(name, meta):
    art = os.path.join(pub, "build", name)
    A = sqlite3.connect(art)
    A.executescript("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT); CREATE TABLE series (x); CREATE TABLE volumes (x);")
    A.executemany("INSERT INTO meta VALUES(?,?)", [("gcd_dump", "opentome-2026-09-28"), ("alias_provenance", "opentome"),
                                                   ("licence", "x"), ("carried_from", "cold-start")] + meta)
    A.commit()
    A.close()
    return art


def pub_run(art, publish):
    return subprocess.run(["bash", os.path.join(pub, "export", "publish.sh"), art], cwd=pub,
                          env=dict(penv, PUBLISH=publish), capture_output=True, text=True)


STAGED = ("krcn_lines", json.dumps({"roles": {"held": 3, "new_work": 1}, "by_market": {}}))
r = pub_run(pub_art("a-noids.sqlite", [STAGED]), "1")
eq("publish.sh refuses staged KR/CN lines without meta.krcn_ids (and never reaches gh)",
   (r.returncode, "refusing: meta.krcn_ids is absent" in r.stderr, os.path.exists(marker)), (1, True, False))
r = pub_run(pub_art("a-badlines.sqlite", [("krcn_lines", "{not json")]), "1")
eq("... and an unreadable meta.krcn_lines without krcn_ids (fail closed)",
   (r.returncode, "refusing: meta.krcn_ids is absent" in r.stderr, os.path.exists(marker)), (1, True, False))
for label, meta in (("with meta.krcn_ids", [STAGED, ("krcn_ids", '{"works": [], "created": [], "lines": {}}')]),
                    ("with krcn_lines={} (no 3f)", [("krcn_lines", "{}")]), ("with no krcn_lines at all", [])):
    r = pub_run(pub_art("a-ok.sqlite", meta), "0")
    eq("publish.sh dry run %s: no krcn_ids complaint" % label, (r.returncode, "KRCN IDS" in r.stderr), (0, False))
    os.remove(os.path.join(pub, "build", "a-ok.sqlite"))

# ---- Task 14: stage 3f end to end (enumerators replaced; synthetic catalogue) ---------------------------------
import dnb_enumerate as E2, loc_sru as LS2, bnf_sru as BS2
gam = U.records(GAMER)[0]                     # the BnF 'The gamer 1' record (Task 7; `g` was rebound since)
_saved_enum = (E2.enumerate_krcn, LS2.enumerate_loc, BS2.enumerate_bnf, BK.BUILD)
_btmp = tempfile.mkdtemp(prefix="krcn-3f-")
BK.BUILD = _btmp
cat = os.path.join(_btmp, "cat.db")


def fresh_catalogue(path):
    if os.path.exists(path):
        os.remove(path)
    db = sqlite3.connect(path)
    db.executescript(open(os.path.join(ROOT, "schema", "schema.sql"), encoding="utf8").read())
    db.execute("INSERT INTO meta VALUES('x','y')")
    for wid, t in (("w_sl", "Solo Leveling"), ("w_rae", "Why Raeliana Ended Up at the Duke's Mansion")):
        db.execute("INSERT INTO work VALUES(?,?,NULL,NULL,NULL,NULL,'x','x')", (wid, t))
    line_row(db, "rl_sl_en", "w_sl", "manhwa", "EN", "en")
    line_row(db, "rl_rae_en", "w_rae", "manhwa", "EN", "en")
    for n, i, d in (("1", "9781975319434", "2021-03-02"), ("2", "9781975319458", None), ("3", "9781975336516", None)):
        db.execute("INSERT INTO volume(id,release_line_id,number,isbn13,release_date,release_date_precision,"
                   "release_date_type,created_at,updated_at) VALUES(?,?,?,?,?,?,?,'x','x')",
                   ("v_sl%s" % n, "rl_sl_en", n, i, d, "day" if d else None, "on_sale" if d else "unknown"))
    db.commit()
    return path


try:
    E2.enumerate_krcn = lambda verbose=False: ({k: r for k, r in dk.items() if k != "1400000003"}, {}, {"degraded": None})
    LS2.enumerate_loc = lambda verbose=False: ({r["cf"]["001"]: r for r in (SL, SL1, MS, MS4)}, {"degraded": None})
    BS2.enumerate_bnf = lambda verbose=False: ({U.ark(r): r for r in (gam, g2)}, {"degraded": None})
    fresh_catalogue(cat)
    BK.run(cat, None)
    db = sqlite3.connect(cat)
    roles = dict(db.execute("SELECT key, role FROM krcn_line"))
    eq("roles: LoC Solo Leveling merged into the EN line; Mystery a new work; Raeliana review; The Gamer a new work (the lift)",
       (roles["loc:2020950228"], roles["loc:2025007302"], roles["dnb:1390000000"], roles["bnf:ark:/12148/cb09999999z"]),
       ("merged", "new_work", "review", "new_work"))
    w_m, r_m = _id("w_", "krcn", "loc:2025007302"), _id("rl_", "loc:2025007302")
    eq("the new work and its line", (db.execute("SELECT primary_title FROM work WHERE id=?", (w_m,)).fetchone(),
                                     db.execute("SELECT work_id, medium, market FROM release_line WHERE id=?", (r_m,)).fetchone()),
       (("Mystery Science Detectives",), (w_m, "manhwa", "EN")))
    eq("§9: the new work's titles -- the English line name official in en, status NULL",
       (db.execute("SELECT language, kind FROM work_title WHERE work_id=? AND title='Mystery Science Detectives'",
                   (w_m,)).fetchall(), db.execute("SELECT status FROM work WHERE id=?", (w_m,)).fetchone()[0]),
       ([("en", "official")], None))
    w_g, r_g = _id("w_", "krcn", "bnf:ark:/12148/cb09999999z"), _id("rl_", "bnf:ark:/12148/cb09999999z")
    eq("the lift: The Gamer (FR only) is a work keyed krcn|<its BnF key>, its line under it; no held line",
       (db.execute("SELECT work_id, market FROM release_line WHERE id=?", (r_g,)).fetchone(),
        db.execute("SELECT COUNT(*) FROM krcn_line WHERE role='held'").fetchone()[0]),
       ((w_g, "FR"), 0))
    eq("R6: review / held rows hold no work either",
       db.execute("SELECT COUNT(*) FROM krcn_line WHERE exported=0 AND (rl_id IS NOT NULL OR work IS NOT NULL)").fetchone()[0], 0)
    eq("ruling: a merged row's rl_id is the line it merged into (3e dnb_line convention), carried 0",
       db.execute("SELECT rl_id, target, carried, exported FROM krcn_line WHERE key='loc:2020950228'").fetchone(),
       ("rl_sl_en", "rl_sl_en", 0, 1))
    eq("merged: v.1-3 attach to the Wikipedia volumes, v.14-15 are created under the Wikipedia line id",
       sorted(db.execute("SELECT number, fate, volume_id FROM krcn_member WHERE line_key='loc:2020950228' AND member LIKE '%#%'")),
       [("1", "attached", "v_sl1"), ("14", "created", _id("v_", "rl_sl_en", "14")), ("15", "created", _id("v_", "rl_sl_en", "15")),
        ("2", "attached", "v_sl2"), ("3", "attached", "v_sl3")])
    eq("the Wikipedia day date is never replaced by a library year", db.execute(
        "SELECT release_date FROM volume WHERE id='v_sl1'").fetchone()[0], "2021-03-02")
    eq("§8: an attached volume fills only its EMPTY columns (v.1 pages from the single record), recorded in filled",
       (db.execute("SELECT isbn13, page_count FROM volume WHERE id='v_sl1'").fetchone(),
        db.execute("SELECT filled FROM krcn_member WHERE member='loc:2021011111'").fetchone()[0]),
       (("9781975319434", 320), '["page_count"]'))
    eq("every loc claim: us_gov_pd, an lccn.loc.gov url", db.execute(
        "SELECT COUNT(*) FROM claim WHERE source='loc' AND (licence<>'us_gov_pd' OR source_url NOT LIKE 'https://lccn.loc.gov/%')"
    ).fetchone()[0], 0)
    eq("the v.1 date claim points at the single-volume record, not the set record", db.execute(
        "SELECT source_url FROM claim WHERE source='loc' AND entity_id='v_sl1' AND field='release_date'").fetchone()[0],
       "https://lccn.loc.gov/2021011111")
    eq("loc_member: only DLC records", db.execute("SELECT DISTINCT f040a FROM loc_member").fetchall(), [("DLC",)])
    eq("loc_member: every row of an exported line carries its volume id and fate", db.execute(
        """SELECT COUNT(*) FROM loc_member m JOIN krcn_line l ON l.key=m.line_key
           WHERE l.exported=1 AND (m.volume_id IS NULL OR m.fate IS NULL)""").fetchone()[0], 0)
    ids = json.loads(db.execute("SELECT value FROM meta WHERE key='krcn:ids'").fetchone()[0])
    eq("meta krcn:ids: the created works and the library-born lines", (ids["created"], ids["lines"]),
       (sorted([w_m, w_g]), {r_m: "loc", r_g: "bnf"}))
    eq("record_meta: loc:degraded / bnf:degraded absent on a clean run",
       db.execute("SELECT COUNT(*) FROM meta WHERE key IN ('loc:degraded','bnf:degraded','dnb:degraded')").fetchone()[0], 0)
    eq("files written", sorted(f for f in os.listdir(_btmp) if f.startswith("krcn-")),
       ["krcn-held.tsv", "krcn-new-works.tsv", "krcn-report.json", "krcn-review.tsv"])
    held_rows = open(os.path.join(_btmp, "krcn-held.tsv"), encoding="utf8").read().splitlines()[1:]
    eq("the hold file: empty after the lift (no novel-only cluster in this build)", held_rows, [])
    rep = json.load(open(os.path.join(_btmp, "krcn-report.json"), encoding="utf8"))
    eq("krcn-report.json carries the Task 15 gate lists", set(rep["gate"]) >= {"adopt_conflicts", "left", "taken_weak", "deferred_to_jp_round"}, True)
    # §12: enrich_bnf must not spend one SRU call per volume the BnF line source already covered -- its
    # existing "NOT EXISTS ... source='bnf'" clause skips every volume 3f gave a bnf claim (stage 3f runs first)
    fr = schema_db()
    fr.execute("INSERT INTO work VALUES('w_fr','X',NULL,NULL,NULL,NULL,'x','x')")
    line_row(fr, "rl_fr", "w_fr", "manhwa", "FR", "fr")
    fr.execute("INSERT INTO volume(id,release_line_id,number,isbn13,created_at,updated_at) VALUES('v_fr1','rl_fr','1','9782382880371','x','x')")
    fr.execute("INSERT INTO claim VALUES('volume','v_fr1','isbn13','9782382880371','bnf','https://catalogue.bnf.fr/ark:/12148/cb47253773p','open','x')")
    eq("enrich_bnf skips a volume with a BnF line-source claim (0 requests)", EM.enrich_bnf(fr), (0, 0, 0))
    before = sorted(db.execute("SELECT id FROM release_line"))
    before_c = sorted(db.execute("SELECT entity, entity_id, field, source, source_url FROM claim"))
    # another stage's claim on an attached volume (3e / enrich_bnf) must survive the rerun's unload
    db.execute("INSERT INTO claim VALUES('volume','v_sl2','page_count','200','bnf',"
               "'https://catalogue.bnf.fr/api/SRU?query=bib.isbn+all+%229781975319458%22','open','x')")
    db.commit()
    BK.run(cat, None)                                             # a rerun on the same catalogue: unload + reload
    eq("rerun: the same lines", sorted(db.execute("SELECT id FROM release_line")), before)
    eq("rerun: the same claims, plus the other stage's claim on an attached volume (unload takes only its own)",
       sorted(db.execute("SELECT entity, entity_id, field, source, source_url FROM claim")),
       sorted(before_c + [("volume", "v_sl2", "page_count", "bnf",
                           "https://catalogue.bnf.fr/api/SRU?query=bib.isbn+all+%229781975319458%22")]))
    eq("rerun: the filled column is put back and filled again (not left stale)",
       db.execute("SELECT page_count FROM volume WHERE id='v_sl1'").fetchone()[0], 320)
    fresh_catalogue(cat)                                          # P25: the JP round already holds that DNB set key
    db = sqlite3.connect(cat)
    db.executescript(B.STAGING_DDL)
    db.execute("INSERT INTO dnb_line(key,rl_id,role,exported) VALUES('dnb:1390000000','rl_jp','unlinked',0)")
    db.commit()
    st = BK.run(cat, None)
    eq("a DNB set key the JP round holds is deferred: not staged, reported (P25)",
       (db.execute("SELECT COUNT(*) FROM krcn_line WHERE key='dnb:1390000000'").fetchone()[0], st["deferred_to_jp_round"]),
       (0, ["dnb:1390000000"]))
    eq("... and its members are not staged either",
       db.execute("SELECT COUNT(*) FROM krcn_member WHERE line_key='dnb:1390000000'").fetchone()[0], 0)
    # a degraded source reaches the catalogue meta through record_meta (the export and publish.sh refuse on it)
    LS2.enumerate_loc = lambda verbose=False: ({r["cf"]["001"]: r for r in (SL, SL1, MS, MS4)},
                                               {"degraded": "offline-incomplete", "degraded_queries": ["bath.isbn=97988554*"]})
    fresh_catalogue(cat)
    BK.run(cat, None)
    db = sqlite3.connect(cat)
    eq("a degraded LoC enumeration -> meta loc:degraded (record_meta)",
       json.loads(db.execute("SELECT value FROM meta WHERE key='loc:degraded'").fetchone()[0]),
       {"reason": "offline-incomplete", "kept_previous": ["bath.isbn=97988554*"]})
    LS2.enumerate_loc = lambda verbose=False: ({r["cf"]["001"]: r for r in (SL, SL1, MS, MS4)}, {"degraded": None})

    # the next build: the carry names the line; an OLDER record joins the series, so the lowest LCCN -- the
    # natural key -- changes; the carry lookup keeps the published line id and the frozen work id
    carry = carry_file("c3f", [(r_m, w_m, "Mystery Science Detectives", "manhwa", "en",
                                [("3", "9798765627549"), ("4", "9798765627556")])], works=[w_m], krcn_lines={r_m: "loc"})
    MS2 = dict(MS, cf={"001": "older", "008": MS["cf"]["008"]},
               df=[f for f in MS["df"] if f[0] not in ("010", "020", "490")] +
                  [("010", " ", " ", [("a", "  2024999999")]), ("020", " ", " ", [("a", "9798765600009"), ("q", "paperback")]),
                   ("490", " ", " ", [("a", "Mystery Science Detectives ;"), ("v", "book 2")])])
    LS2.enumerate_loc = lambda verbose=False: ({r["cf"]["001"]: r for r in (SL, SL1, MS, MS4, MS2)}, {"degraded": None})
    fresh_catalogue(cat)
    st = BK.run(cat, carry)
    db = sqlite3.connect(cat)
    row = db.execute("SELECT key, rl_id, carried, work FROM krcn_line WHERE name LIKE 'Mystery%'").fetchone()
    eq("re-key: natural key loc:2024999999, published line id and work id kept", row, ("loc:2024999999", r_m, 1, w_m))
    eq("... its volumes are minted under the carried id (v_(tome_id, number)), the new one included",
       sorted(db.execute("SELECT number, id FROM volume WHERE release_line_id=?", (r_m,))),
       sorted((n, _id("v_", r_m, n)) for n in ("2", "3", "4")))
    eq("... the frozen work is not created again (created 1 = The Gamer, not in this carry; frozen 1)",
       (st["works_created"], st["works_frozen"]), (1, 1))
finally:
    E2.enumerate_krcn, LS2.enumerate_loc, BS2.enumerate_bnf, BK.BUILD = _saved_enum


# the hold file is plan['held'] exactly: a cluster of novels only (a comic signal, no comic line) is one row,
# never one per line
_htmp = tempfile.mkdtemp(prefix="krcn-held-")
_saved_build, BK.BUILD = BK.BUILD, _htmp
try:
    hs = [mkline(k, m, "Semantic error", medium="novel", members=[k], reason=None, candidates=[])
          for k, m in (("loc:2025033006", "EN"), ("dnb:1362777552", "DE"))]
    hplan = BK.decide(hs, L.Index(schema_db()), None)
    BK.write_files(hs, hplan, L.Index(schema_db()), {})
    rows = open(os.path.join(_htmp, "krcn-held.tsv"), encoding="utf8").read().splitlines()[1:]
    eq("the hold file: one novel-without-comic row for a cluster of 2 novel lines (no per-line duplicates)",
       [(r.split("\t")[1], r.split("\t")[3]) for r in rows],
       [("novel-without-comic", "dnb:1362777552 loc:2025033006")])
finally:
    BK.BUILD = _saved_build


# ---- Task 14 ruling: adoption moves the staging rows too (krcn_member / loc_member volume ids, krcn_line target) ----
def lib_line(key, tome_id, role, target, vols, carried=False, work="w_ad"):
    lc = key[4:]
    return {"key": key, "source": "loc", "market": "EN", "language": "en", "name": "Adopt me", "publisher": "Ize Press",
            "edition": None, "medium": "manhwa", "medium_why": None, "medium_guess": None, "origin": "kor",
            "explicit": True, "comic": True, "titles": [], "orig": [], "native": [], "authors": [],
            "tome_id": tome_id, "carried": carried, "role": role, "target": target, "work": work, "exported": True,
            "tier": None, "via": "isbn", "link_work": None, "candidates": [], "reason": None, "cluster": None,
            "vols": [{"number": n, "isbn": i, "cands": [(i, "")], "isbns": [i], "pages": None,
                      "date": ("2024", "year", "published"), "date_member": m, "members": [m], "announced": False,
                      "set_record": False} for n, i, m in vols],
            "members": [m for _, _, m in vols],
            "loc": [(m[4:], n, "DLC", " ", "s", 0, None, m) for n, _, m in vols]}


dba = schema_db()
dba.executescript(BK.STAGING_DDL)
dba.execute("INSERT INTO work VALUES('w_ad','Adopt me',NULL,NULL,NULL,NULL,'x','x')")
line_row(dba, "rl_wad", "w_ad", "manhwa", "EN", "en")
for n, i in (("1", "9798400950001"), ("2", "9798400950002"), ("4", "9798400950004")):
    dba.execute("INSERT INTO volume(id,release_line_id,number,isbn13,created_at,updated_at) VALUES(?,?,?,?,'x','x')",
                ("v_wad" + n, "rl_wad", n, i))
adl = lib_line("loc:3000000011", "rl_pubA", "adopting", "rl_wad", carried=True,
               vols=[("1", "9798400950001", "loc:3000000011"), ("2", "9798400950002", "loc:3000000012"),
                     ("3", "9798400950003", "loc:3000000013")])
sib = lib_line("loc:3000000025", _id("rl_", "loc:3000000025"), "sibling", "rl_wad",
               vols=[("5", "9798400950004", "loc:3000000025"), ("7", "9798400950002", "loc:3000000027")])
fates = BK.load(dba, [adl, sib], [], {"works": {}, "adopt_works": [], "held": []}, BK.NO_K)
v2, v4 = _id("v_", "rl_pubA", "2"), _id("v_", "rl_pubA", "4")
eq("adoption: the adopting line's volumes are created under the public id (never attached by ISBN)",
   sorted(r for r in dba.execute("SELECT member, fate, volume_id FROM krcn_member WHERE line_key='loc:3000000011'")),
   [("loc:3000000011", "created", _id("v_", "rl_pubA", "1")), ("loc:3000000012", "created", v2),
    ("loc:3000000013", "created", _id("v_", "rl_pubA", "3"))])
eq("adoption: the internal line is gone; its volumes moved (4) or merged (1, 2) into the public line",
   (dba.execute("SELECT COUNT(*) FROM release_line WHERE id='rl_wad'").fetchone()[0],
    sorted(dba.execute("SELECT number, id FROM volume WHERE release_line_id='rl_pubA'"))),
   (0, sorted((n, _id("v_", "rl_pubA", n)) for n in ("1", "2", "3", "4"))))
eq("adoption moves krcn_member volume ids: a moved volume -> v_(public, n), a merged one -> the public volume",
   sorted(dba.execute("SELECT member, fate, volume_id FROM krcn_member WHERE line_key='loc:3000000025'")),
   [("loc:3000000025", "attached", v4), ("loc:3000000027", "attached", v2)])
eq("... and loc_member volume ids", sorted(dba.execute("SELECT member, volume_id FROM loc_member WHERE line_key='loc:3000000025'")),
   [("loc:3000000025", v4), ("loc:3000000027", v2)])
eq("... and krcn_line target (both rows) and rl_id to the public id; the absorbed sibling holds no id",
   sorted(dba.execute("SELECT key, role, rl_id, target FROM krcn_line")),
   [("loc:3000000011", "adopting", "rl_pubA", "rl_pubA"), ("loc:3000000025", "absorbed", None, "rl_pubA")])
eq("no staging row points at a volume that does not exist",
   dba.execute("""SELECT COUNT(*) FROM (SELECT volume_id FROM krcn_member UNION SELECT volume_id FROM loc_member) s
                  WHERE s.volume_id IS NOT NULL AND s.volume_id NOT IN (SELECT id FROM volume)""").fetchone()[0], 0)
eq("krcn:adopted records the line adoption", json.loads(dba.execute("SELECT value FROM meta WHERE key='krcn:adopted'").fetchone()[0]),
   [["release_line", "rl_wad", "rl_pubA"]])
try:
    BK.unload(dba.cursor())
    eq("unload refuses a catalogue whose ids 3f adopted", "no error", "SystemExit")
except SystemExit:
    eq("unload refuses a catalogue whose ids 3f adopted", True, True)


# ---- Task 14 fix round 1 ----------------------------------------------------------------------------------------
# I1 (review repro build/t14-review/adopt_s8.py): adoption keeps the Wikipedia volume's present columns; the library
# fills only what is empty (the fill_attached rule), even with a finer date
dbs8 = schema_db()
dbs8.executescript(BK.STAGING_DDL)
dbs8.execute("INSERT INTO work VALUES('w_ad','Adopt me',NULL,NULL,NULL,NULL,'x','x')")
line_row(dbs8, "rl_wad", "w_ad", "manhwa", "EN", "en")
dbs8.execute("""INSERT INTO volume(id,release_line_id,number,isbn13,page_count,release_date,release_date_precision,
                release_date_type,created_at,updated_at) VALUES('v_wad1','rl_wad','1','9798400950001',200,'2021','year',
                'on_sale','x','x')""")
dbs8.execute("""INSERT INTO volume(id,release_line_id,number,isbn13,release_date_type,created_at,updated_at)
                VALUES('v_wad2','rl_wad','2',NULL,'unknown','x','x')""")
a8 = lib_line("loc:3000000011", "rl_pubA", "adopting", "rl_wad", carried=True,
              vols=[("1", "9798400950001", "loc:3000000011"), ("2", "9798400950002", "loc:3000000012")])
a8["vols"][0].update(pages=180, date=("2022-05", "month", "published"))
a8["vols"][1].update(pages=190, date=("2022", "year", "published"))
BK.load(dbs8, [a8], [], {"works": {}, "adopt_works": [], "held": []}, BK.NO_K)
eq("I1: after adoption the Wikipedia volume's pages / ISBN / date survive (not the library's 180 / 2022-05)",
   dbs8.execute("SELECT isbn13, page_count, release_date, release_date_precision, release_date_type FROM volume WHERE id=?",
                (_id("v_", "rl_pubA", "1"),)).fetchone(), ("9798400950001", 200, "2021", "year", "on_sale"))
eq("I1: a column Wikipedia left empty takes the library's value",
   dbs8.execute("SELECT isbn13, page_count, release_date, release_date_precision, release_date_type FROM volume WHERE id=?",
                (_id("v_", "rl_pubA", "2"),)).fetchone(), ("9798400950002", 190, "2022", "year", "published"))

# I2 (review repro build/t14-review/conflict.py): two works adopting one public id fail before anything is written
dbc = schema_db()
dbc.executescript(BK.STAGING_DDL)
for w in ("w1", "w2"):
    dbc.execute("INSERT INTO work VALUES(?,?,NULL,NULL,NULL,NULL,'x','x')", (w, w))
cl1 = lib_line("loc:1", "rl_a01", "linked", None, vols=[("1", "9798400950101", "loc:1")], carried=True, work="w_P")
cl2 = lib_line("loc:2", "rl_b02", "linked", None, vols=[("1", "9798400950202", "loc:2")], carried=True, work="w_P")
cl1["adopted_from"], cl2["adopted_from"] = "w1", "w2"
try:
    BK.load(dbc, [cl1, cl2], [], {"works": {}, "adopt_works": [("w1", "w_P"), ("w2", "w_P")],
                                  "adopt_conflicts": [("w1", "w_P"), ("w2", "w_P")], "held": []}, BK.NO_K)
    eq("I2: two works adopting one public id raise SystemExit", "no error", "SystemExit")
except SystemExit as e:
    eq("I2: the message names both works, their lines, the public id and the link_work fix",
       all(x in str(e) for x in ("w1 (lines loc:1)", "w2 (lines loc:2)", "w_P", "link_work")), True)
eq("I2: nothing written -- no release_line, no work w_P, no staging row",
   (dbc.execute("SELECT COUNT(*) FROM release_line").fetchone()[0], sorted(dbc.execute("SELECT id FROM work")),
    dbc.execute("SELECT COUNT(*) FROM krcn_line").fetchone()[0]), (0, [("w1",), ("w2",)], 0))

# Minor 1: an attached volume's claim from another stage (enrich_bnf's per-ISBN SRU url) is kept, not displaced
dbm = schema_db()
dbm.executescript(BK.STAGING_DDL)
dbm.execute("INSERT INTO work VALUES('w_fr','X',NULL,NULL,NULL,NULL,'x','x')")
line_row(dbm, "rl_fr", "w_fr", "manhwa", "FR", "fr")
dbm.execute("INSERT INTO volume(id,release_line_id,number,isbn13,created_at,updated_at) VALUES('v_fr1','rl_fr','1','9782382880371','x','x')")
SRU_URL = "https://catalogue.bnf.fr/api/SRU?query=bib.isbn+all+%229782382880371%22"
dbm.execute("INSERT INTO claim VALUES('volume','v_fr1','volume_number','1','bnf',?,'open','x')", (SRU_URL,))
ark = "bnf:ark:/12148/cb47253773p"
bfl = dict(lib_line("bnf:ark:/12148/cb47253773p", "rl_bfl", "linked", None, vols=[("1", "9782382880371", ark)], work="w_fr"),
           source="bnf", market="FR", language="fr", loc=[])
BK.load(dbm, [bfl], [], {"works": {}, "adopt_works": [], "held": []}, BK.NO_K)
eq("Minor 1: enrich_bnf's claim survives 3f on an attached volume; 3f's other claims land",
   sorted(dbm.execute("SELECT field, source_url FROM claim WHERE entity_id='v_fr1' AND source='bnf'")),
   [("isbn13", "https://catalogue.bnf.fr/ark:/12148/cb47253773p"), ("release_date", "https://catalogue.bnf.fr/ark:/12148/cb47253773p"),
    ("volume_number", SRU_URL)])

# Minor 2: unload takes back 3f's part of dnb:degraded only
for label, before, after in (
        ("3e's value with 3f's 'krcn' part -> 3e's value back",
         {"reason": "3e", "kept_previous": ["q"], "krcn": {"reason": "x", "kept_previous": []}}, {"reason": "3e", "kept_previous": ["q"]}),
        ("3f's own value (round krcn; 3e was clean) -> the key deleted", {"reason": "x", "kept_previous": [], "round": "krcn"}, None),
        ("3e's value alone -> untouched", {"reason": "3e", "kept_previous": []}, {"reason": "3e", "kept_previous": []})):
    dbd = schema_db()
    dbd.executescript(BK.STAGING_DDL)
    dbd.execute("INSERT INTO meta VALUES('dnb:degraded',?)", (json.dumps(before),))
    BK.unload(dbd.cursor())
    got = dbd.execute("SELECT value FROM meta WHERE key='dnb:degraded'").fetchone()
    eq("Minor 2: unload and dnb:degraded: " + label, json.loads(got[0]) if got else None, after)

# Minor 3: a volume one merged line creates is the target's volume of that number for the next merged line
dbt = schema_db()
dbt.executescript(BK.STAGING_DDL)
dbt.execute("INSERT INTO work VALUES('w_t','T',NULL,NULL,NULL,NULL,'x','x')")
line_row(dbt, "rl_t", "w_t", "manhwa", "EN", "en")
dbt.execute("INSERT INTO volume(id,release_line_id,number,isbn13,created_at,updated_at) VALUES('v_t1','rl_t','1','9798400960001','x','x')")
mA = lib_line("loc:4000000001", _id("rl_", "loc:4000000001"), "merged", "rl_t", vols=[("9", "9798400960009", "loc:4000000001")], work="w_t")
mB = lib_line("loc:4000000002", _id("rl_", "loc:4000000002"), "merged", "rl_t", vols=[("9", "9798400960009", "loc:4000000002")], work="w_t")
mC = lib_line("loc:4000000003", _id("rl_", "loc:4000000003"), "merged", "rl_t", vols=[("9", "9798400960099", "loc:4000000003")], work="w_t")
fates = BK.load(dbt, [mA, mB, mC], [], {"works": {}, "adopt_works": [], "held": []}, BK.NO_K)
eq("Minor 3: the first merged line creates v.9, the second attaches to it, a third with another ISBN clashes",
   sorted(dbt.execute("SELECT member, fate, volume_id FROM krcn_member")),
   [("loc:4000000001", "created", _id("v_", "rl_t", "9")), ("loc:4000000002", "attached", _id("v_", "rl_t", "9")),
    ("loc:4000000003", "dropped_number_clash", None)])


# ---- Task 14 fix round 2 ----------------------------------------------------------------------------------------
# new issue 1 (re-review repro): offset numbering -- Wikipedia v1=X1 v2=X2, the library v1=X0 v2=X1 v3=X2. The I1
# re-apply must never put one ISBN on two volumes of the public line; each clash is a review gate entry
X0, X1, X2 = "9798400970000", "9798400970001", "9798400970002"
dbo = schema_db()
dbo.executescript(BK.STAGING_DDL)
dbo.execute("INSERT INTO work VALUES('w_ad','Adopt me',NULL,NULL,NULL,NULL,'x','x')")
line_row(dbo, "rl_wad", "w_ad", "manhwa", "EN", "en")
for n, i in (("1", X1), ("2", X2)):
    dbo.execute("INSERT INTO volume(id,release_line_id,number,isbn13,created_at,updated_at) VALUES(?,?,?,?,'x','x')",
                ("v_wad" + n, "rl_wad", n, i))
ao = lib_line("loc:3000000011", "rl_pubA", "adopting", "rl_wad", carried=True,
              vols=[("1", X0, "loc:3000000011"), ("2", X1, "loc:3000000012"), ("3", X2, "loc:3000000013")])
plan_o = {"works": {}, "adopt_works": [], "held": []}
BK.load(dbo, [ao], [], plan_o, BK.NO_K)
eq("round 2: offset numbering -- no ISBN on two volumes of the public line; each volume keeps its value",
   (dbo.execute("""SELECT COUNT(*) FROM (SELECT isbn13 FROM volume WHERE release_line_id='rl_pubA' AND isbn13 IS NOT NULL
                   GROUP BY isbn13 HAVING COUNT(*) > 1)""").fetchone()[0],
    sorted(dbo.execute("SELECT number, isbn13 FROM volume WHERE release_line_id='rl_pubA'"))),
   (0, [("1", X0), ("2", X1), ("3", X2)]))
eq("round 2: one adoption_isbn_clash entry per clash [line key, public, number, Wikipedia ISBN, ISBN kept]",
   plan_o.get("adoption_isbn_clash"),
   [["loc:3000000011", "rl_pubA", "1", X1, X0], ["loc:3000000011", "rl_pubA", "2", X2, X1]])
eq("round 2: the clash reaches the gate report (krcn-report.json 'gate')",
   BK.gate_report([ao], plan_o, {}, BK.NO_K)["adoption_isbn_clash"],
   [["loc:3000000011", "rl_pubA", "1", X1, X0], ["loc:3000000011", "rl_pubA", "2", X2, X1]])
eq("round 2: no clash, no entry (the I1 scenario)", BK.gate_report([], {}, {}, BK.NO_K)["adoption_isbn_clash"], [])

# new issue 2: without adopted_from the SystemExit says it cannot attribute lines, instead of one list twice
dbc2 = schema_db()
dbc2.executescript(BK.STAGING_DDL)
try:
    BK.load(dbc2, [dict(cl1, adopted_from=None), dict(cl2, adopted_from=None)], [],
            {"works": {}, "adopt_works": [("w1", "w_P"), ("w2", "w_P")], "held": []}, BK.NO_K)
    eq("round 2: the fallback message", "no error", "SystemExit")
except SystemExit as e:
    eq("round 2: without adopted_from the message names both works once and says the lines cannot be attributed",
       ("works w1, w2 -> public id w_P" in str(e), "cannot be attributed" in str(e), str(e).count("loc:1")), (True, True, 1))



# ---- Task 15: contract gates and measure floors -----------------------------------------------------------
import test_artifact as TA, measure_library as ML
_t15 = tempfile.mkdtemp(prefix="krcn-t15-", dir=os.path.join(ROOT, "build"))
_saved_fx = TA.KRCN_FIXTURES


def krcn_fx(new_works=None, pre=(), must_link=(), must_not_link=(), taken_ok=()):
    d = tempfile.mkdtemp(prefix="fx-", dir=_t15)
    for name, body in (("krcn_lines_pre.json", {"lines": list(pre)}),
                       ("krcn_linker_labels.json", {"must_link": list(must_link), "must_not_link": list(must_not_link),
                                                    "taken_ok": [list(p) for p in taken_ok]}),
                       ("krcn_new_works.json", {"works": new_works or {}})):
        with open(os.path.join(d, name), "w") as f:
            json.dump(body, f)
    return d


def gate_pair(taken_weak=()):
    """A catalogue with 3f staging + claims + meta krcn:stats and its artifact, on which every KR/CN rule is
    green (the licence gate included: the artifact has cover_url, the catalogue the current clean_claim)."""
    d = tempfile.mkdtemp(prefix="gate-", dir=_t15)
    catp, artp = os.path.join(d, "cat.db"), os.path.join(d, "art.sqlite")
    cat = sqlite3.connect(catp)
    cat.executescript(open(os.path.join(ROOT, "schema", "schema.sql"), encoding="utf8").read())
    cat.executescript(BK.STAGING_DDL)
    cat.execute("INSERT INTO work VALUES('w_new','New',NULL,NULL,NULL,NULL,'x','x')")
    line_row(cat, "rl_new", "w_new", "manhwa", "EN", "en")
    cat.execute("INSERT INTO volume(id,release_line_id,number,isbn13,created_at,updated_at) VALUES('v_n1','rl_new','1','9798400900648','x','x')")
    for f_, v_, u_ in (("isbn13", "9798400900648", "2023941160"), ("release_date", "2023", "2023000077")):
        cat.execute("INSERT INTO claim VALUES('volume','v_n1',?,?,'loc',?,'us_gov_pd','x')", (f_, v_, "https://lccn.loc.gov/" + u_))
    cat.execute("""INSERT INTO krcn_line(key,source,market,rl_id,carried,name,medium,n_volumes,origin,explicit,comic,role,work,exported)
                   VALUES('loc:2023941160','loc','EN','rl_new',0,'New','manhwa',1,'kor',1,1,'new_work','w_new',1),
                         ('dnb:77','dnb','DE',NULL,0,'Held','manhwa',3,'kor',1,1,'held',NULL,0)""")
    cat.execute("""INSERT INTO loc_member VALUES('2023941160','1','DLC','5','m',1,NULL,'loc:2023941160#1','loc:2023941160','v_n1','created'),
                                                ('2023000077','1','DLC',' ','s',0,NULL,'loc:2023000077','loc:2023941160','v_n1','created')""")
    cat.execute("INSERT INTO meta VALUES('krcn:stats',?)", (json.dumps({"gate": {"taken_weak": [list(t) for t in taken_weak],
                                                                                 "adoption_isbn_clash": []}}),))
    cat.commit()
    A = sqlite3.connect(artp)
    A.executescript("""CREATE TABLE series (gcd_series_id INTEGER, tome_id TEXT, tome_work_id TEXT, language TEXT, medium TEXT);
        CREATE TABLE volumes (gcd_series_id INTEGER, tome_id TEXT, isbn13 TEXT, cover_url TEXT, cover_source TEXT);
        CREATE TABLE id_map (opentome_id TEXT, int_id INTEGER, kind TEXT); CREATE TABLE meta (key TEXT, value TEXT);
        CREATE TABLE id_redirect (old_tome_id TEXT, new_tome_id TEXT);
        INSERT INTO series VALUES(1,'rl_new','w_new','en','manhwa');
        INSERT INTO volumes VALUES(1,'v_n1','9798400900648',NULL,NULL);""")
    A.executemany("INSERT INTO meta VALUES(?,?)", [
        ("attribution", "Bibliographic data: ... Library of Congress (US government work; LoC-created records only) ..."),
        ("krcn_ids", json.dumps({"works": ["w_new"], "created": ["w_new"], "lines": {"rl_new": "loc"}}))])
    A.commit()
    return artp, catp


LABELLED = {"w_new": {"verdict": "must_create", "anchor_key": "loc:2023941160", "title": "New"}}


def krcn_fails(mutate_cat=(), mutate_art=(), fx=None, carry=None, taken_weak=()):
    artp, catp = gate_pair(taken_weak)
    for sql in mutate_cat:
        sqlite3.connect(catp).executescript(sql)
    for sql in mutate_art:
        sqlite3.connect(artp).executescript(sql)
    TA.KRCN_FIXTURES = fx or krcn_fx(new_works=LABELLED)
    n = len(TA.FAILS)
    with contextlib.redirect_stdout(io.StringIO()):
        TA.run_krcn(artp, catp, carry)
    got = TA.FAILS[n:]
    del TA.FAILS[n:]
    return got


has = lambda fails, s: any(s in f for f in fails)
eq("a clean KR/CN build passes every rule", krcn_fails(), [])
eq("a non-DLC loc_member fails", has(krcn_fails(["UPDATE loc_member SET f040a='ZCU' WHERE lccn='2023000077';"]), "not DLC"), True)
eq("a loc_member row with a NULL 040 $a counts as not DLC", has(krcn_fails(
    ["CREATE TABLE lm2 AS SELECT * FROM loc_member; DROP TABLE loc_member; ALTER TABLE lm2 RENAME TO loc_member;"
     "INSERT INTO loc_member(lccn,number,f040a,set_record,member) VALUES('2023000078','2',NULL,0,'loc:2023000078');"]),
    "not DLC"), True)
eq("a loc claim citing a record that is no loc_member fails", has(krcn_fails(
    ["UPDATE claim SET source_url='https://lccn.loc.gov/2099000001' WHERE field='release_date';"]),
    "record is not a DLC loc_member"), True)
eq("a loc date from a set record fails", has(krcn_fails(
    ["UPDATE claim SET source_url='https://lccn.loc.gov/2023941160' WHERE field='release_date';"]), "set record"), True)
eq("a loc published date from an ECIP record fails", has(krcn_fails(
    ["UPDATE loc_member SET encoding_level='5' WHERE lccn='2023000077';"]), "level 5 / 8"), True)
eq("a loc published date at month precision fails", has(krcn_fails(
    ["UPDATE claim SET value='2023-04' WHERE field='release_date';"]), "not year precision"), True)
eq("a volume dated from a 263 1111 fails", has(krcn_fails(
    ["UPDATE claim SET field='projected_date', value='2023-01' WHERE field='release_date';"
     "UPDATE loc_member SET f263='1111', encoding_level='8' WHERE lccn='2023000077';"]), "263 1111"), True)
eq("a clean_claim view without us_gov_pd fails (pre-Task-13 catalogue)", has(krcn_fails(
    ["DROP VIEW clean_claim; CREATE VIEW clean_claim AS SELECT * FROM claim WHERE licence IN ('cc0','open','facts_only');"]),
    "clean_claim misses loc claims"), True)
eq("a held line with an id fails R6 (the licence gate's rule, called from run_krcn)", has(krcn_fails(
    ["UPDATE krcn_line SET rl_id='rl_x' WHERE key='dnb:77';"]), "non-exported krcn_line rows holding a tome_id"), True)
eq("a created work without an English line fails R6", has(krcn_fails(
    mutate_art=["UPDATE series SET language='de';"]), "English line"), True)
eq("a created work without explicit KR/CN origin fails", has(krcn_fails(
    ["UPDATE krcn_line SET explicit=0 WHERE key='loc:2023941160';"]), "explicit KR/CN origin"), True)
eq("a created work with a JP manga line fails", has(krcn_fails(
    ["INSERT INTO release_line(id,work_id,medium,market,language,created_at,updated_at) VALUES('rl_jp','w_new','manga','JP','ja','x','x');"]),
    "Japanese line"), True)
eq("a KR/CN novel line in a work without a comic line fails", has(krcn_fails(
    mutate_art=["UPDATE series SET medium='novel';"]), "novel lines"), True)
eq("dnb_line and krcn_line keys overlapping fails", has(krcn_fails(
    ["CREATE TABLE dnb_line (key TEXT); INSERT INTO dnb_line VALUES('dnb:77');"]), "overlap"), True)
eq("the licence gate runs inside run_krcn (a loc summary fails its allowlist)", has(krcn_fails(
    ["INSERT INTO claim VALUES('volume','v_n1','summary','A story','loc','https://lccn.loc.gov/2023000077','us_gov_pd','x');"]),
    "field allowlist"), True)
eq("no stage 3f staging: fails closed", has(krcn_fails(["DROP TABLE krcn_line;"]), "staging missing"), True)
eq("first KR/CN build: an unlabelled new work fails (P19/P21)", has(krcn_fails(fx=krcn_fx()), "not labelled"), True)
eq("a must_not_create work exported fails", has(krcn_fails(fx=krcn_fx(new_works={"w_new": {"verdict": "must_not_create"}})),
                                                "must_not_create"), True)
eq("a must_create work missing fails", has(krcn_fails(fx=krcn_fx(new_works=dict(LABELLED, w_gone={"verdict": "must_create"}))),
                                           "must_create works missing"), True)
refresh = carry_file("cflood", [("rl_old", "w_old", "Old", "manhwa", "en", [])], works=["w_old"], krcn_lines={"rl_old": "loc"})
eq("refresh build: an unlabelled new work is reported, not failed (P21)", krcn_fails(fx=krcn_fx(), carry=refresh),
   ["published KR/CN lines absent from the artifact (never demoted to held)"])
many = {"works": ["w_%02d" % i for i in range(21)], "created": ["w_%02d" % i for i in range(21)], "lines": {}}
eq("flood gate: 21 new library works in a refresh build fail", has(krcn_fails(
    mutate_art=["UPDATE meta SET value='%s' WHERE key='krcn_ids';" % json.dumps(many)], fx=krcn_fx(), carry=refresh),
    "new library works"), True)
# fixtures: pre-round ids, the linker labels
eq("a pre-round KR/CN line id missing from the artifact fails", has(krcn_fails(fx=krcn_fx(
    new_works=LABELLED, pre=[{"tome_id": "rl_gone", "name": "Gone", "language": "en", "work": "w_x"}])), "pre-round"), True)
eq("must_link: a line under the expected work but not linked (new_work) counts as wrong", krcn_fails(fx=krcn_fx(
    new_works=LABELLED, must_link=[{"key": "loc:2023941160", "expected_work": "w_new"}])),
   ["KR/CN linker fixture: must_link lines not linked to the expected work"])
eq("must_link: a linked line under the expected work passes", krcn_fails(
    ["UPDATE krcn_line SET role='linked' WHERE key='loc:2023941160';"],
    fx=krcn_fx(new_works=LABELLED, must_link=[{"key": "loc:2023941160", "expected_work": "w_new"}])), [])
eq("must_link: a key the build does not have is reported, not failed", krcn_fails(
    fx=krcn_fx(new_works=LABELLED, must_link=[{"key": "dnb:999", "expected_work": "w_new"}])), [])
eq("must_not_link: the line under the wrong work fails", has(krcn_fails(
    fx=krcn_fx(new_works=LABELLED, must_not_link=[{"key": "loc:2023941160", "wrong_work": "w_new"}])), "must_not_link"), True)
eq("must_not_link: a held line (work NULL) against a real wrong work passes", krcn_fails(
    fx=krcn_fx(new_works=LABELLED, must_not_link=[{"key": "dnb:77", "wrong_work": "w_new"}])), [])

# ruling 3: taken_weak is BLOCKING until a person confirms it; read from the catalogue (krcn:stats), 0-of-0 exempt
WEAK = [["rl_T", "loc:500", 1, 5]]
eq("taken_weak: an unconfirmed weak take fails", has(krcn_fails(taken_weak=WEAK), "taken_weak"), True)
eq("taken_weak: a take confirmed in taken_ok [line key, carried id] passes", krcn_fails(
    taken_weak=WEAK, fx=krcn_fx(new_works=LABELLED, taken_ok=[("loc:500", "rl_T")])), [])
eq("taken_weak: a confirmation for another pair does not count", has(krcn_fails(
    taken_weak=WEAK, fx=krcn_fx(new_works=LABELLED, taken_ok=[("loc:500", "rl_U")])), "taken_weak"), True)
eq("taken_weak: a krcn:stats gate without its taken_weak list fails closed", has(krcn_fails(
    ["UPDATE meta SET value='{\"gate\": {\"adoption_isbn_clash\": []}}' WHERE key='krcn:stats';"]), "krcn:stats"), True)
eq("taken_weak: a catalogue without meta krcn:stats fails closed", has(krcn_fails(["DELETE FROM meta WHERE key='krcn:stats';"]),
                                                                       "krcn:stats"), True)
_gl = lambda ln: dict(ln, role="linked", work="w_x", exported=True, reason=None, via="title", tier="medium", link_work="w_x",
                      authors=[], target=None)
lz = bl("loc:803", "loc", "Rebirth", [("1", None), ("2", None)], "Ize Press")
rz = KI.line_ids([lz], KR2)
eq("0-of-0: line_ids' raw report still lists the take (S2')", rz["taken_weak"], [("rl_rb2", "loc:803", 0, 0)])
eq("0-of-0: a take with no ISBN on either side (same name + publisher family) is NOT listed by gate_report",
   BK.gate_report([_gl(lz)], {"adopt_works": [], "works": {}}, rz, KR2)["taken_weak"], [])
lzi = bl("loc:806", "loc", "Rebirth", [("1", None), ("2", None), ("3", "9798400999993")], "Ize Press")
rzi = KI.line_ids([lzi], KR2)
eq("... but a line WITH ISBNs taking an ISBN-less carried line stays listed",
   (lzi["tome_id"], BK.gate_report([_gl(lzi)], {"adopt_works": [], "works": {}}, rzi, KR2)["taken_weak"]),
   ("rl_rb2", [["rl_rb2", "loc:806", 0, 0]]))
l4 = bl("loc:804", "loc", "Rebirth", [("3", I5[2][1])], YEN)
r4 = KI.line_ids([l4], KR)
eq("... and a 1-of-5 take stays listed (S3_alt)", BK.gate_report([_gl(l4)], {"adopt_works": [], "works": {}}, r4, KR)["taken_weak"],
   [["rl_rb", "loc:804", 1, 5]])

# ruling 4 (required): a present carried volume's carried ISBN now on ANOTHER present volume fails
VW = _id("v_", "rl_w", "1")
cw = carry_file("cvol", [("rl_w", "w_new", "Wiki", "manhwa", "en", [("1", "9798400900648")])])
PRESENT_W = "INSERT INTO series VALUES(2,'rl_w','w_new','en','manhwa'); INSERT INTO volumes VALUES(2,'%s',NULL,NULL,NULL);" % VW
MOVED = "carried KR/CN-scope volumes whose carried ISBN now sits on another present volume"
eq("carried volume gate: the ISBN of a present carried volume (a line of a touched work) now on a 3f volume fails",
   krcn_fails(mutate_art=[PRESENT_W], carry=cw), [MOVED])
eq("... not when the carried volume is gone (run_ids' redirect rules own that)", krcn_fails(carry=cw), [])
cw2 = carry_file("cvol2", [("rl_w", "w_new", "Wiki", "manhwa", "en", [("1", "9798400900648")]),
                           ("rl_new", "w_new", "New", "manhwa", "en", [("1", "9798400900648")])])
VN = "UPDATE volumes SET tome_id='%s' WHERE tome_id='v_n1';" % _id("v_", "rl_new", "1")
eq("... not when an unchanged carry duplicate is still on both volumes (a pre-existing duplicate)",
   krcn_fails(mutate_art=[PRESENT_W.replace("'%s',NULL" % VW, "'%s','9798400900648'" % VW), VN], carry=cw2), [])
eq("... but a carry duplicate whose ISBN left the in-scope volume (still present) for the other one fails",
   krcn_fails(mutate_art=[PRESENT_W, VN], carry=cw2), [MOVED])
cw3 = carry_file("cvol3", [("rl_w", "w_other", "Wiki", "manga", "en", [("1", "9798400900648")])])
eq("... and out of scope: a line of a work no KR/CN line touches",
   krcn_fails(mutate_art=[PRESENT_W.replace("'w_new'", "'w_other'")], carry=cw3), [])

# ruling 2: the BnF search-URL hole -- a volume of a BnF KR/CN line whose only bnf claims are SRU-cited
# enrichment-shaped fields is line-source (krcn_member join): ark urls only
SRU_URL = "https://catalogue.bnf.fr/api/SRU?query=bib.isbn+all+%229782811600009%22"
BNF_STAGE = """INSERT INTO krcn_line(key,source,market,carried,role,exported) VALUES('bnf:ark:/12148/cb47000001x','bnf','FR',0,'new_work',1),
                                                                             ('dnb:1400000001','dnb','DE',0,'linked',1);
               INSERT INTO krcn_member(member,line_key,number,volume_id,fate) VALUES
                 ('bnf:ark:/12148/cb47000001x','bnf:ark:/12148/cb47000001x','1','v_bl','created'),
                 ('dnb:1400000002','dnb:1400000001','1','v_dl','attached');"""
eq("licence gate: a BnF-line volume whose only bnf claims carry the per-ISBN SRU url fails (krcn_member join)",
   lic_gate([("volume", "v_bl", "page_count", "150", "bnf", SRU_URL, "open")], staging=BNF_STAGE), [BNFU])
eq("... an SRU enrichment claim on a volume staged only by a DNB line still passes",
   lic_gate([("volume", "v_dl", "page_count", "150", "bnf", SRU_URL, "open")], staging=BNF_STAGE), [])
eq("... and an ark-cited claim on the BnF-line volume passes",
   lic_gate([("volume", "v_bl", "page_count", "150", "bnf", "https://catalogue.bnf.fr/ark:/12148/cb47000001x", "open")],
            staging=BNF_STAGE), [])

# ruling 6: a BnF child whose own 101 $c contradicts its KR/CN head -- the child's own origin wins
def child(c):
    kid = brec(("101", [("a", "fre")] + ([("c", c)] if c else [])), ("010", [("a", isbn13("97823", 141))]), ("200", [("a", "Chonchu"), ("h", "9")]),
               ("210", [("c", "Tokebi"), ("d", "2004")]), ("461", [("0", "39026600"), ("t", "Chonchu"), ("v", "9")]),
               cf3="http://catalogue.bnf.fr/ark:/12148/cb39026900x")        # fr()'s record (the name was rebound since)
    res = KL.bnf_lines({U.ark(r): r for r in [HEAD, kid]})
    return [(l["key"][-11:], l["origin"], l["medium"]) for l in res[0]], res[2]["origin_inherited"]


eq("BnF child 101 $c chi under a kor head (461 $0): its own origin wins -> manhua, nothing inherited",
   child("chi"), ([("cb39026900x", "chi", "manhua")], 0))
eq("BnF child 101 $c jpn under a kor head: its own origin wins -> not KR/CN (out of scope), nothing inherited",
   child("jpn"), ([], 0))
eq("BnF child 101 $c fre under a kor head: not KR/CN either", child("fre"), ([], 0))
eq("BnF child with no 101 $c under a kor head still inherits kor", child(None), ([("cb39026900x", "kor", "manhwa")], 1))

# measure_krcn floors
_saved_floors = (ML.KRCN_STAGED_FLOORS, ML.KRCN_EXPORTED_FLOORS, ML.KRCN_MIN_WORKS, ML.KRCN_STAGED_COVERAGE)
try:
    ML.KRCN_STAGED_FLOORS = {"DE": (1, 3), "FR": (0, 0), "EN": (1, 1)}
    ML.KRCN_EXPORTED_FLOORS = {"DE": (0, 0), "FR": (0, 0), "EN": (1, 1)}
    ML.KRCN_MIN_WORKS = 1
    ML.KRCN_STAGED_COVERAGE = {}
    artp, catp = gate_pair()

    def mk():
        with contextlib.redirect_stdout(io.StringIO()):
            return ML.measure_krcn(artp, catp, None, check_ids=False)
    eq("measure_krcn: floors met", mk(), [])
    ML.KRCN_EXPORTED_FLOORS = {"DE": (0, 0), "FR": (0, 0), "EN": (2, 1)}
    eq("measure_krcn: an exported line floor missed fails", mk(), ["EN exported lines"])
    ML.KRCN_EXPORTED_FLOORS = {"DE": (0, 0), "FR": (0, 0), "EN": (1, 1)}
    ML.KRCN_STAGED_FLOORS = {"DE": (2, 3), "FR": (0, 0), "EN": (1, 2)}
    eq("measure_krcn: staged floors missed fail", mk(), ["DE staged lines", "EN staged volumes"])
    ML.KRCN_STAGED_FLOORS = {"DE": (1, 3), "FR": (0, 0), "EN": (1, 1)}
    ML.KRCN_STAGED_COVERAGE = _saved_floors[3]
    eq("measure_krcn: staged DE volumes but no krcn_member rows to measure coverage on fails (never skipped)", mk(),
       ["DE staged deposited year coverage", "DE staged pages coverage"])
    sqlite3.connect(catp).executescript("""INSERT INTO krcn_member(member,line_key,number,fate,announced_only,dated,paged) VALUES
        ('dnb:78','dnb:77','1','line_held',0,0,1), ('dnb:79','dnb:77','2','line_held',0,1,1),
        ('dnb:80','dnb:77','3','line_held',1,0,1);""")
    eq("measure_krcn: DE deposited-year coverage below 95% fails (announced-only volumes left out)", mk(),
       ["DE staged deposited year coverage"])
    ML.KRCN_MIN_WORKS = 2
    eq("measure_krcn: library works below the floor fail", "library works exported" in mk(), True)
finally:
    ML.KRCN_STAGED_FLOORS, ML.KRCN_EXPORTED_FLOORS, ML.KRCN_MIN_WORKS, ML.KRCN_STAGED_COVERAGE = _saved_floors

# measure_de: the announced set is the union of dnb_member and krcn_member (an undated KR/CN announcement
# is not a deposited-undated volume)
dde = os.path.join(_t15, "de-cat.db")
Cd = sqlite3.connect(dde)
Cd.executescript(BK.STAGING_DDL + """CREATE TABLE dnb_member (idn TEXT, volume_id TEXT, announced_only INTEGER);
    INSERT INTO dnb_member VALUES('1','v_d1',0);
    INSERT INTO krcn_member(member,line_key,number,volume_id,fate,announced_only) VALUES('dnb:9','dnb:8','2','v_k2','created',1),
                                                                                      ('dnb:10','dnb:8','3','v_k3','created',0);""")
Cd.commit()
ade = os.path.join(_t15, "de-art.sqlite")
Ad = sqlite3.connect(ade)
Ad.executescript("""CREATE TABLE series (gcd_series_id INTEGER, language TEXT); CREATE TABLE meta (key TEXT, value TEXT);
    CREATE TABLE volumes (gcd_series_id INTEGER, tome_id TEXT, release_date_raw TEXT, release_date_type TEXT, page_count INTEGER);
    INSERT INTO series VALUES(1,'de');
    INSERT INTO volumes VALUES(1,'v_d1','2020','published',100),(1,'v_k2',NULL,NULL,100),(1,'v_k3','2021','published',100);""")
Ad.commit()
_saved_same = ML.same_ids
ML.same_ids = lambda catalogue: (True, "stub")
try:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        ML.measure_de(ade, dde)
    eq("measure_de: an announced-only krcn_member volume is left out of the deposited date coverage (2/2 = 100%)",
       "DE date coverage (deposited volumes): 100.0% (2/2" in out.getvalue(), True)
finally:
    ML.same_ids = _saved_same

# same_ids: the offline reload (enumerators replaced as in the Task 14 end-to-end test)
_saved_enum = (E2.enumerate_krcn, LS2.enumerate_loc, BS2.enumerate_bnf, BK.BUILD)
BK.BUILD = _t15
cat15 = os.path.join(_t15, "cat15.db")
try:
    E2.enumerate_krcn = lambda verbose=False: ({k: r for k, r in dk.items() if k != "1400000003"}, {}, {"degraded": None})
    LS2.enumerate_loc = lambda verbose=False: ({r["cf"]["001"]: r for r in (SL, SL1, MS, MS4)}, {"degraded": None})
    BS2.enumerate_bnf = lambda verbose=False: ({U.ark(r): r for r in (gam, g2)}, {"degraded": None})
    fresh_catalogue(cat15)
    with contextlib.redirect_stdout(io.StringIO()):
        BK.run(cat15, None)
    ok15 = BK.same_ids(cat15, None)
    eq("same_ids: a first build reloads to the same ids", (ok15[0], ok15[1].split(",")[0] != "0 exported lines"), (True, True))
    c15 = sqlite3.connect(cat15)
    c15.execute("UPDATE krcn_line SET rl_id='rl_moved' WHERE role='new_work'")
    c15.commit()
    eq("same_ids: an exported line whose staged id differs from the reload fails", BK.same_ids(cat15, None)[0], False)
    def _miss(verbose=False):
        raise BK.SRU.SourceOfflineMiss("bath.isbn=97988554* not cached")
    LS2.enumerate_loc = _miss
    eq("same_ids: an uncached LoC set fails the gate (never live)", BK.same_ids(cat15, None)[0], False)
finally:
    E2.enumerate_krcn, LS2.enumerate_loc, BS2.enumerate_bnf, BK.BUILD = _saved_enum
    TA.KRCN_FIXTURES = _saved_fx
    shutil.rmtree(_t15, ignore_errors=True)

# ---- final whole-branch review fix round (final-fix-brief.md) -------------------------------------------------
_tf = tempfile.mkdtemp(prefix="krcn-final-", dir=os.path.join(ROOT, "build"))

# I1: step 2 never takes a reserved (JP-round) id either -- it falls to rep["left"] (7b)
T_JP = _id("rl_", "dnb:111")
K_i1 = KI.read_carry(carry_file("ci1", [(T_JP, "w_x", "Kkk", "manhwa", "de", I5[:3])], works=["w_x"],
                                krcn_lines={T_JP: "dnb"}))
l_i1 = bl("dnb:222", "dnb", "Kkk", I5[:3])
r_i1 = KI.line_ids([l_i1], K_i1, reserved={T_JP})
eq("I1: a built line sharing 2+ ISBNs with a carried line whose id is reserved (JP round) does not take it",
   (l_i1["tome_id"], l_i1["carried"], r_i1["taken"], r_i1["left"]), (_id("rl_", "dnb:222"), False, [], [T_JP]))

# the stage 3f scenarios below: the Task 14 enumerator stubs, a catalogue with hex work ids (link_work needs them)
W_SLH, W_RAEH, W_LIB, W_OLD = "w_00000000051e", "w_000000007ae1", "w_00000000b1b1", "w_0000000001d1"
R_RAE_DNB = _id("rl_", "dnb:1390000000")


def cat_final(path):
    fresh_catalogue(path)
    db_ = sqlite3.connect(path)
    for old, new in (("w_sl", W_SLH), ("w_rae", W_RAEH)):
        KI.rename_work(db_.cursor(), old, new)
    db_.commit()
    return db_


def corr_dir(link):
    d = tempfile.mkdtemp(prefix="corr-", dir=_tf)
    with open(os.path.join(d, "lines.json"), "w") as f:
        json.dump([{"line_key": k, "link_work": w, "source_url": "x", "checked": "x"} for k, w in link.items()], f)
    return d


def run_final(name, carry=None, link=None, env=None):
    """BK.run on a fresh catalogue with the Task 14 stubs -> (catalogue connection, stats, run_link_work failures)."""
    p = os.path.join(_tf, name + ".db")
    cat_final(p).close()
    saved_dir, saved_env = CORR.DIR, {k: os.environ.get(k) for k in (env or {})}
    CORR.DIR = corr_dir(link or {})
    os.environ.update(env or {})
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            st_ = BK.run(p, carry)
            n = len(TA.FAILS)
            TA.run_link_work(p)
        lw_fails = TA.FAILS[n:]
        del TA.FAILS[n:]
    finally:
        CORR.DIR = saved_dir
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return sqlite3.connect(p), st_, lw_fails


def art_of(c, path, carry):
    """A minimal artifact of a catalogue (series / volumes / id_redirect) for run_ids: a carried line keeps its
    carried integer (what the export's id carry does), a new one gets a fresh one."""
    ints = dict(sqlite3.connect(carry).execute("SELECT tome_id, gcd_series_id FROM series"))
    if os.path.exists(path):
        os.remove(path)
    A = sqlite3.connect(path)
    A.executescript("""CREATE TABLE series (gcd_series_id INTEGER, tome_id TEXT, tome_work_id TEXT, language TEXT, medium TEXT);
                       CREATE TABLE volumes (gcd_series_id INTEGER, tome_id TEXT, isbn13 TEXT);
                       CREATE TABLE id_redirect (old_tome_id TEXT, new_tome_id TEXT, entity TEXT, reason TEXT,
                                                 old_series_id INTEGER, new_series_id INTEGER);
                       CREATE TABLE id_map (opentome_id TEXT, int_id INTEGER, kind TEXT);
                       CREATE TABLE meta (key TEXT, value TEXT);""")
    for n_, (rid, wid, lang, med) in enumerate(c.execute("SELECT id, work_id, language, medium FROM release_line ORDER BY id"), 1):
        k = ints.get(rid, 1000 + n_)
        A.execute("INSERT INTO series VALUES(?,?,?,?,?)", (k, rid, wid, lang, med))
        A.executemany("INSERT INTO volumes VALUES(?,?,?)", [(k, v, i) for v, i in c.execute(
            "SELECT id, isbn13 FROM volume WHERE release_line_id=?", (rid,))])
    A.commit()
    return path


_saved_enum = (E2.enumerate_krcn, LS2.enumerate_loc, BS2.enumerate_bnf, BK.BUILD)
BK.BUILD = _tf
try:
    E2.enumerate_krcn = lambda verbose=False: ({k: r for k, r in dk.items() if k != "1400000003"}, {}, {"degraded": None})
    LS2.enumerate_loc = lambda verbose=False: ({r["cf"]["001"]: r for r in (SL, SL1, MS, MS4)}, {"degraded": None})
    BS2.enumerate_bnf = lambda verbose=False: ({U.ark(r): r for r in (gam, g2)}, {"degraded": None})
    c0, _, _ = run_final("base")
    eq("control: the stubbed build sends DE Raeliana (dnb:1390000000) to review, unlinked",
       c0.execute("SELECT role, exported FROM krcn_line WHERE key='dnb:1390000000'").fetchone(), ("review", 0))

    # Work split after adoption (recommendation; reproduced here). Build 1 adopted the Wikipedia work (W_RAEH, internal)
    # into the published library work W_LIB: the carry has the Wikipedia EN line and the DE library line under W_LIB.
    # Build 2: the DE line goes to review (step 5 keeps it) -- W_LIB must stay the work of BOTH, never split.
    c_split = carry_file("csplit", [("rl_rae_en", W_LIB, "Why Raeliana", "manhwa", "en", []),
                                    (R_RAE_DNB, W_LIB, "Raeliana", "manhwa", "de", [])],
                         works=[W_LIB], krcn_lines={R_RAE_DNB: "dnb"})
    c1, st1, _ = run_final("split", carry=c_split)
    eq("work split: the Wikipedia EN line of an adopted work stays under its published work id",
       c1.execute("SELECT work_id FROM release_line WHERE id='rl_rae_en'").fetchone(), (W_LIB,))
    eq("work split: the carried DE line (a frozen cluster of the adopted work) is kept under the same work (one work, not two)",
       c1.execute("SELECT role, exported, work FROM krcn_line WHERE key='dnb:1390000000'").fetchone(), ("kept", 1, W_LIB))
    eq("work split: the internal Wikipedia work id is gone (adopted again), recorded in krcn:adopted",
       (c1.execute("SELECT COUNT(*) FROM work WHERE id=?", (W_RAEH,)).fetchone()[0],
        ["work", W_RAEH, W_LIB] in json.loads(c1.execute("SELECT value FROM meta WHERE key='krcn:adopted'").fetchone()[0])),
       (0, True))
    n = len(TA.FAILS)
    with contextlib.redirect_stdout(io.StringIO()):
        TA.run_ids(art_of(c1, os.path.join(_tf, "split-art.sqlite"), c_split), c_split)
    ids_fails = TA.FAILS[n:]
    del TA.FAILS[n:]
    eq("work split: run_ids on the result (every carried id present or redirected)", ids_fails, [])

    # I2(b): step 5 resolves a carried line's published work through the carry's id_redirect
    c_red = carry_file("cred", [(R_RAE_DNB, W_OLD, "Raeliana", "manhwa", "de", [])], works=[], krcn_lines={R_RAE_DNB: "dnb"})
    sqlite3.connect(c_red).executescript(
        """CREATE TABLE id_redirect (old_tome_id TEXT, new_tome_id TEXT, entity TEXT, reason TEXT, old_series_id INTEGER,
                                     new_series_id INTEGER);
           INSERT INTO id_redirect VALUES('%s','%s','work','duplicate_merge',NULL,NULL);""" % (W_OLD, W_RAEH))
    c2, _, _ = run_final("redirect", carry=c_red)
    eq("I2(b): a carried review line whose published work was redirected (carry id_redirect) is kept under the successor",
       c2.execute("SELECT role, exported, work FROM krcn_line WHERE key='dnb:1390000000'").fetchone(), ("kept", 1, W_RAEH))

    # I3: link_work to (i) a library-born work, (ii) an adopted work, (iii) a Wikipedia work -- each ships in the build
    # and passes 8c's run_link_work
    w_m = _id("w_", "krcn", "loc:2025007302")
    r_m = _id("rl_", "loc:2025007302")
    c_lib = carry_file("clib", [(r_m, w_m, "Mystery Science Detectives", "manhwa", "en",
                                 [("3", "9798765627549"), ("4", "9798765627556")])], works=[w_m], krcn_lines={r_m: "loc"})
    c3, _, f3 = run_final("lw-lib", carry=c_lib, link={"dnb:1390000000": w_m})
    eq("I3 (i): link_work to a published library-born work ships the line under it; run_link_work passes",
       (c3.execute("SELECT role, exported, work FROM krcn_line WHERE key='dnb:1390000000'").fetchone(), f3),
       (("linked", 1, w_m), []))
    c_ad = carry_file("cad", [("rl_rae_en", W_LIB, "Why Raeliana", "manhwa", "en", [])], works=[W_LIB], krcn_lines={})
    c4, _, f4 = run_final("lw-adopted", carry=c_ad, link={"dnb:1390000000": W_LIB})
    eq("I3 (ii): link_work to an adopted work (public id, internal Wikipedia work this build) ships under the public id",
       (c4.execute("SELECT role, exported, work FROM krcn_line WHERE key='dnb:1390000000'").fetchone(),
        c4.execute("SELECT work_id FROM release_line WHERE id='rl_rae_en'").fetchone(), f4),
       (("linked", 1, W_LIB), (W_LIB,), []))
    c5, _, f5 = run_final("lw-wiki", link={"dnb:1390000000": W_RAEH})
    eq("I3 (iii): link_work to a Wikipedia work (control)",
       (c5.execute("SELECT role, exported, work FROM krcn_line WHERE key='dnb:1390000000'").fetchone(), f5),
       (("linked", 1, W_RAEH), []))

    # M4: a 3e DNB stop (meta dnb:degraded) carries into 3f's DNB enumeration; 3f's own old value does not seed itself
    seen = []

    def _enum_seen(verbose=False):
        seen.append(BK.S.DEGRADED[0])
        return {k: r for k, r in dk.items() if k != "1400000003"}, {}, {"degraded": BK.S.DEGRADED[0]}
    E2.enumerate_krcn = _enum_seen
    for label, val, want in (("a 3e stop", {"reason": "DnbThrottled: second 429", "kept_previous": ["q"], "gaps": {}}, True),
                             ("3f's own value of an earlier run", {"reason": "x", "kept_previous": [], "round": "krcn"}, False)):
        p = os.path.join(_tf, "m4.db")
        cat_final(p).execute("INSERT INTO meta VALUES('dnb:degraded',?)", (json.dumps(val),)).connection.commit()
        del seen[:]
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                BK.run(p, None)
        finally:
            BK.S.DEGRADED[0] = None
            del BK.S.DEGRADED_QUERIES[:]
        eq("M4: %s -> dnb_sru DEGRADED set before enumerate_krcn: %s" % (label, want), bool(seen and seen[0]), want)
    E2.enumerate_krcn = lambda verbose=False: ({k: r for k, r in dk.items() if k != "1400000003"}, {}, {"degraded": None})
    # M1: an unreachable LoC / BnF (the CI probe's LOC_UNREACHABLE / BNF_UNREACHABLE) is traced in meta, never blocking
    c6, st6, _ = run_final("offline", env={"LOC_UNREACHABLE": "1"})
    eq("M1: LOC_UNREACHABLE=1 -> meta loc:offline {reason, stale_sets}; no bnf:offline; in krcn-report.json",
       (json.loads((c6.execute("SELECT value FROM meta WHERE key='loc:offline'").fetchone() or ["null"])[0]),
        c6.execute("SELECT COUNT(*) FROM meta WHERE key='bnf:offline'").fetchone()[0],
        json.load(open(os.path.join(_tf, "krcn-report.json"), encoding="utf8")).get("offline")),
       ({"reason": "unreachable", "stale_sets": 0}, 0, {"loc": {"reason": "unreachable", "stale_sets": 0}}))
    eq("M1: loc:offline is not a degraded flag (publishing is not refused on it)",
       c6.execute("SELECT COUNT(*) FROM meta WHERE key LIKE '%degraded'").fetchone()[0], 0)
    BK.unload(c6.cursor())
    eq("M1: unload clears loc:offline", c6.execute("SELECT COUNT(*) FROM meta WHERE key='loc:offline'").fetchone()[0], 0)

    # M6: 8d's same_ids must not overwrite build/loc-report.json (the real enumerate_loc, zero channels, no canary)
    _saved_loc = (LS2.enumerate_loc, LS2.REPORT, LS2.canary, LS2.CHANNELS)
    try:
        LS2.enumerate_loc, LS2.canary, LS2.CHANNELS = _saved_enum[1], (lambda: None), []
        LS2.REPORT = os.path.join(_tf, "loc-report.json")
        BK.same_ids(os.path.join(_tf, "base.db"), None)
        eq("M6: same_ids leaves build/loc-report.json alone", os.path.exists(LS2.REPORT), False)
        LS2.enumerate_loc(verbose=False)
        eq("M6: control -- stage 3f's enumerate_loc still writes it", os.path.exists(LS2.REPORT), True)
    finally:
        LS2.enumerate_loc, LS2.REPORT, LS2.canary, LS2.CHANNELS = _saved_loc
finally:
    E2.enumerate_krcn, LS2.enumerate_loc, BS2.enumerate_bnf, BK.BUILD = _saved_enum

# M1: lib_sru counts the result sets an offline run served past their refresh window (loc:offline stale_sets)
TS = SRU.Source("tstale", "http://x.invalid/sru", "1.2", "marcxml", 100, "test data", budget=0)
TS.relocate(os.path.join(_tf, "cache"), _tf)
os.makedirs(TS.cache, exist_ok=True)
TS.now = lambda: 1.0e9
TS.store_set("q-old", 1, [(TS.url_for("q-old"), '<searchRetrieveResponse><x tag="001">A1<')])
TS.now = lambda: 1.0e9 + 40 * 86400
TS.offline, TS.refresh_days = True, 28
TS.search("q-old", refresh=True)
TS.search("q-old", refresh=True)
eq("M1: an offline run counts each stale cached set it served once", getattr(TS, "stale_queries", None), ["q-old"])

# M5: the German JP round's index (3e) never reads a work stage 3f made (a KEEP_DB rerun of 3e after 3f)
dbm = schema_db()
dbm.execute("INSERT INTO work VALUES('w_libm','Mystery Science Detectives',NULL,NULL,NULL,NULL,'x','x')")
dbm.execute("INSERT INTO work_title VALUES('w_libm','en','Mystery Science Detectives','official')")
dbm.execute("INSERT INTO work VALUES('w_wikim','Solo Leveling',NULL,NULL,NULL,NULL,'x','x')")
dbm.execute("INSERT INTO meta VALUES('krcn:works_made','[\"w_libm\"]')")
ixm = L.Index(dbm)
eq("M5: a 3f-made work (meta krcn:works_made) is not in the linker index; a Wikipedia work is",
   ("w_libm" in ixm.name, "mysterysciencedetectives" in ixm.official, "w_wikim" in ixm.name), (False, False, True))

# the step-5 path of the split: a carried line sent to review BEFORE pooling (writer_only, no guess) whose published
# work is an adopted public id -- kept at the adopting Wikipedia work, which step 7 renames to the public id
db_sp = schema_db()
db_sp.execute("INSERT INTO work VALUES('w_wiki','Lover Boy',NULL,NULL,NULL,NULL,'x','x')")
line_row(db_sp, "rl_wiki", "w_wiki", "manhwa", "EN", "en")
K_sp = {"works": {"w_libS"}, "lines": {"rl_S": "dnb"}, "series_ids": {"rl_S", "rl_wiki"}, "work_ids": {"w_libS"},
        "int": {"rl_S": 7, "rl_wiki": 9}, "line_work": {"rl_S": "w_libS", "rl_wiki": "w_libS"}, "line_name": {},
        "line_medium": {}, "line_vols": {}}
ls_sp = [mkline("dnb:77", "DE", "Liebesjunge", medium=None, medium_why="writer_only", carried=True, tome_id="rl_S")]
plan_sp = BK.decide(ls_sp, L.Index(db_sp), K_sp, present={"rl_wiki": "w_wiki"})
eq("work split, step 5: a carried review line under an adopted public id is kept; the Wikipedia work adopts it again",
   ((ls_sp[0]["role"], ls_sp[0]["work"], ls_sp[0]["exported"]), plan_sp["adopt_works"], plan_sp["adopt_conflicts"],
    "w_libS" in plan_sp["works"]), (("kept", "w_libS", True), [("w_wiki", "w_libS")], [], False))

# residuals (final re-review): several present works re-adopting ONE public id stop the build (mixed adopters: a published
# older work and an internal one) -- never a silent split
db_mx = schema_db()
for w, t in (("w_a", "Lover Boy"), ("w_b", "Lover Boy Side")):
    db_mx.execute("INSERT INTO work VALUES(?,?,NULL,NULL,NULL,NULL,'x','x')", (w, t))
line_row(db_mx, "rl_en", "w_a", "manhwa", "EN", "en")
line_row(db_mx, "rl_a0", "w_a", "manhwa", "EN", "en")
line_row(db_mx, "rl_fr", "w_b", "manhwa", "FR", "fr")
K_mx = {"works": {"w_libS"}, "lines": {"rl_S": "dnb"}, "series_ids": {"rl_S", "rl_en", "rl_fr", "rl_a0"},
        "work_ids": {"w_libS", "w_a"}, "int": {"rl_a0": 1, "rl_S": 7, "rl_en": 9, "rl_fr": 10},
        "line_work": {"rl_S": "w_libS", "rl_en": "w_libS", "rl_fr": "w_libS", "rl_a0": "w_a"}, "line_name": {},
        "line_medium": {}, "line_vols": {}}
ls_mx = [mkline("dnb:77", "DE", "Liebesjunge", medium=None, medium_why="writer_only", carried=True, tome_id="rl_S")]
plan_mx = BK.decide(ls_mx, L.Index(db_mx), K_mx, present={"rl_en": "w_a", "rl_fr": "w_b", "rl_a0": "w_a"})
eq("residual: mixed adopters of one public id are both listed in adopt_conflicts",
   sorted(t for t in plan_mx["adopt_conflicts"] if t[1] == "w_libS"), [("w_a", "w_libS"), ("w_b", "w_libS")])
try:
    with contextlib.redirect_stdout(io.StringIO()):
        BK.load(schema_db(), ls_mx, [], plan_mx, K_mx)
    msg_mx = None
except SystemExit as e:
    msg_mx = str(e)
except Exception:                     # load went on past the check (and tripped on the minimal lines)
    msg_mx = None
eq("residual: ... and load stops the build naming the works, their lines, the public id and link_work",
   bool(msg_mx) and all(x in msg_mx for x in ("w_a", "w_b", "rl_en", "rl_fr", "w_libS", "link_work")), True)

# residual: a link_work naming a carry-redirected (old) work id is STALE -- 8c's run_link_work would fail it
db_rd = schema_db()
db_rd.execute("INSERT INTO work VALUES('w_new','Lover Boy',NULL,NULL,NULL,NULL,'x','x')")
line_row(db_rd, "rl_new", "w_new", "manhwa", "EN", "en")
K_rd = {"works": set(), "lines": {}, "series_ids": set(), "work_ids": set(), "int": {}, "line_work": {}, "line_name": {},
        "line_medium": {}, "line_vols": {}, "redirect": {"w_old": "w_new"}}
ls_rd = [mkline("dnb:88", "DE", "Zzz unrelated")]
with contextlib.redirect_stdout(io.StringIO()) as out_rd:
    BK.decide(ls_rd, L.Index(db_rd), K_rd, link_work={"dnb:88": "w_old"})
eq("residual: link_work to a redirected work id is stale (not linked), and the log names the successor",
   (ls_rd[0]["role"] == "linked", "STALE" in out_rd.getvalue() and "use w_new" in out_rd.getvalue()), (False, True))

# residual: enrich_more._fetch_xml writes via tmp + rename; a write error propagates (never a silent None / partial file)
import verify as V2


class _FakeResp:
    def __init__(self, b):
        self.b = b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.b


_saved_x = (V2.CACHE, EM.urllib.request.urlopen)
_xc = os.path.join(_tf, "xcache")
try:
    V2.CACHE = _xc
    EM.urllib.request.urlopen = lambda req, timeout=None: _FakeResp(b"<searchRetrieveResponse/>")
    got_x = EM._fetch_xml("http://x.invalid/sru?q=1", interval=0)
    eq("residual: _fetch_xml stores the whole response, no .part left",
       (got_x, sorted(f.endswith(".xml") for f in os.listdir(_xc))), ("<searchRetrieveResponse/>", [True]))
    if os.geteuid() != 0:
        os.chmod(_xc, 0o500)
        try:
            EM._fetch_xml("http://x.invalid/sru?q=2", interval=0)
            raised = False
        except OSError:
            raised = True
        finally:
            os.chmod(_xc, 0o700)
        eq("residual: a cache write error propagates out of _fetch_xml", raised, True)
finally:
    V2.CACHE, EM.urllib.request.urlopen = _saved_x

# I2(a): a carried line that does not export as held / review / unlinked is BLOCKING (absorbed / merged stay 7b's)
_t15 = tempfile.mkdtemp(prefix="krcn-t15b-", dir=_tf)
DEMOTE = "INSERT INTO krcn_line(key,source,market,rl_id,carried,role,work,exported) VALUES('dnb:90','dnb','DE',NULL,1,'%s',NULL,0);"
for r_ in ("held", "review", "unlinked"):
    eq("I2(a): a carried %s line (demoted) fails run_krcn" % r_, has(krcn_fails([DEMOTE % r_]), "demoted"), True)
eq("I2(a): a carried absorbed line is 7b's (not this rule)", krcn_fails([DEMOTE % "absorbed"]), [])
TA.KRCN_FIXTURES = _saved_fx

# I3 (run_link_work): a correction naming a published Wikipedia work that adoption renamed maps through krcn:adopted;
# an adopting line ships
catf = os.path.join(_tf, "lw-cat.db")
cat = sqlite3.connect(catf)
cat.executescript(open(os.path.join(ROOT, "schema", "schema.sql"), encoding="utf8").read() + BK.STAGING_DDL)
cat.execute("INSERT INTO work VALUES(?,'Lib',NULL,NULL,NULL,NULL,'x','x')", (W_LIB,))
for rid in ("rl_lk", "rl_pub"):
    cat.execute("INSERT INTO release_line(id,work_id,medium,market,language,created_at,updated_at) "
                "VALUES(?,?,'manhwa','DE','de','x','x')", (rid, W_LIB))
cat.execute("""INSERT INTO krcn_line(key,source,market,rl_id,carried,role,work,exported) VALUES
               ('dnb:31','dnb','DE','rl_lk',0,'linked',?,1), ('dnb:32','dnb','DE','rl_pub',1,'adopting',?,1)""", (W_LIB, W_LIB))
cat.execute("INSERT INTO meta VALUES('krcn:adopted',?)", (json.dumps([["work", W_RAEH, W_LIB]]),))
cat.commit()
cat.close()
_saved_dir = CORR.DIR
try:
    for key, wid, label in (("dnb:31", W_RAEH, "a correction naming the work adoption renamed (krcn:adopted)"),
                            ("dnb:32", W_LIB, "an adopting line under the corrected work")):
        CORR.DIR = corr_dir({key: wid})
        n = len(TA.FAILS)
        with contextlib.redirect_stdout(io.StringIO()):
            TA.run_link_work(catf)
        eq("I3 run_link_work: %s passes" % label, TA.FAILS[n:], [])
        del TA.FAILS[n:]
finally:
    CORR.DIR = _saved_dir
shutil.rmtree(_tf, ignore_errors=True)

# ==== export fixes (2026-09-28: krcn-consumer-findings §7, §8 "Solo Leveling") ====
# E2: a vernacular 880 paired with a 240 carries the 240 $l language note inside its $a ("멸망 이후의 세계.
# English", LoC 2022942912 / 2024951923): its normalize() is 'english', which became an alias of both works
LEW = lrec("01234cam a2200301 i 4500", "240101s2024    nyua          000 1 eng  ",
           ("010", [("a", "  2024951923")]), DLC,
           ("240", [("6", "880-02"), ("a", "Sar'inma Lewellyn-ssieui nangmanjeog'in jeongchan."), ("l", "English")]),
           ("245", [("a", "Murderous Lewellyn's candlelit dinner /")]),
           ("246", [("a", "멸망 이후의 세계. Korean")]),
           ("880", [("6", "240-02/$1"), ("a", "살인마 르웰린 씨의 낭만적인 정찬. English")]), cid="2")
eq("E2: an 880's trailing '. English' (the 240 $l) is not part of the native title",
   LM.native_titles(LEW), ["살인마 르웰린 씨의 낭만적인 정찬", "멸망 이후의 세계"])
eq("E2: a title that merely contains a language word keeps it",
   LM.native_titles(lrec("x", "x", ("880", [("6", "245-01"), ("a", "영어 English Club")]))), ["영어 English Club"])
for keep in ("Mr. English", "A.I. German", "Dr.Chinese"):
    eq("E2: a Latin title ending in a language word keeps it: %s" % keep,
       LM.native_titles(lrec("x", "x", ("880", [("6", "245-01"), ("a", keep)]))), [keep])

# E1 (decide): a NEW, title-linked library line with no vol 1 -- or an ISBN sibling with no vol 1 (attach_roles
# gives exactly one line per target the merge; a second line sharing the target's ISBNs is a sibling) -- in a work
# and market that already has a carried line goes to review ('fragment'). The dry run's cases: FR Kbooks 4/15/17
# (title-linked) and DE dnb:1281034274 8/11/15 (sibling of rl_a6fdb4d1904a)
db = schema_db()
for wid, title in (("w_sle", "Solo Leveling"), ("w_oth", "Omniscient Reader's Viewpoint")):
    db.execute("INSERT INTO work VALUES(?,?,NULL,NULL,NULL,NULL,'x','x')", (wid, title))
line_row(db, "rl_sle_en", "w_sle", "manhwa", "EN", "en")
line_row(db, "rl_oth_en", "w_oth", "manhwa", "EN", "en")
vols = lambda *ns: [{"number": str(n), "isbns": []} for n in ns]
Kf = dict(BK.NO_K, series_ids={"rl_med", "rl_de14"}, work_ids={"w_sle"}, int={"rl_med": 5, "rl_de14": 6},
          line_work={"rl_med": "w_sle", "rl_de14": "w_sle"}, line_market={"rl_med": "FR", "rl_de14": "DE"})
ls = [mkline("bnf:ark:/12148/cb46910428j", "FR", "Solo leveling", vols=vols(4, 15, 17)),    # fragment
      mkline("bnf:ark:/12148/cb00000002x", "FR", "Solo leveling", vols=vols(1, 2)),         # has vol 1
      mkline("dnb:1281034274", "DE", "Solo Leveling", vols=vols(8, 11, 15), role="sibling", target="rl_de14",
             work="w_sle"),                                                                  # sibling fragment
      mkline("dnb:1281034275", "DE", "Solo Leveling", vols=vols(1, 15), role="sibling", target="rl_de14",
             work="w_sle"),                                                                  # sibling with vol 1
      mkline("loc:2025000001", "EN", "Solo Leveling", vols=vols(15)),                        # no carried EN line
      mkline("dnb:1325611948", "DE", "Omniscient Reader's Viewpoint", vols=vols(5, 14)),    # no carried line in w_oth
      mkline("bnf:ark:/12148/cb00000003x", "FR", "Solo leveling", vols=vols(3), carried=True, tome_id="rl_fr3"),
      mkline("bnf:ark:/12148/cb00000004x", "FR", "Solo leveling", vols=vols(9))]            # a link_work correction
plan = BK.decide(ls, L.Index(db), Kf, link_work={"bnf:ark:/12148/cb00000004x": "w_sle"}, comic_works={"w_sle", "w_oth"})
role = {l["key"]: (l["role"], l["reason"], l["exported"]) for l in ls}
eq("E1: a new title-linked FR line without vol 1, the work's FR line carried -> review 'fragment'",
   role["bnf:ark:/12148/cb46910428j"], ("review", "fragment", False))
eq("E1: ... the same line with vol 1 stays linked", role["bnf:ark:/12148/cb00000002x"][::2], ("linked", True))
eq("E1: a new DE ISBN sibling without vol 1 (no second merge exists) -> review 'fragment'",
   role["dnb:1281034274"], ("review", "fragment", False))
eq("E1: ... a sibling with vol 1 stays a sibling", role["dnb:1281034275"][::2], ("sibling", True))
eq("E1: no carried line in that market (EN) -> linked", role["loc:2025000001"][::2], ("linked", True))
eq("E1: no carried line in that work -> linked (ORV DE 5/14)", role["dnb:1325611948"][::2], ("linked", True))
eq("E1: a carried line is never a new fragment", role["bnf:ark:/12148/cb00000003x"][2], True)
eq("E1: a link_work correction (hand-checked) is not title-linked", role["bnf:ark:/12148/cb00000004x"][::2],
   ("linked", True))
eq("E1: fragments are listed for review, their work cleared (R6)",
   (sorted(k for k in plan["review"] if role[k][1] == "fragment"),
    [l["work"] for l in ls if l["reason"] == "fragment"]),
   (["bnf:ark:/12148/cb46910428j", "dnb:1281034274"], [None, None]))
ls = [mkline("dnb:1235188599", "DE", "Solo leveling", medium="novel", comic=False, vols=vols(3, 4))]
BK.decide(ls, L.Index(db), Kf, comic_works={"w_sle"})
eq("E1: a novel line beside a carried COMIC line only is not a fragment (the export guard's class split)",
   ls[0]["role"], "linked")
ls = [mkline("bnf:ark:/12148/cb46910428j", "FR", "Solo leveling", vols=vols(4, 15, 17), reason="low")]
BK.decide(ls, L.Index(db), Kf, comic_works={"w_sle"})
eq("E1: a fragment's reason is joined, never overwritten", (ls[0]["role"], ls[0]["reason"]), ("review", "low+fragment"))
ls = [mkline("bnf:ark:/12148/cb46910428j", "FR", "Solo leveling", vols=vols(4, 15, 17))]
BK.decide(ls, L.Index(db), None, comic_works={"w_sle"})
eq("E1: no carry (a cold build): nothing is a fragment", ls[0]["role"], "linked")

# ---- KR/CN lift (2026-10-01): the anchor of a new work with no English comic line -----------------------------
ls = [mkline("bnf:ark:/12148/cb40000001x", "FR", "Lame royale")]
plan = BK.decide(ls, L.Index(schema_db()), None)
wA = _id("w_", "krcn", "bnf:ark:/12148/cb40000001x")
eq("lift: an FR comic line alone -> a new work keyed krcn|<its key>, anchored on it, titled with its name",
   (ls[0]["role"], ls[0]["work"], plan["works"][wA]["anchor"], plan["works"][wA]["title"], plan["works"][wA]["created"]),
   ("new_work", wA, "bnf:ark:/12148/cb40000001x", "Lame royale", True))
ls = [mkline("dnb:900", "DE", "Demon Diary"), mkline("bnf:ark:/12148/cb40000002x", "FR", "Demon Diary")]
plan = BK.decide(ls, L.Index(schema_db()), None)
wB = _id("w_", "krcn", "bnf:ark:/12148/cb40000002x")
eq("lift: a DE + FR comic cluster -> one work anchored on the FR line (bnf: sorts before dnb:)",
   ([l["work"] for l in ls], plan["works"][wB]["anchor"]), ([wB, wB], "bnf:ark:/12148/cb40000002x"))
ls = [mkline("loc:2025000101", "EN", "Ink Sky", medium="novel"), mkline("bnf:ark:/12148/cb40000003x", "FR", "Ink Sky")]
plan = BK.decide(ls, L.Index(schema_db()), None)
wC = _id("w_", "krcn", "bnf:ark:/12148/cb40000003x")
eq("lift: an EN novel + an FR comic -> a work anchored on the FR comic; the EN novel ships in it as new_work",
   ([(l["role"], l["work"]) for l in ls], plan["works"][wC]["anchor"]), ([("new_work", wC)] * 2, "bnf:ark:/12148/cb40000003x"))
ls = [mkline("loc:2025000102", "EN", "Red Moon"), mkline("bnf:ark:/12148/cb40000004x", "FR", "Red Moon")]
plan = BK.decide(ls, L.Index(schema_db()), None)
wD = _id("w_", "krcn", "loc:2025000102")
eq("lift: an EN comic + an FR comic -> unchanged: keyed and anchored on the EN line",
   (list(plan["works"]), plan["works"][wD]["anchor"]), ([wD], "loc:2025000102"))
Kz = {"works": {"w_libF"}, "lines": {"rl_F": "dnb"}, "series_ids": {"rl_F"}, "work_ids": {"w_libF"}, "int": {"rl_F": 9},
      "line_work": {"rl_F": "w_libF"}, "line_name": {}, "line_medium": {"rl_F": "manhwa"}, "line_vols": {}}
ls = [mkline("dnb:800", "DE", "Sternenlicht (Roman)", medium="novel", titles=["Sternenlicht"]),
      mkline("dnb:801", "DE", "Sternenlicht", titles=["Sternenlicht"], carried=True, tome_id="rl_F")]
plan = BK.decide(ls, L.Index(schema_db()), Kz)
eq("lift: a FROZEN cluster with no line hashing to its id keeps the first round's rule (cl[0], here the novel)",
   (plan["works"]["w_libF"]["anchor"], plan["works"]["w_libF"]["title"], plan["works"]["w_libF"]["created"]),
   ("dnb:800", "Sternenlicht (Roman)", False))
wH = _id("w_", "krcn", "dnb:861")
Kh = {"works": {wH}, "lines": {"rl_M": "dnb"}, "series_ids": {"rl_M"}, "work_ids": {wH}, "int": {"rl_M": 11},
      "line_work": {"rl_M": wH}, "line_name": {"rl_M": "Little mushroom"}, "line_medium": {"rl_M": "manhua"}, "line_vols": {}}
ls = [mkline("dnb:860", "DE", "Xiao Mo Gu", medium="novel", titles=["Kleiner Pilz"]),
      mkline("dnb:861", "DE", "Kleiner Pilz", medium="manhua", titles=["Kleiner Pilz"], carried=True, tome_id="rl_M")]
plan = BK.decide(ls, L.Index(schema_db()), Kh)
eq("lift: a FROZEN cluster keeps the line its id hashes as the anchor (the manhua, not the lower-keyed novel), "
   "titled with that line's carried name", (plan["works"][wH]["anchor"], plan["works"][wH]["title"]),
   ("dnb:861", "Little mushroom"))
ls = [mkline("dnb:802", "DE", "Ein Roman", medium="novel"), mkline("bnf:ark:/12148/cb40000005x", "FR", "Ein Roman", medium="novel")]
plan = BK.decide(ls, L.Index(schema_db()), None)
eq("lift: a cluster of novels only is still held (novel-without-comic; R6 for prose unchanged)",
   ([l["role"] for l in ls], [h["reason"] for h in plan["held"]], plan["works"]), (["held", "held"], ["novel-without-comic"], {}))

# ---- KR/CN lift: lines.json cluster_with / review act before a work is created ---------------------------------
def decide_out(ls, idx_, K_=None, **kw):
    """BK.decide with stdout captured -> (plan, printed text, SystemExit text or None)."""
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            return BK.decide(ls, idx_, K_, **kw), buf.getvalue(), None
    except SystemExit as e:
        return None, buf.getvalue(), str(e)


dbC = schema_db()
dbC.execute("INSERT INTO work VALUES('w_sl','Solo Leveling',NULL,NULL,NULL,NULL,'x','x')")
line_row(dbC, "rl_sl", "w_sl", "manhwa", "EN", "en")
FR_P, DE_P = "bnf:ark:/12148/cb41000001x", "dnb:910"
ls = [mkline(DE_P, "DE", "Wer definiert Beliebtheit"), mkline(FR_P, "FR", "Qui définit la popularité")]
plan, _, _ = decide_out(ls, L.Index(dbC))
eq("without a correction a DE and an FR cluster of one series are two works", len(plan["works"]), 2)
ls = [mkline(DE_P, "DE", "Wer definiert Beliebtheit"), mkline(FR_P, "FR", "Qui définit la popularité")]
plan, _, _ = decide_out(ls, L.Index(dbC), cluster_with=[(DE_P, FR_P)])
wP = _id("w_", "krcn", FR_P)
eq("cluster_with: one work, anchored on the FR line (lowest comic key), titled with the FR name",
   ([l["work"] for l in ls], list(plan["works"]), plan["works"][wP]["title"]), ([wP, wP], [wP], "Qui définit la popularité"))
ls = [mkline("dnb:911", "DE", "Solo Leveling"), mkline("dnb:912", "DE", "Neuland")]
_, _, err = decide_out(ls, L.Index(dbC), cluster_with=[("dnb:912", "dnb:911")], comic_works={"w_sl"})
eq("cluster_with naming a linked line stops the build, naming the key and its role",
   (err is not None and "dnb:911" in err and "the line is linked" in err), True)
ls = [mkline("dnb:913", "DE", "Neuland")]
_, _, err = decide_out(ls, L.Index(dbC), review_lines={"dnb:999": "x"}, deferred={"dnb:999"})
eq("review naming a deferred line (P25) stops the build", (err is not None and "deferred to the German JP round" in err), True)
ls = [mkline("dnb:913", "DE", "Neuland")]
plan, out, err = decide_out(ls, L.Index(dbC), cluster_with=[("dnb:913", "dnb:998")])
eq("cluster_with naming a key the build does not have: STALE CORRECTION printed, the build goes on",
   (err, "STALE CORRECTION -- lines.json cluster_with dnb:998" in out, ls[0]["role"]), (None, True, "new_work"))
ls = [mkline("dnb:914", "DE", "Athanasia"), mkline("dnb:915", "DE", "Andere Reihe")]
plan, out, _ = decide_out(ls, L.Index(dbC), review_lines={"dnb:914": "may be Who Made Me a Princess"})
eq("review: the line's cluster goes to review with the correction's reason; no work; others unaffected",
   (ls[0]["role"], ls[0]["reason"], ls[0]["work"], ls[1]["role"], "dnb:914" in plan["review"]),
   ("review", "correction: may be Who Made Me a Princess", None, "new_work", True))
Kr = {"works": {"w_libR"}, "lines": {"rl_R": "dnb"}, "series_ids": {"rl_R"}, "work_ids": {"w_libR"}, "int": {"rl_R": 4},
      "line_work": {"rl_R": "w_libR"}, "line_name": {}, "line_medium": {"rl_R": "manhwa"}, "line_vols": {}}
ls = [mkline("dnb:916", "DE", "Alte Reihe", carried=True, tome_id="rl_R")]
_, _, err = decide_out(ls, L.Index(dbC), Kr, review_lines={"dnb:916": "x"})
eq("review on a cluster holding a published (carried) line is refused, naming the reviewed key and the cluster",
   (err is not None and "lines.json review dnb:916 (cluster c0000)" in err and "published line dnb:916" in err), True)
ls = [mkline("dnb:917", "DE", "Solo Leveling", carried=True, tome_id="rl_X"), mkline("dnb:918", "DE", "Neuland")]
plan, out, err = decide_out(ls, L.Index(dbC), cluster_with=[("dnb:918", "dnb:917")], comic_works={"w_sl"})
eq("cluster_with naming a CARRIED line the linker now places: skipped and printed, never a stop",
   (err, "CLUSTER_WITH / REVIEW SKIPPED -- lines.json cluster_with dnb:917: carried line now linked" in out,
    ls[1]["role"]), (None, True, "new_work"))
W_P = _id("w_", "krcn", FR_P)
Kp = {"works": {W_P}, "lines": {"rl_P1": "bnf", "rl_P2": "dnb"}, "series_ids": {"rl_P1", "rl_P2"}, "work_ids": {W_P},
      "int": {"rl_P1": 3, "rl_P2": 4}, "line_work": {"rl_P1": W_P, "rl_P2": W_P},
      "line_name": {"rl_P1": "Qui définit la popularité", "rl_P2": "Wer definiert Beliebtheit"},
      "line_medium": {"rl_P1": "manhwa", "rl_P2": "manhwa"}, "line_vols": {}}
ls = [mkline(DE_P, "DE", "Wer definiert Beliebtheit", carried=True, tome_id="rl_P2"),
      mkline(FR_P, "FR", "Qui définit la popularité", carried=True, tome_id="rl_P1")]
plan, _, _ = decide_out(ls, L.Index(dbC), Kp)
eq("two clusters frozen to one published work (a cluster_with dropped): one plan entry with both lines, the first "
   "cluster's anchor and title kept", (sorted(plan["works"][W_P]["lines"]), plan["works"][W_P]["anchor"],
                                       plan["works"][W_P]["title"], [l["work"] for l in ls]),
   (sorted([DE_P, FR_P]), FR_P, "Qui définit la popularité", [W_P, W_P]))

# ==== summary ====
print()
if FAILS:
    print("%d FAILED: %s" % (len(FAILS), FAILS))
    sys.exit(1)
print("all krcn tests passed")
