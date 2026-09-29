#!/usr/bin/env python3
"""Unit tests for export/to_mangarr.py's pure functions -- no database, no network.
Run: python3 export/test_to_mangarr.py
"""
import contextlib, io, json, os, shutil, sqlite3, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "tier2"))
sys.path.insert(0, os.path.join(ROOT, "schema"))
sys.path.insert(0, os.path.join(ROOT, "tier0"))
from to_mangarr import title_for_export, pick_origin, origin_markets, export, local_title, local_name_for
import corrections as corr

FAILS = []


def eq(label, got, want):
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else f"  got={got!r} want={want!r}"))
    if not ok:
        FAILS.append(label)


def run():
    # ---- title_for_export: redundancy (2026-09-23 follow-up) --------------
    # A LicensedTitle like "Mushoku Tensei: Jobless Reincarnation (Light Novel)
    # Vol. 14" survived the old redundancy check: the bracketed qualifier
    # between the name and the number wasn't in _REDUNDANT_SUFFIX's shape.
    NAME = "Mushoku Tensei: Jobless Reincarnation"
    TITLE = NAME + " (Light Novel) Vol. 14"
    eq("bracketed qualifier + 'Vol.' + number is now redundant",
       title_for_export(TITLE, NAME, True), None)
    eq("bracketed qualifier + bare number is now redundant",
       title_for_export(NAME + " (Light Novel) 14", NAME, True), None)
    eq("a real subtitle after the bracket still survives (not just digits)",
       title_for_export(NAME + " (Light Novel): A Real Subtitle", NAME, True),
       NAME + " (Light Novel): A Real Subtitle")

    # ---- regressions: unaffected by the widened suffix ---------------------
    eq("plain redundant name+number (pre-existing behaviour)",
       title_for_export("X 5", "X", True), None)
    eq("prefix lead-in still strips (a different regex, _PREFIX_LEAD_IN)",
       title_for_export("Sword Art Online 1: Aincrad", "Sword Art Online", True), "Aincrad")
    eq("a real subtitle with no bracket still survives",
       title_for_export("Sword Art Online: Aincrad", "Sword Art Online", True),
       "Sword Art Online: Aincrad")
    eq("trusted titles still round-trip verbatim, redundant shape or not",
       title_for_export(TITLE, NAME, True, trusted=True), TITLE)
    eq("markup is still refused regardless of trusted",
       title_for_export("{{x}}", NAME, True, trusted=True), None)
    eq("number-only is still refused regardless of trusted",
       title_for_export("14", NAME, True, trusted=True), None)

    # ---- pick_origin (2026-09-23 follow-up: lifted from a closure inside
    # export() to module level, so it's independently testable and a
    # corrections-driven medium override can be exercised without a database).
    # Denma's real dates (build/opentome.db, 2026-09-22): JP's main line shipped
    # 2008-10-14, KR's 2015-01-20 (a late collected edition of an ongoing web
    # serialization). Tagged plain 'manga' upstream, Denma has no medium hint, so
    # step 2 (earliest date) picks JP -- the accepted, documented defect
    # (HANDOFF.md 2026-09-21). A corrections/lines.json medium override that
    # retags Denma's lines 'manhwa' routes it through step 1 instead.
    DENMA_MARKETS = {"JP", "KR"}
    DENMA_DATES = {"JP": "2008-10-14", "KR": "2015-01-20"}
    eq("Denma (medium 'manga', no hint): JP wins on date -- the accepted defect",
       pick_origin("manga", DENMA_MARKETS, DENMA_DATES), "JP")
    eq("Denma retagged 'manhwa' (medium override applied): KR wins on the hint",
       pick_origin("manhwa", DENMA_MARKETS, DENMA_DATES), "KR")
    eq("manhwa hint wins even when the JP date is earlier",
       pick_origin("manhwa", {"JP", "KR"}, {"JP": "2000-01-01", "KR": "2015-01-20"}), "KR")
    eq("manhua hint prefers CN over TW", pick_origin("manhua", {"TW", "CN"}, {}), "CN")
    eq("no hint, no dates: falls back to the fixed JP>KR>CN>TW order",
       pick_origin("manga", {"TW", "KR"}, {}), "KR")
    eq("no candidate markets at all: None", pick_origin("manga", set(), {}), None)

    # ---- origin_markets (heading cleanup, 2026-09-29): the export's origin loop at module level, so
    # stage 4b2 (tier0/comic_medium.py) decides a work's origin exactly as the export does. Recast: a
    # ko 'manga' + ko 'manhwa' + fr 'manga' line; King of Hell DE: only a DE 'manga' line and a ko manhwa.
    mo = {("w", "manga"): {"KR", "FR"}, ("w", "manhwa"): {"KR"}, ("d", "manga"): {"DE"}, ("d", "manhwa"): {"KR"},
          ("j", "manga"): {"JP", "KR"}}
    mn = {("w", "KR", "manga"): "a", ("w", "FR", "manga"): "b", ("w", "KR", "manhwa"): "c",
          ("d", "DE", "manga"): "e", ("d", "KR", "manhwa"): "f", ("j", "JP", "manga"): "g", ("j", "KR", "manga"): "h"}
    og, fam = origin_markets(mo, mn, {"a": "2010-01-01", "c": "2010-01-01", "f": "2012-05-01",
                                      "g": "2009-01-01", "h": "2015-01-01"})
    eq("origin_markets: a ko 'manga' line makes KR the manga origin", og[("w", "manga")], "KR")
    eq("origin_markets: the manhwa hint", og[("w", "manhwa")], "KR")
    eq("origin_markets: a DE-only 'manga' finds KR through the comic family (E3)",
       (og[("d", "manga")], ("d", "manga") in fam), ("KR", True))
    eq("origin_markets: an earlier JP 'manga' main line wins the date step (Denma)", og[("j", "manga")], "JP")
    eq("origin_markets: a same-medium origin is not a family origin", ("w", "manga") in fam, False)

    # ---- origin_line pin, end to end (2026-09-24, Roxy Gets Serious): two
    # same-work, same-medium JP lines -- a main line and a spin-off whose
    # line_name claim cannot exact-match an EN line's own name (mirrors the
    # real JP Roxy line's French cross-parsed name). Without a pin, an EN
    # line resolves to the JP MAIN line (the defect); with one, to the spin-off.
    pinned_rid, unpinned_rid, orig_of, gcd_of = fixture_origin_line_pin()
    eq("origin_line pin: resolves to the pinned JP spin-off",
       orig_of[pinned_rid], gcd_of["rl_jp_spinoff"])
    eq("origin_line pin: not the JP main line",
       orig_of[pinned_rid] == gcd_of["rl_jp_main"], False)
    eq("no pin: an EN line with no name match falls back to the JP main line (the defect, reproduced)",
       orig_of[unpinned_rid], gcd_of["rl_jp_main"])

    # ---- a redirected line keeps its consumer-facing integer (2026-09-24, DNB) --------
    # A DNB line whose source key changed (a parent record appeared) gets a new rl_ id and
    # an id_redirect row; the integer a Mangarr stored for the old id must follow it.
    sid, rtype, red, idmap, markets = fixture_redirect_carry()
    eq("a redirected line carries the old line's integer id", sid, 424242)
    eq("release_date_type ships with a dated volume", rtype, "projected")
    eq("the artifact's id_redirect resolves the retired id (chained) to the line that exists",
       red.get("rl_older"), ("rl_new", "release_line", None))
    eq("a successor that already had an integer keeps it; the retired integer resolves through id_redirect",
       red.get("rl_twin"), ("rl_new", "release_line", 555555))
    eq("a retired integer stays reserved in id_map", idmap.get("rl_twin"), (555555, "retired"))
    eq("a degraded DNB refresh reaches the artifact as meta.dnb_degraded (publish.sh refuses it)",
       FIX_META.get("dnb_degraded"), '{"reason": "HTTP 502"}')
    eq("meta markets counts lines per language", markets, {"de": 1})
    eq("meta.krcn_ids carries the library-born works and lines to the next build's carry (P3)",
       json.loads(FIX_META.get("krcn_ids") or "null"), {"works": ["w_r"], "created": ["w_r"], "lines": {"rl_new": "loc"}})
    eq("a degraded LoC refresh reaches the artifact as meta.loc_degraded", FIX_META.get("loc_degraded"),
       '{"reason": "LadderExhausted"}')
    eq("the attribution names the Library of Congress", "Library of Congress" in (FIX_META.get("attribution") or ""), True)
    lic = open(os.path.join(ROOT, "LICENSE-DATA.md"), encoding="utf8").read()
    eq("LICENSE-DATA.md carries meta.attribution byte-for-byte", "\n> %s\n" % FIX_META.get("attribution") in lic, True)

    # ---- KR/CN library lines (krcn-design §8, controller rulings 2, 3, 5) --------------------
    k = fixture_krcn()
    eq("a library line with no Wikipedia name: series.name is the builder's, not an earlier line_name claim",
       k["K"]["line_name"].get("rl_lib2"), "Omniscient Reader")
    eq("... its series.publisher the builder's publisher string", k["K"]["line_pub"].get("rl_lib2"), "Ize Press")
    eq("... the line's own name is its first alias (kind 'line')", k["line_alias"], "Omniscient Reader")
    eq("a library line Wikipedia names keeps the Wikipedia name (controller ruling), the builder's publisher",
       (k["K"]["line_name"].get("rl_lib"), k["K"]["line_pub"].get("rl_lib")), ("Wiki Name", "Ize Press"))
    eq("a merged krcn_line row never renames the existing line it ships inside", (k["K"]["line_name"].get("rl_wiki"),
       k["K"]["line_pub"].get("rl_wiki")), ("Wiki Line", "Yen Press"))
    eq("meta.krcn_ids keeps only ids the artifact ships (a held line's id, a gone work: dropped)",
       (sorted(k["K"]["works"]), k["K"]["lines"]), (["w_k"], {"rl_lib": "loc", "rl_lib2": "loc"}))
    eq("an alternative ISBN claim (isbn13_alt) never reaches the artifact", k["alt_found"], 0)
    eq("meta.krcn_lines tallies roles overall and per market (held included)", k["krcn_lines"],
       {"roles": {"held": 1, "merged": 1, "new_work": 2},
        "by_market": {"DE": {}, "EN": {"held": 1, "merged": 1, "new_work": 2}, "FR": {}}})
    eq("the licence gate flags an isbn13_alt claim (not in the loc field allowlist)", k["alt_gate"],
       ["dnb / loc / bnf claims outside the source's field allowlist"])
    eq("the artifact passes the KR/CN licence and R6 rules", k["licence_fails"], [])
    eq("... and a non-exported line's id listed in meta.krcn_ids fails R6", k["r6_fails"],
       ["held / review / unlinked KR/CN line ids in release_line, series, id_map or meta.krcn_ids"])
    eq("the carry lookup reads each carried line's market (build_krcn's fragment rule)",
       k["K"].get("line_market", {}).get("rl_lib"), "EN")

    # ---- export fixes (2026-09-28, krcn-consumer-findings §3 / §7 / §8 "Solo Leveling") ---------
    x = fixture_export_fixes()
    s = x["after"]
    # E1: a new library line named after the work used to win main_of over a carried sub-named line
    # ("Solo Leveling (Médias)"), become its parent (named_line) and take the work aliases + FR local_name
    eq("E1: the carried FR line keeps is_main", s["rl_med"]["is_main"], 1)
    eq("E1: ... keeps no parent (never a child of the new library line)", s["rl_med"]["parent"], None)
    eq("E1: ... keeps its local_name", s["rl_med"]["local_name"], "Solo Leveling")
    eq("E1: ... keeps every alias it had in the carry", sorted(x["carry"]["rl_med"]["aliases"] - s["rl_med"]["aliases"]), [])
    eq("E1: the new library line is not main in that group", s["rl_lib"]["is_main"], 0)
    eq("E1: ... and takes no counterpart slot the carried FR line does not share (its KR origin differs)",
       (s["rl_lib"]["orig"], s["rl_med"]["orig"], x["cold"]["rl_lib"]["orig"]),
       (None, s["rl_krmed"]["sid"], s["rl_kr"]["sid"]))
    eq("E1: the carried-line gate finds nothing", x["gate_after"], [])
    eq("E1: cold export (no carry): the named library line wins main as before -- the rule is carry-scoped",
       (x["cold"]["rl_lib"]["is_main"], x["cold"]["rl_med"]["is_main"]), (1, 0))
    eq("E1 gate: a carried line losing is_main / local_name / aliases and parented under a new line is caught",
       sorted({w for _, w, _ in x["gate_regressed"]}), ["alias rows lost", "is_main lost", "local_name lost",
                                                         "parent is a line absent from the carry"])
    eq("E1 gate: a listed alias loss (ALIAS_LOSS_OK) and a redirect-explained parent are not failures",
       x["gate_exempt"], [])
    eq("E1 gate: a retired carried line of the group redirected elsewhere explains nothing (review fix)",
       x["gate_elsewhere"], [("rl_hde8", "is_main lost", "")])
    # E2 gate: a bare language name as an alias or a title (normalize(): the Hangul title '... English' -> 'english')
    eq("E2 gate: a language-name alias / name / local_name is caught", sorted(x["lang_rows"]),
       [("local_name", "rl_hde8", "Deutsch"), ("series_alias", "rl_med", "english"),
        ("series_alias", "rl_med", "살인마 르웰린 씨의 낭만적인 정찬. English")])
    eq("E2 gate: the clean artifact has none", x["lang_rows_clean"], [])
    # E3: a manhwa line whose origin market's line is tagged manga (King of Hell DE) finds it
    eq("E3: King of Hell DE manhwa -> the ko 'manga' line", s["rl_hde"]["orig"], s["rl_hkr"]["sid"])
    eq("E3: ... the carried DE manga line keeps its origin", s["rl_hde8"]["orig"], s["rl_hkr"]["sid"])
    eq("E3: a manhua line with only a zh 'manga' line (Biao Ren DE) gains its origin", s["rl_bde"]["orig"],
       s["rl_bzh"]["sid"])
    eq("E3: a same-medium origin still wins over the family (Solo Leveling DE manga -> ko manga)",
       s["rl_sde"]["orig"], s["rl_krm"]["sid"])
    eq("E3: carried lines' orig_series_id unchanged (gate)", x["orig_changes"], [])
    eq("E3 gate: an unlisted carried orig change is caught", x["orig_regressed"], [("rl_sde", "rl_krm", "rl_kr")])
    eq("E3 gate: ... a listed one is not", x["orig_listed"], [])
    eq("E3 gate: ... a listed line with a DIFFERENT change still fails (keyed by line, old, new)",
       [r[:3] for r in x["orig_other"]], [("rl_sde", "rl_krm", "rl_kr")])
    # E3 contract rule (run()): a cross-comic origin pair only when the origin market has no line of the
    # licensed line's own medium; never a novel
    import test_artifact as TA
    om = sqlite3.connect(":memory:")
    om.execute("""CREATE TABLE series (gcd_series_id INTEGER, tome_work_id TEXT, language TEXT, country TEXT,
                  medium TEXT, orig_series_id INTEGER)""")
    om.executemany("INSERT INTO series VALUES(?,?,?,?,?,?)", [
        (1, "w1", "ko", "KR", "manga", None), (2, "w1", "de", "DE", "manhwa", 1),       # KR has no manhwa: ok
        (3, "w2", "ko", "KR", "manga", None), (4, "w2", "ko", "KR", "manhwa", None),
        (5, "w2", "de", "DE", "manhwa", 3),                                             # KR has manhwa: bad
        (6, "w3", "ko", "KR", "manga", None), (7, "w3", "de", "DE", "novel", 6)])      # novel -> comic: bad
    eq("E3 contract: orig mismatches = the same-medium-available pair + the novel", TA.orig_mismatches(om), [5, 7])
    # E4: a library-born FR line whose work has no official fr title takes its BnF line name
    eq("E4: library-born FR line, no fr work title -> the bnf line name", s["rl_dfr"]["local_name"],
       "Dites-moi, princesse !")
    eq("E4: library-born FR line, the work has a fr title -> the official title, unchanged",
       s["rl_nfr"]["local_name"], "Noblesse")
    eq("E4: a Wikipedia FR line (not library-born) with no fr work title stays NULL", s["rl_wfr"]["local_name"], None)

    # ---- local_title / local_name_for (2026-09-24, Preferred Edition v0) -------------
    # Measured on build/opentome.db: FR official work titles are raw Wikipedia article
    # names; work_title() strips the common list kinds but not every one, and article
    # disambiguators ride along.
    eq("fr list article -> the title", local_title("Liste des chapitres de L'Attaque des Titans"),
       "L'Attaque des Titans")
    eq("fr list of spin-off volumes -> the work", local_title("Liste des volumes dérivés de One Piece"),
       "One Piece")
    eq("fr light-novel list -> the title", local_title("Liste des light novel de L'Odyssée de Kino"),
       "L'Odyssée de Kino")
    eq("fr d' form", local_title("Liste des chapitres d'Ushio et Tora"), "Ushio et Tora")
    eq("fr d’ form (curly apostrophe)", local_title("Liste des chapitres d’Ushio et Tora"), "Ushio et Tora")
    eq("fr 'chapitres et épisodes' list (Love Hina shape)",
       local_title("Liste des chapitres et épisodes de Love Hina"), "Love Hina")
    # 'de' must not eat the start of 'des' (review ruling, 2026-09-24): the old
    # alternation turned this into "s Chevaliers du Zodiaque". des = de + les, du = de + le,
    # so the title's own article comes back (fix round 1 ruling).
    eq("fr des form restores Les", local_title("Liste des chapitres des Chevaliers du Zodiaque"),
       "Les Chevaliers du Zodiaque")
    eq("fr des form, measured title", local_title("Liste des chapitres des Gouttes de Dieu"),
       "Les Gouttes de Dieu")
    eq("fr du form restores Le", local_title("Liste des chapitres du Prince du tennis"),
       "Le Prince du tennis")
    # work_title (ingest, tier0/build_corpus.py) and local_title (export) share the article
    # fragment; on every list article both read, they must give the same title (alias-fix).
    from build_corpus import work_title
    for art in ("Liste des chapitres des Gouttes de Dieu", "Liste des tomes des Enquêtes de Kindaichi",
                "Liste des chapitres du Prince du tennis", "Liste des chapitres de L'Attaque des Titans",
                "Liste des chapitres d'Ushio et Tora", "Liste des chapitres d’Ushio et Tora",
                "Liste des light novels des Enquêtes de Kindaichi", "Liste des volumes de One Piece"):
        eq("work_title agrees with local_title: " + art, work_title(art), local_title(art))
    eq("fr chronologie branch", local_title("Chronologie des volumes de Dragon Ball"), "Dragon Ball")
    eq("fr chronologie branch, des form", local_title("Chronologie des tomes des Enquêtes de Kindaichi"),
       "Les Enquêtes de Kindaichi")
    eq("trailing disambiguator dropped", local_title("Radiant (bande dessinée)"), "Radiant")
    eq("trailing disambiguator with a year dropped", local_title("Gestalt (manga, 1992)"), "Gestalt")
    eq("ja qualifier dropped", local_title("Wish (漫画)"), "Wish")
    # A full-width bracket is part of a Japanese title, not a disambiguator (measured).
    eq("full-width reading kept", local_title("オトメン（乙男）"), "オトメン（乙男）")
    eq("full-width subtitle kept", local_title("男女の友情は成立する?（いや、しないっ!!）"),
       "男女の友情は成立する?（いや、しないっ!!）")
    eq("plain title unchanged", local_title("Princesse Mononoké"), "Princesse Mononoké")
    eq("markup is not a title", local_title("{{nihongo|X}}"), None)
    eq("empty is None", local_title(""), None)

    eq("EN lines carry no local name", local_name_for("EN", True, None, ["Attack on Titan"]), None)
    eq("FR main line: the cleaned official title",
       local_name_for("FR", True, None, ["Liste des chapitres de L'Attaque des Titans"]), "L'Attaque des Titans")
    eq("FR arc (not main): none", local_name_for("FR", False, None, ["Liste des chapitres de L'Attaque des Titans"]), None)
    eq("DE: the DNB line name wins", local_name_for("DE", False, "Die rothaarige Schneeprinzessin", ["X"]),
       "Die rothaarige Schneeprinzessin")
    eq("DE main line without a DNB name: the official title", local_name_for("DE", True, None, ["Nah bei dir"]),
       "Nah bei dir")
    eq("JP main line: the native official title", local_name_for("JP", True, None, ["天空のエスカフローネ"]),
       "天空のエスカフローネ")
    eq("first usable official title wins", local_name_for("FR", True, None, ["{{x}}", "Naruto"]), "Naruto")

    # ---- end to end: country + local_name land in the artifact --------------------
    got = fixture_local_names()
    eq("FR line: country is the market code", got["rl_fr"][0], "FR")
    eq("FR line: local_name from the fr official title", got["rl_fr"][1], "L'Attaque des Titans")
    eq("DE line: local_name from the DNB line name", got["rl_de"][1], "Angriff der Titanen")
    eq("EN line: country EN, no local_name", got["rl_en"], ("EN", None))

    # ---- series_alias.language / kind (2026-09-24, Preferred Edition v0 b) ------------
    tags = fixture_alias_tags()
    eq("the line's own name is kind 'line', no language", tags["Attack on Titan"], (None, "line"))
    eq("the cleaned fr official title keeps fr/official", tags["L'Attaque des Titans"], ("fr", "official"))
    eq("its normalized form inherits fr/official", tags["l attaque des titans"], ("fr", "official"))
    eq("an en alias row (romaji arrives this way) is en/alias", tags["Shingeki no Kyojin"], ("en", "alias"))
    eq("a ja official title is ja/official", tags["進撃の巨人"], ("ja", "official"))

    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        sys.exit(1)
    print("to_mangarr ok")


def fixture_redirect_carry():
    tmp = tempfile.mkdtemp(prefix="opentome-redirect-")
    src_path, out_path, carry = (os.path.join(tmp, n) for n in ("pipeline.db", "artifact.sqlite", "carry.sqlite"))
    db = sqlite3.connect(src_path)
    db.executescript(open(os.path.join(ROOT, "schema", "schema.sql"), encoding="utf8").read())
    db.execute("INSERT INTO work(id,primary_title,created_at,updated_at) VALUES('w_r','Redirect Work','x','x')")
    db.execute("""INSERT INTO release_line(id,work_id,medium,market,language,created_at,updated_at)
                 VALUES('rl_new','w_r','manga','DE','de','x','x')""")
    db.execute("""INSERT INTO volume(id,release_line_id,number,isbn13,release_date,release_date_precision,
                  release_date_type,created_at,updated_at)
                  VALUES('v_new1','rl_new','1','9783753935874','2026-11','month','projected','x','x')""")
    db.execute("INSERT INTO id_redirect VALUES('rl_old','rl_new','release_line','correction','x')")
    db.execute("INSERT INTO id_redirect VALUES('rl_older','rl_old','release_line','correction','x')")
    db.execute("INSERT INTO id_redirect VALUES('rl_twin','rl_new','release_line','duplicate_merge','x')")
    db.execute("""INSERT INTO meta VALUES('dnb:degraded','{"reason": "HTTP 502"}')""")
    db.execute("""INSERT INTO meta VALUES('krcn:ids','{"works": ["w_r"], "created": ["w_r"], "lines": {"rl_new": "loc"}}')""")
    db.execute("""INSERT INTO meta VALUES('loc:degraded','{"reason": "LadderExhausted"}')""")
    db.commit()
    c = sqlite3.connect(carry)
    c.execute("CREATE TABLE id_map (opentome_id TEXT PRIMARY KEY, int_id INTEGER UNIQUE NOT NULL, kind TEXT NOT NULL)")
    c.execute("INSERT INTO id_map VALUES('rl_old', 424242, 'release_line')")
    c.execute("INSERT INTO id_map VALUES('rl_twin', 555555, 'release_line')")
    c.commit()
    real_dir = corr.DIR
    corr.DIR = tempfile.mkdtemp(prefix="opentome-nocorr-")      # no corrections in play
    try:
        export(src_path, out_path, carry)
    finally:
        corr.DIR = real_dir
    out = sqlite3.connect(out_path)
    sid = out.execute("SELECT gcd_series_id FROM series WHERE tome_id='rl_new'").fetchone()[0]
    rtype = out.execute("SELECT release_date_type FROM volumes WHERE tome_id='v_new1'").fetchone()[0]
    red = {o: (n, e, oi) for o, n, e, oi in out.execute(
        "SELECT old_tome_id, new_tome_id, entity, old_series_id FROM id_redirect")}
    idmap = {o: (i, k) for o, i, k in out.execute("SELECT opentome_id, int_id, kind FROM id_map")}
    FIX_META["dnb_degraded"] = (out.execute("SELECT value FROM meta WHERE key='dnb_degraded'").fetchone() or [None])[0]
    for k in ("krcn_ids", "loc_degraded", "attribution"):
        FIX_META[k] = (out.execute("SELECT value FROM meta WHERE key=?", (k,)).fetchone() or [None])[0]
    markets = json.loads(out.execute("SELECT value FROM meta WHERE key='markets'").fetchone()[0])
    return sid, rtype, red, idmap, markets


def fixture_krcn():
    """A LoC-born EN line (krcn_line, exported) whose line_name claims are a Wikipedia one inserted
    FIRST and the builder's; a held line; a library claim the export must never carry."""
    import build_krcn as BK, krcn_identity as KI, test_artifact as TA
    from load import _id
    tmp = tempfile.mkdtemp(prefix="opentome-krcn-")
    src_path, out_path = os.path.join(tmp, "pipeline.db"), os.path.join(tmp, "artifact.sqlite")
    db = sqlite3.connect(src_path)
    db.executescript(open(os.path.join(ROOT, "schema", "schema.sql"), encoding="utf8").read())
    db.executescript(BK.STAGING_DDL)
    db.execute("INSERT INTO work(id,primary_title,created_at,updated_at) VALUES('w_k','Solo Leveling','x','x')")
    db.execute("INSERT INTO work(id,primary_title,created_at,updated_at) VALUES('w_o','Other Work','x','x')")
    for rid, wid, pub in (("rl_lib", "w_k", "Yen Press"), ("rl_wiki", "w_o", "Yen Press"), ("rl_lib2", "w_k", None)):
        db.execute("""INSERT INTO release_line(id,work_id,medium,market,language,publisher,created_at,updated_at)
                      VALUES(?,?,'manhwa','EN','en',?,'x','x')""", (rid, wid, pub))
    for rid, name, src, url, lic in (("rl_lib", "Wiki Name", "wikipedia", "https://en.wikipedia.org/wiki/X", "facts_only"),
                                     ("rl_lib", "Solo Leveling", "loc", "https://lccn.loc.gov/2020950228", "us_gov_pd"),
                                     ("rl_lib2", "Stale Name", "opentome", None, "open"),
                                     ("rl_lib2", "Omniscient Reader", "loc", "https://lccn.loc.gov/2021011111", "us_gov_pd"),
                                     ("rl_wiki", "Wiki Line", "wikipedia", "https://en.wikipedia.org/wiki/Y", "facts_only")):
        db.execute("INSERT INTO claim VALUES('release_line',?,'line_name',?,?,?,?,'x')", (rid, name, src, url, lic))
    db.execute("""INSERT INTO volume(id,release_line_id,number,isbn13,created_at,updated_at)
                  VALUES('v_lib1','rl_lib','1','9781975319434','x','x')""")
    db.execute("""INSERT INTO claim VALUES('volume','v_lib1','isbn13_alt','9781975399990','loc',
                  'https://lccn.loc.gov/2020950228','us_gov_pd','x')""")
    held = "loc:2099000001"
    db.execute("""INSERT INTO krcn_line(key,source,market,rl_id,carried,work,name,publisher,role,exported,target)
                  VALUES('loc:2021000001','loc','EN','rl_wiki',0,'w_o','Merged Lib Title','Lib Pub',
                         'merged',1,'rl_wiki')""")
    db.execute("""INSERT INTO krcn_line(key,source,market,rl_id,carried,work,name,publisher,role,exported)
                  VALUES('loc:2020950228','loc','EN','rl_lib',0,'w_k','Solo Leveling','Ize Press','new_work',1)""")
    db.execute("""INSERT INTO krcn_line(key,source,market,rl_id,carried,work,name,publisher,role,exported)
                  VALUES('loc:2021011111','loc','EN','rl_lib2',0,'w_k','Omniscient Reader','Ize Press','new_work',1)""")
    db.execute("""INSERT INTO krcn_line(key,source,market,rl_id,carried,work,name,publisher,role,exported)
                  VALUES(?,'loc','EN',NULL,0,NULL,'Held Title','Ize Press','held',0)""", (held,))
    db.execute("INSERT INTO meta VALUES('krcn:ids',?)", (json.dumps(
        {"works": ["w_k", "w_gone"], "created": ["w_k"], "lines": {"rl_lib": "loc", "rl_lib2": "loc", _id("rl_", held): "loc"}}),))
    db.commit()
    real_dir = corr.DIR
    corr.DIR = tempfile.mkdtemp(prefix="opentome-nocorr-")
    try:
        export(src_path, out_path)
    finally:
        corr.DIR = real_dir
    out = sqlite3.connect(out_path)
    r = {"K": KI.read_carry(out_path),
         "line_alias": out.execute("""SELECT a.alias FROM series_alias a JOIN series s USING(gcd_series_id)
                                      WHERE s.tome_id='rl_lib2' AND a.kind='line'""").fetchone()[0],
         "alt_found": out.execute("""SELECT (SELECT COUNT(*) FROM volumes WHERE isbn13='9781975399990' OR isbn10='9781975399990')
                                     + (SELECT COUNT(*) FROM volumes_special WHERE isbn13='9781975399990')""").fetchone()[0],
         "krcn_lines": json.loads(out.execute("SELECT value FROM meta WHERE key='krcn_lines'").fetchone()[0])}
    out.close()
    n = len(TA.FAILS)
    with contextlib.redirect_stdout(io.StringIO()):
        TA.run_krcn_licence(out_path, src_path)
    r["alt_gate"] = TA.FAILS[n:]
    c = sqlite3.connect(src_path)
    c.execute("DELETE FROM claim WHERE field='isbn13_alt'")
    c.commit()
    c.close()
    n = len(TA.FAILS)
    TA.run_krcn_licence(out_path, src_path)
    r["licence_fails"] = TA.FAILS[n:]
    # the same artifact with the held line's id put back into meta.krcn_ids: R6 must fail
    out = sqlite3.connect(out_path)
    out.execute("UPDATE meta SET value=? WHERE key='krcn_ids'",
                (json.dumps({"works": ["w_k"], "lines": {_id("rl_", held): "loc"}}),))
    out.commit()
    out.close()
    n = len(TA.FAILS)
    with contextlib.redirect_stdout(io.StringIO()):      # the expected FAIL line stays out of the log
        TA.run_krcn_licence(out_path, src_path)
    r["r6_fails"] = TA.FAILS[n:]
    del TA.FAILS[:]
    return r


def fixture_export_fixes():
    """E1 / E3 / E4 (2026-09-28). One catalogue, exported twice: first WITHOUT the library-born lines (that
    artifact is the carry), then with them against that carry. Works:
      Solo Leveling -- KR manhwa + KR manga (the duplicate ko line) + KR 'Solo Leveling (Médias)', EN manhwa,
        FR 'Solo Leveling (Médias)' (a Wikipedia sub-line name), DE manga; library-born: FR 'Solo leveling'
        (bnf, vols 4/15/17);
      King of Hell -- KR manga, EN manga, DE manga vol 8 (carried); library-born: DE manhwa vols 1-3;
      Biao Ren -- CN manga; library-born: DE manhua;
      Who Made Me a Princess -- EN manhwa; library-born FR (bnf 'Dites-moi, princesse !'), no fr work title;
      Noblesse -- EN manhwa, fr official 'Noblesse (manhwa)'; library-born FR (bnf 'Noblesse');
      Wiki FR -- a Wikipedia FR line (not library-born) with a bnf line_name claim, no fr work title."""
    import test_artifact as TA
    tmp = tempfile.mkdtemp(prefix="opentome-exportfix-", dir=os.path.join(ROOT, "build"))
    src_path = os.path.join(tmp, "pipeline.db")
    db = sqlite3.connect(src_path)
    db.executescript(open(os.path.join(ROOT, "schema", "schema.sql"), encoding="utf8").read())
    works = {"w_s": "Solo Leveling", "w_h": "King of Hell", "w_b": "Biao Ren", "w_d": "Who Made Me a Princess",
             "w_n": "Noblesse", "w_w": "Wiki FR Work"}
    for wid, t in works.items():
        db.execute("INSERT INTO work(id,primary_title,created_at,updated_at) VALUES(?,?,'x','x')", (wid, t))
    for wid, lang, t in (("w_s", "fr", "Solo Leveling"), ("w_s", "en", "Solo Leveling: ARISE"),
                         ("w_n", "fr", "Noblesse (manhwa)")):
        db.execute("INSERT INTO work_title(work_id,language,title,kind) VALUES(?,?,?,'official')", (wid, lang, t))
    LINES = [  # rid, work, medium, market, lang, vols, line_name (source, value) or None, library-born
        ("rl_kr", "w_s", "manhwa", "KR", "ko", (1, 2, 3), None, False),
        ("rl_krm", "w_s", "manga", "KR", "ko", (1, 2, 3), None, False),
        ("rl_krmed", "w_s", "manhwa", "KR", "ko", (1, 2), ("wikipedia", "Solo Leveling (Médias)"), False),
        ("rl_sen", "w_s", "manhwa", "EN", "en", (1, 2), None, False),
        ("rl_med", "w_s", "manhwa", "FR", "fr", (1, 2, 3, 4, 5), ("wikipedia", "Solo Leveling (Médias)"), False),
        ("rl_sde", "w_s", "manga", "DE", "de", (1, 2), None, False),
        ("rl_lib", "w_s", "manhwa", "FR", "fr", (4, 15, 17), ("bnf", "Solo leveling"), True),
        ("rl_hkr", "w_h", "manga", "KR", "ko", (1, 2, 3, 4), None, False),
        ("rl_hen", "w_h", "manga", "EN", "en", (1, 2), None, False),
        ("rl_hde8", "w_h", "manga", "DE", "de", (8,), ("dnb", "King of hell"), False),
        ("rl_hde", "w_h", "manhwa", "DE", "de", (1, 2, 3), ("dnb", "King of hell"), True),
        ("rl_bzh", "w_b", "manga", "CN", "zh", (1, 2), None, False),
        ("rl_bde", "w_b", "manhua", "DE", "de", (1,), ("dnb", "Die Klingen der Wächter"), True),
        ("rl_den", "w_d", "manhwa", "EN", "en", (1,), None, False),
        ("rl_dfr", "w_d", "manhwa", "FR", "fr", (1, 2), ("bnf", "Dites-moi, princesse !"), True),
        ("rl_nen", "w_n", "manhwa", "EN", "en", (1,), None, False),
        ("rl_nfr", "w_n", "manhwa", "FR", "fr", (1,), ("bnf", "Noblesse"), True),
        ("rl_wfr", "w_w", "manga", "FR", "fr", (1,), ("bnf", "Wiki FR Titre"), False)]
    born = {r[0]: "bnf" if r[3] == "FR" else "dnb" for r in LINES if r[7]}

    def add(rows):
        for rid, wid, medium, market, lang, vols, lname, _ in rows:
            db.execute("""INSERT INTO release_line(id,work_id,medium,market,language,created_at,updated_at)
                          VALUES(?,?,?,?,?,'x','x')""", (rid, wid, medium, market, lang))
            for n in vols:
                db.execute("""INSERT INTO volume(id,release_line_id,number,release_date,release_date_precision,
                              release_date_type,created_at,updated_at) VALUES(?,?,?,?,'day','published','x','x')""",
                           ("v_%s_%d" % (rid, n), rid, str(n), "20%02d-01-02" % (10 + n) if market in ("KR", "CN") else
                            "20%02d-01-02" % (15 + n)))
            if lname:
                db.execute("""INSERT INTO claim(entity,entity_id,field,value,source,licence,retrieved_at)
                              VALUES('release_line',?,'line_name',?,?,'facts_only','x')""", (rid, lname[1], lname[0]))

    def exp(out_path, carry=None):
        real_dir, corr.DIR = corr.DIR, tempfile.mkdtemp(prefix="opentome-nocorr-", dir=tmp)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                export(src_path, out_path, carry)
        finally:
            corr.DIR = real_dir

    def rows(path):
        o = sqlite3.connect(path)
        sid = dict(o.execute("SELECT gcd_series_id, tome_id FROM series"))
        r = {t: {"sid": s, "is_main": m, "parent": sid.get(p), "local_name": ln, "orig": o_, "aliases": set()}
             for s, t, m, p, ln, o_ in o.execute("""SELECT gcd_series_id, tome_id, is_main, parent_series_id,
                                                    local_name, orig_series_id FROM series""")}
        for t, a in o.execute("SELECT s.tome_id, a.alias FROM series_alias a JOIN series s USING(gcd_series_id)"):
            r[t]["aliases"].add(a)
        o.close()
        return r
    add([r for r in LINES if not r[7]])
    db.commit()
    carry = os.path.join(tmp, "carry.sqlite")
    exp(carry)
    add([r for r in LINES if r[7]])
    db.execute("INSERT INTO meta VALUES('krcn:ids',?)", (json.dumps({"works": [], "created": [], "lines": born}),))
    db.commit()
    db.close()
    out, cold = os.path.join(tmp, "artifact.sqlite"), os.path.join(tmp, "cold.sqlite")
    exp(out, carry)
    exp(cold)
    x = {"carry": rows(carry), "after": rows(out), "cold": rows(cold)}
    A, C = sqlite3.connect(out), sqlite3.connect("file:%s?mode=ro" % carry, uri=True)
    x["gate_after"] = TA.carried_regressions(A, C)
    x["orig_changes"] = TA.carried_orig_changes(A, C)
    x["lang_rows_clean"] = TA.language_name_rows(A)
    # a regressed copy: the 67451c2 shape for the Medias line, junk language rows, a moved carried origin
    reg = os.path.join(tmp, "regressed.sqlite")
    A.close()
    shutil.copy(out, reg)
    R_ = sqlite3.connect(reg)
    s = x["after"]
    R_.execute("UPDATE series SET is_main=0, local_name=NULL, parent_series_id=? WHERE tome_id='rl_med'",
               (s["rl_lib"]["sid"],))
    R_.execute("DELETE FROM series_alias WHERE gcd_series_id=? AND alias='Solo Leveling: ARISE'", (s["rl_med"]["sid"],))
    R_.execute("UPDATE series SET local_name='Deutsch' WHERE tome_id='rl_hde8'")
    for a in ("english", "살인마 르웰린 씨의 낭만적인 정찬. English"):
        R_.execute("INSERT INTO series_alias VALUES(?,?,'ko','official')", (s["rl_med"]["sid"], a))
    R_.execute("UPDATE series SET orig_series_id=? WHERE tome_id='rl_sde'", (s["rl_kr"]["sid"],))
    R_.commit()
    x["gate_regressed"] = TA.carried_regressions(R_, C)
    x["lang_rows"] = TA.language_name_rows(R_)
    x["orig_regressed"] = [(t, a, b) for t, a, b, _ in TA.carried_orig_changes(R_, C, listed={})]
    x["orig_listed"] = TA.carried_orig_changes(R_, C, listed={("rl_sde", "rl_krm", "rl_kr"): "fixture"})
    x["orig_other"] = TA.carried_orig_changes(R_, C, listed={("rl_sde", "rl_krm", "rl_hkr"): "fixture"})
    # exemptions: the alias loss listed (ALIAS_LOSS_OK); the parent change explained by a redirect of the carried
    # parent; an is_main loss explained by a carried line of the same work and market retired by a redirect
    saved = dict(TA.ALIAS_LOSS_OK)
    TA.ALIAS_LOSS_OK[("rl_med", "Solo Leveling: ARISE")] = "fixture"
    R_.execute("UPDATE series SET is_main=1, local_name='Solo Leveling' WHERE tome_id='rl_med'")
    R_.execute("INSERT INTO id_redirect VALUES('rl_krm2','rl_lib','release_line','fixture',NULL,NULL)")
    R_.execute("UPDATE series SET is_main=0 WHERE tome_id='rl_hde8'")
    R_.execute("""INSERT INTO series(gcd_series_id,name,language,country,medium,is_main,tome_id,tome_work_id)
                  VALUES(9003,'King of hell','de','DE','manga',1,'rl_hsucc','w_h')""")
    R_.execute("INSERT INTO id_redirect VALUES('rl_hghost','rl_hsucc','release_line','fixture',NULL,NULL)")
    R_.commit()
    Cx = os.path.join(tmp, "carry-x.sqlite")
    shutil.copy(carry, Cx)
    cx = sqlite3.connect(Cx)
    cx.execute("INSERT INTO series(gcd_series_id,name,tome_id,tome_work_id,country) VALUES(9001,'x','rl_krm2','w_s','KR')")
    cx.execute("UPDATE series SET parent_series_id=9001 WHERE tome_id='rl_med'")
    cx.execute("""INSERT INTO series(gcd_series_id,name,tome_id,tome_work_id,country,medium)
                  VALUES(9002,'x','rl_hghost','w_h','DE','manga')""")
    cx.commit()
    x["gate_exempt"] = TA.carried_regressions(R_, cx)
    # the same retired carried line, redirected ELSEWHERE (the new manhwa line, another group): not an explanation
    R_.execute("UPDATE id_redirect SET new_tome_id='rl_hde' WHERE old_tome_id='rl_hghost'")
    R_.commit()
    x["gate_elsewhere"] = TA.carried_regressions(R_, cx)
    TA.ALIAS_LOSS_OK.clear()
    TA.ALIAS_LOSS_OK.update(saved)
    R_.close(), cx.close(), C.close()
    shutil.rmtree(tmp, ignore_errors=True)
    return x


def fixture_local_names():
    """One work with an EN, a FR and a DE line; a fr official work title and a DNB line
    name. Returns {tome_id: (country, local_name)}."""
    tmp = tempfile.mkdtemp(prefix="opentome-localname-")
    src_path, out_path = (os.path.join(tmp, n) for n in ("pipeline.db", "artifact.sqlite"))
    db = sqlite3.connect(src_path)
    db.executescript(open(os.path.join(ROOT, "schema", "schema.sql"), encoding="utf8").read())
    db.execute("INSERT INTO work(id,primary_title,created_at,updated_at) VALUES('w_aot','Attack on Titan','x','x')")
    for rid, market, lang in (("rl_en", "EN", "en"), ("rl_fr", "FR", "fr"), ("rl_de", "DE", "de")):
        db.execute("""INSERT INTO release_line(id,work_id,medium,market,language,created_at,updated_at)
                      VALUES(?,?,'manga',?,?,'x','x')""", (rid, "w_aot", market, lang))
        db.execute("""INSERT INTO volume(id,release_line_id,number,release_date,release_date_precision,
                      release_date_type,created_at,updated_at) VALUES(?,?,'1','2019-01-02','day','published','x','x')""",
                   ("v_" + rid, rid))
    db.execute("INSERT INTO work_title(work_id,language,title,kind) VALUES('w_aot','fr','Liste des chapitres de L''Attaque des Titans','official')")
    db.execute("""INSERT INTO claim(entity,entity_id,field,value,source,source_url,licence,retrieved_at)
                  VALUES('release_line','rl_de','line_name','Angriff der Titanen','dnb','https://d-nb.info/1','cc0','x')""")
    db.commit(); db.close()
    real_dir, corr.DIR = corr.DIR, tempfile.mkdtemp(prefix="opentome-nocorr-")
    try:
        export(src_path, out_path)
    finally:
        corr.DIR = real_dir
    out = sqlite3.connect(out_path)
    rows = {t: (c, n) for t, c, n in out.execute("SELECT tome_id, country, local_name FROM series")}
    out.close()
    return rows


def fixture_alias_tags():
    """The FR main line of a work with fr/ja official titles and an en alias. Returns
    {alias: (language, kind)} for that line."""
    tmp = tempfile.mkdtemp(prefix="opentome-aliastags-")
    src_path, out_path = (os.path.join(tmp, n) for n in ("pipeline.db", "artifact.sqlite"))
    db = sqlite3.connect(src_path)
    db.executescript(open(os.path.join(ROOT, "schema", "schema.sql"), encoding="utf8").read())
    db.execute("INSERT INTO work(id,primary_title,created_at,updated_at) VALUES('w_aot','Attack on Titan','x','x')")
    db.execute("""INSERT INTO release_line(id,work_id,medium,market,language,created_at,updated_at)
                  VALUES('rl_fr','w_aot','manga','FR','fr','x','x')""")
    db.execute("""INSERT INTO volume(id,release_line_id,number,created_at,updated_at)
                  VALUES('v1','rl_fr','1','x','x')""")
    for lang, title, kind in (("fr", "Liste des chapitres de L'Attaque des Titans", "official"),
                              ("ja", "進撃の巨人", "official"),
                              ("en", "Shingeki no Kyojin", "alias")):
        db.execute("INSERT INTO work_title(work_id,language,title,kind) VALUES('w_aot',?,?,?)", (lang, title, kind))
    db.commit(); db.close()
    real_dir, corr.DIR = corr.DIR, tempfile.mkdtemp(prefix="opentome-nocorr-")
    try:
        export(src_path, out_path)
    finally:
        corr.DIR = real_dir
    out = sqlite3.connect(out_path)
    rows = {a: (l, k) for a, l, k in out.execute("SELECT alias, language, kind FROM series_alias")}
    out.close()
    return rows


FIX_META = {}


def fixture_origin_line_pin():
    """Build a tiny pipeline DB with two same-work, same-medium JP manga lines --
    a main line and a spin-off whose line_name claim does not match either new
    EN line's own name (exactly the shape of the real Mushoku Tensei JP Roxy
    line, whose line_name is the French string cross-parsed from the FR
    Wikipedia table) -- then run the real corrections.apply_line_corrections()
    and export() against it. Returns (pinned EN rid, unpinned EN rid,
    {tome_id: orig_series_id}, {tome_id: gcd_series_id})."""
    tmp = tempfile.mkdtemp(prefix="opentome-originline-")
    src_path = os.path.join(tmp, "pipeline.db")
    out_path = os.path.join(tmp, "artifact.sqlite")
    db = sqlite3.connect(src_path)
    db.executescript(open(os.path.join(ROOT, "schema", "schema.sql"), encoding="utf8").read())
    db.execute("INSERT INTO work(id,primary_title,created_at,updated_at) VALUES('w_t','Test Work','x','x')")
    db.execute("""INSERT INTO release_line(id,work_id,medium,market,language,created_at,updated_at)
                 VALUES('rl_jp_main','w_t','manga','JP','ja','x','x')""")
    db.execute("""INSERT INTO release_line(id,work_id,medium,market,language,created_at,updated_at)
                 VALUES('rl_jp_spinoff','w_t','manga','JP','ja','x','x')""")
    db.execute("""INSERT INTO claim(entity,entity_id,field,value,source,licence,retrieved_at)
                 VALUES('release_line','rl_jp_spinoff','line_name','Something Else Entirely',
                        'wikipedia','facts_only','x')""")
    for num, date in (("1", "2019-01-01"), ("2", "2019-06-01")):
        db.execute("""INSERT INTO volume(id,release_line_id,number,release_date,release_date_precision,
                                        created_at,updated_at) VALUES(?,?,?,?,'day','x','x')""",
                  ("v_jpmain%s" % num, "rl_jp_main", num, date))
    for num, date in (("1", "2020-01-01"), ("2", "2020-06-01")):
        db.execute("""INSERT INTO volume(id,release_line_id,number,release_date,release_date_precision,
                                        created_at,updated_at) VALUES(?,?,?,?,'day','x','x')""",
                  ("v_jpspin%s" % num, "rl_jp_spinoff", num, date))
    db.commit()

    PINNED = {"work": "w_t", "market": "EN", "medium": "manga", "name": "Test Work Spin-off",
              "publisher": "Example Press", "origin_line": "rl_jp_spinoff",
              "volumes": [{"number": "1", "isbn13": "978-1-64505-000-1", "release_date": "2020-10-06", "contains": [1]},
                          {"number": "2", "isbn13": "9798888779347", "release_date": "2021-02-01", "contains": [2]}],
              "source_url": "https://example.test/pin", "checked": "2026-09-24"}
    UNPINNED = {"work": "w_t", "market": "EN", "medium": "manga", "name": "Test Work Unrelated",
                "publisher": "Example Press",
                "volumes": [{"number": "1", "isbn13": "978-1-64505-100-1", "release_date": "2020-10-06", "contains": [1]}],
                "source_url": "https://example.test/unpinned", "checked": "2026-09-24"}
    corr.apply_line_corrections(db, entries=[PINNED, UNPINNED], verbose=False)
    db.commit(); db.close()

    # export() also applies corrections/aliases.json (load_aliases /
    # load_alias_removals, imported from this same module) against whatever
    # DB it's exporting -- the real repo's aliases target real lines this
    # fixture doesn't have. Point corr.DIR at an empty directory for the
    # export call only; load_aliases/load_alias_removals resolve `DIR` at
    # call time, so to_mangarr.py's already-imported references see it too.
    real_dir, corr.DIR = corr.DIR, tempfile.mkdtemp(prefix="opentome-empty-corrections-")
    try:
        export(src_path, out_path)
    finally:
        corr.DIR = real_dir
    out = sqlite3.connect(out_path)
    pinned_rid = corr._id("rl_", "w_t", "manga", "EN", "Test Work Spin-off")
    unpinned_rid = corr._id("rl_", "w_t", "manga", "EN", "Test Work Unrelated")
    orig_of = dict(out.execute("SELECT tome_id, orig_series_id FROM series"))
    gcd_of = dict(out.execute("SELECT tome_id, gcd_series_id FROM series"))
    out.close()
    return pinned_rid, unpinned_rid, orig_of, gcd_of


if __name__ == "__main__":
    run()
