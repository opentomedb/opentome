"""Bind OpenTome's English lines to AniList ids (series.anilist_id).

    python3 export/resolve_anilist.py [build/manga-metadata.sqlite] [--dry-run] [--limit N] [--only NAME] [--covers | --covers-only | --display]

Mangarr resolves a series' poster / description / aliases from AniList by title, and the
2026-09-15 audit (mangarr: docs/superpowers/specs/2026-09-15-manga-metadata-audit.md) found
three of its 44 manga entries bound to a one-shot or an anthology that merely carried the
serial's title as a synonym. Mangarr now binds by id and consults the catalogue first, so
this step gives every English line the id up front, with the rules Mangarr's AniListRanker
applies (kept in step on purpose) plus FALLBACK tiers that run only where those rules find
nothing (R4 on; each measured by export/replay_anilist.py to move no existing bind). Mangarr
mirrors R4-R7 since 10.0.0.615 (2026-09-24); there R4/R5 also require the entry name to BE the
hinted catalogue line's own name, never an alias or arc title it was matched by:

  * candidates = AniList `Page(perPage: 10) { media(search:) }`, type MANGA; manga-family
    mediums query `format_not: NOVEL`, novel mediums (light_novel, novel) `format: NOVEL`
  * ONE_SHOT is never bound
  * the volume rule is ONE-SIDED (contract "Volume rule", the same in Mangarr's
    AniListRanker.VolumesAgree): a candidate SMALLER than the line's volume_count by more
    than max(3, 40 % of the line) is dropped (tolerance doubled while the candidate is
    RELEASING), and so is one LARGER than 4x the line; a larger count within 4x is never
    rejected. Junk (one-shots, anthologies) has fewer volumes than the serial; a larger
    AniList count is legitimate -- English 2-in-1 lines (Erased 9 vs 5, Vinland Saga 29 vs
    15) and lines where the catalogue lags an ongoing series. AniList leaves `volumes` null
    on most releasing series, and null is never compared. The 4x ceiling does not apply to
    a line of 1-2 volumes (R2, the 2026-09-15 live run): a one-book release or a run cut
    short binds the full Japanese serial (Pupa: 5 vs 1); the smaller-side rule still applies.
    That exemption is for the line's OWN name (and its de-slugged form) only -- an alias
    retry always keeps the ceiling (R3), or a spin-off's bare franchise alias binds the main
    serial ("Attack on Titan: Harsh Mistress of the City", 2 volumes, to "Attack on Titan",
    34, through "Shingeki no Kyojin")
  * primary-title equality (romaji / english / native) beats synonym equality; ties go to
    `popularity`; equality is Mangarr's TitleMatcher: lower-case letters and digits only,
    after fold() -- which key() and the outbound for_search() term share. fold() strips a
    combining accent ONLY from a Latin-script letter ("Fushigi Yûgi" = "Fushigi Yugi"); kana
    voicing marks, Hangul, CJK and Cyrillic are untouched (2026-09-24: the broad NFKD fold that
    also turned ゲ into ケ was reverted). PARITY: Mangarr's TitleMatcher.Normalize /
    TitleNormalizer.ForSearch do not fold yet -- they mirror fold() in a follow-up task; until
    then the two differ on accented titles only.
    fold() also turns a numeric symbol (No / Nl) into its NFKC form, the fraction slash into "/":
    "Ranma ½" is searched as "Ranma 1/2" (AniList's own romaji) and keys as ranma12; Ⅱ -> II, ² -> 2.
    A synonym-only carrier never wins while ANY candidate on the page has primary-title
    equality, even one the rules rejected (R1, the 2026-09-15 live run): a primary rejected
    on volumes says "this is the work but the count disagrees" (Doll: "DOLL" 1 vol vs 6, and
    the 4-volume "Onegai, Sore wo Yamenaide" carries "Doll" as a synonym), a same-named
    ONE_SHOT is that serial's pilot -- either way the carrier is a chapter title wearing the
    name, and unresolved is recoverable where a wrong bind is not
  * R7 (article, 2026-09-24; Mangarr since 10.0.0.615): below exact equality, the same primary-then-
    synonym equality after dropping one leading "the" / "a" / "an" (a whole word) from both
    sides, R1 included across tiers (never beside an exact primary-title candidate, even a
    rejected one). The catalogue's "Hollow Regalia" is AniList's "The Hollow Regalia"
    (133016) on its own novel page. Measured: that one line, nothing else moved
  * fallback tiers, tried only while the tiers above found nothing on the page (R5 needs no
    equal title on the page -- exact or R7 -- and R4 needs one, so the two never compete):
    - R5 (substring, 2026-09-24): no candidate on the page -- rejected or ONE_SHOT included,
      R1's reading -- key-equals the term, and exactly ONE volume-passing, non-ONE_SHOT
      candidate has a title / synonym key that contains the term's key or sits inside it
      (shorter side >= 4) AND `volumes` equal to the line's volume_count. The exact count is
      what makes it safe: "It's Just Not My Night" (3) is "...: Tale of a Fallen Vampire
      Queen" (3); AniList lists the Bookworm novel per Part, so the catalogue's longer
      "Ascendance of a Bookworm (Part 2: Apprentice Shrine Maiden)" (4) is the SHORTER
      "Ascendance of a Bookworm: Part 2" (4) while Parts 1/3/4/5 (3/5/9/12) share the base
      name. In that candidate-shorter direction the exact count plus uniqueness is the WHOLE
      guard -- any shorter franchise name inside the term qualifies on text alone (Re:Zero
      (A Week at the Mansion) matched 85814 through its synonym "ReZero"). Own-name terms only: allowed on alias terms it bound "Diamond Is Unbreakable"
      to Battle Angel Alita through the alias "Angelo" and moved an existing bind (replay,
      2026-09-24). Measured: 14 new, 1 changed (Der Werwolf: the alias-found 98367, null
      volumes, to 114483 "~Origins~", 11 = the line's 11 and its JP line's 11)
    - R4 (ceiling, 2026-09-24, Weed): an exact primary / synonym match (R1 still applies)
      rejected SOLELY by the 4x ceiling binds -- a short English run of the full Japanese
      serial (Weed: 3 English volumes, 34010 "Ginga Densetsu WEED" 60, synonym "WEED"; the
      old rule fell through to a franchise relative's alias and bound 38901). Own-name terms
      only (R3), and never over an equal-titled candidate that passes the ceiling, even a
      synonym carrier R1 rejected (Worst: 147044, 4 vols,
      stays; the right 31741 is a corrections/anilist.json pin, not a rule). Nor beside an
      article-equal (R7) candidate. Measured on opentome-2026-09-24: Weed plus 10 unbound
      lines, each an exact title; for 9 the AniList volume count equals the line's own origin
      line (Billy Bat 20, City Hunter 35, ...); Aria the Scarlet Ammo is the right work
      (47536, the main Hidan no Aria manga) with 16 vs the origin line's 26
  * no equality on the name -> D3 retry, in Mangarr's order: the de-slugged form of the name
    first (its slug with the dashes back as spaces -- Mangarr's foreign id); then (R6,
    2026-09-24; Mangarr since 10.0.0.615) the name without a trailing parenthetical that is an edition /
    format qualifier -- edition, volume list, release (re-release too), version, tankōbon,
    shinsōban, VizBig, 2-in-1, parution, printing; never one naming a chapter or a nested
    "series (" or a quoted title (`Amazing Agent Luna ("Amazing Agent Jennifer" Volume list)`
    names another work) -- ranked against the name page, else one search. The catalogue names sibling
    editions after Wikipedia's headings ("Inuyasha (VizBig edition)", "Ranma ½ (2014 English
    release (2-in-1 Edition)"), and AniList has one entry for the work. It is ranked like an
    ALIAS (R3, no fallback tiers), not like the name: stripping can drop content, and the
    R3 failure is exactly what it would do -- "Sailor Moon (Shinsōban short stories)", 2
    volumes, bound the 18-volume serial through the bare "Sailor Moon" under R2 (its own
    entry is "Sailor Moon Short Stories"). Measured: 9 new, each the id a sibling edition
    of the same line already carries; the own-name reading added Jiraishin and that wrong
    Sailor Moon bind. Then the line's aliases -- EVERY alias (series_alias in stored order, one per normalized form, Wikipedia
    list-article names skipped), each ranked against the page the name search already fetched
    at no cost, and a fresh search only for the first ALIAS_LIMIT = 3 that miss that page,
    ranked against its own page (Mangarr's AniListService.FindSeries: aliases are walked, only
    SEARCHES are capped). There is no fuzzy pass: the fallback tiers each demand an exact
    title or an exact volume count, and a line none of them reaches stays NULL for Mangarr's
    own ranked search at add time. A guess here would be pinned by every future add.
  * post-walk tiers (round 2, 2026-09-24; post_walk()): only for a line STILL unbound after the whole
    walk above, and only over the pages the walk already fetched -- the name page, then every page a
    retry term searched (de-slugged form, R6, aliases), each with the own-name flag it was searched
    under. Zero new queries, and never ahead of an earlier tier: a line any tier above bound is
    skipped. Catalogue-side only -- Mangarr does not mirror them; it reads the id this step writes.
    Tried in order V1 -> V2 -> V3 -> V4, the first hit binds:
    - V1 prefix (via 'prefix'): the name is the head of AniList's full title ("Even Dogs Go to Other
      Worlds" is "...: Life in Another World with My Beloved Hound"). Gate: the line has >= 3
      volumes; a BARE name only (no `(`, no ` (` / `: ` / ` - ` / ` / ` cut); own-name pages only; the
      term's key >= 6 characters; nothing on the page title-equals the term (exact or R7, rejected
      and ONE_SHOT candidates included). Exactly ONE non-ONE_SHOT candidate has a title / synonym
      whose words start with the term's words plus a word boundary -- counted BEFORE the volume rule
      (Kase-san: "Kase-san and..." (5 vols) and "Kase-san and Yamada" both start so, and filtering
      the 5 out first would bind Yamada) -- and it passes pick()'s volume rule with `volumes` null
      or >= the line's (Your Name's "Another Side: Earthbound", 1 vol, never). Shino & Ren (1-vol
      LN) -> "Shino & Ren: Future" is what the gate keeps out
    - V2 arc (via 'arc'): the name has a real arc part (arc_parts(): the name after its first cut,
      parentheses dropped; an R6 edition qualifier is not one), base and arc keys each >= 4, and
      exactly ONE candidate passing the volume rule has a title / synonym containing BOTH keys with
      `volumes` equal to the line's count or to its origin line's (Umineko's English 3-volume
      "Alliance of the Golden Witch" is AniList's 6-volume Episode 4, the JP line's 6). Base-only
      containment never binds: without the arc the Jiraishin line bound "Jiraishin Diablo" (3 = 3)
      and Index NT bound Index (22 = the JP line's 22)
    - V3 amp (via 'amp'): an equality tier like R7 with '&' read as 'and' ("Sword Art Online: Kiss &
      Fly" = "...: Kiss and Fly"), for a term that has either. PRIMARY titles only -- the one synonym
      match measured was the doubtful Shino & Ren -> "Shino & Ren: Future" (synonym "Shino and
      Ren") -- never beside a candidate whose title exactly key-equals the term (rejected ones
      included), volume rule kept, ties to popularity
    - V4 origin (via 'origin'): on a RETRY term's page (never the name page), exactly one non-
      ONE_SHOT candidate key-equals the term, was rejected only by the 4x ceiling (`volumes` > 4x
      the line's) and has `volumes` equal to the origin line's count -- a short English run of the
      full Japanese serial, which R4 cannot reach off the name page (Jiraishin, Tokyopop, 3 vols ->
      30379 "Jiraishin", 19 = the JP line's 19; Crayon Shin-chan CMX 11 -> 32435, 50). Gate: the
      line has >= 3 volumes (Angel Beats! (Related media), 1 vol, bound Heaven's Door without it)
    Measured (export/replay_anilist.py --base main on opentome-2026-09-24): 52 new binds -- V1 26,
    V2 19, V3 5, V4 2 -- 0 changed, 0 lost; no new id is another work's EN line's, no two share one.

DISPLAY ONLY (2026-09-24, `--display`, after the pins): series.display_anilist_id / _via give a
line the rules leave NULL a cover / synopsis source -- its bound parent line's id ('parent') or
the manga-family entry of a novel AniList lists only as an adaptation ('medium'). Never a
binding and never read by Mangarr; see display().

Polite by construction: one request per MIN_INTERVAL, up to BATCH searches per request as
GraphQL aliases, every search cached on disk per (term, family) under .cache/anilist/ so a
rebuild re-runs with zero network for every name already seen. Idempotent: only rows whose
anilist_id IS NULL are considered, and only resolved ones are written. Clean room: AniList
is a lookup-key source here (an id, and with --covers a cover URL) -- no title, synonym or
description ever enters the artifact.
"""
import argparse, hashlib, json, os, re, sqlite3, sys, time, unicodedata, urllib.error, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "https://graphql.anilist.co"
UA = ("opentome-anilist-resolver/0.1 "
      "(non-commercial catalogue; https://github.com/DrAwesome441)")
CACHE = os.environ.get("ANILIST_CACHE", os.path.join(ROOT, ".cache", "anilist"))
OFFLINE = os.environ.get("ANILIST_OFFLINE", "0") == "1"   # tests: a cache miss is an error, never a request
MIN_INTERVAL = 2.1          # seconds between requests: under AniList's degraded 30/min
BATCH = 8                   # searches per request (GraphQL aliases) -- the audit's proven batch shape
PER_PAGE = 10
ALIAS_LIMIT = 3             # fresh alias SEARCHES per line -- every alias is page-ranked for free (the
                            # de-slugged form is a separate, earlier retry); Mangarr's MaxAliasSearches
NOVEL_MEDIUMS = ("light_novel", "novel")
LIST_PREFIXES = ("list of ", "liste des ", "plot of ")
VIAS = ("primary", "synonym", "article", "substring", "ceiling", "alias",   # pick()'s tiers on the name page, or a retry term
        "prefix", "arc", "amp", "origin")                                   # the post-walk tiers (post_walk())
FIELDS = "id format volumes chapters popularity status title { romaji english native } synonyms"
_last = [0.0]


class OfflineMiss(RuntimeError):
    """ANILIST_OFFLINE=1 and a term (or cover id) has no cached response. `terms` names them
    so the offline test can report a fixture gap instead of aborting the pipeline's step 0."""

    def __init__(self, terms):
        self.terms = list(terms)
        super().__init__("ANILIST_OFFLINE=1 and no cached response for %s (re-record the fixtures: "
                         "ANILIST_RECORD=1 python3 export/test_resolve_anilist.py)" % ", ".join(map(repr, self.terms)))


# ---------------------------------------------------------------- Mangarr mirrors

def _latin(c):
    return c.isalpha() and "LATIN" in unicodedata.name(c, "")


def strip_latin_marks(s):
    """Latin-only accent strip (2026-09-24): NFD, a combining mark (Mn) dropped ONLY when its base
    letter is Latin-script, then NFC -- "Fushigi Y\u00fbgi" -> "Fushigi Yugi", "\u00dcbel Blatt" ->
    "Ubel Blatt", "\u014coku" -> "Ooku". Kana voicing marks, Hangul, Cyrillic (\u0439), CJK keep theirs;
    a string with nothing to drop comes back as it was, byte for byte."""
    out, base, dropped = [], "", False
    for c in unicodedata.normalize("NFD", s):
        if unicodedata.category(c) == "Mn":
            if _latin(base):
                dropped = True
                continue
        else:
            base = c
        out.append(c)
    return unicodedata.normalize("NFC", "".join(out)) if dropped else s


def fold_numeric(s):
    """Numeric-symbol fold (2026-09-24): a character in Unicode category No / Nl becomes its NFKC form,
    and the fraction slash (U+2044) becomes "/" -- "Ranma \u00bd" -> "Ranma 1/2", AniList's own spelling
    (key() drops the "/": ranma12), "\u2161" -> "II", "x\u00b2" -> "x2". Nothing else is NFKC'd (no
    full-width, no ligatures)."""
    return "".join(unicodedata.normalize("NFKC", c) if unicodedata.category(c) in ("No", "Nl") else c
                   for c in s).replace("\u2044", "/")


def fold(s):
    """The one normalization key() and for_search() share (Mangarr mirrors it in TitleMatcher.Normalize
    and TitleNormalizer.ForSearch in a follow-up task)."""
    return fold_numeric(strip_latin_marks(s or ""))


def key(s):
    """Mangarr's TitleMatcher.Normalize: lower-case, letters and digits only -- after fold()."""
    return "".join(c for c in fold(s).lower() if c.isalnum())


def for_search(s):
    """Mangarr's TitleNormalizer.ForSearch: typographic quotes/dashes/NBSP -> ASCII, spaces collapsed,
    fold()ed -- so deslug()'s ASCII-only slug keeps the letter ("fushigi yugi", not "fushigi y gi")."""
    s = fold(s).replace("\u2018", "'").replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"')
    s = s.replace("\u2013", "-").replace("\u2014", "-").replace("\u00a0", " ")
    return " ".join(s.split())


ARTICLE = re.compile(r"^(?:the|a|an)\s+", re.I)


def art_key(s):
    """R7: key() after dropping one leading English article ("The Hollow Regalia" -> hollowregalia)."""
    return key(ARTICLE.sub("", for_search(s)))


def pick(cands, term, volume_count, own_name=True):
    """Mangarr's AniListRanker.Pick, plus the fallback tiers in the module docstring.
    (media | None, via | None, rejections); via is 'primary', 'synonym' or the fallback
    tier that bound it ('article', 'substring', 'ceiling'). own_name is False for an alias retry (R3: the volume ceiling
    then always holds, and no fallback tier runs)."""
    k = key(term)

    def primary_title(m):
        t = m.get("title") or {}
        return bool(k) and k in (key(t.get("romaji")), key(t.get("english")), key(t.get("native")))

    def synonym_title(m):
        return bool(k) and any(key(s) == k for s in m.get("synonyms") or [])

    ak = art_key(term)

    def article_primary(m):
        t = m.get("title") or {}
        return bool(ak) and ak in (art_key(t.get("romaji")), art_key(t.get("english")), art_key(t.get("native")))

    def article_synonym(m):
        return bool(ak) and any(art_key(s) == ak for s in m.get("synonyms") or [])

    def contains(m):
        """R5: a title key contains the term's key or sits inside it, shorter side >= 4."""
        t = m.get("title") or {}
        for x in (t.get("romaji"), t.get("english"), t.get("native"), *(m.get("synonyms") or [])):
            x = key(x)
            if min(len(x), len(k)) >= 4 and (k in x or x in k):
                return True
        return False

    primary_on_page = any(primary_title(m) for m in cands)   # R1: counts rejected candidates too
    article_on_page = primary_on_page or any(article_primary(m) for m in cands)   # R1 for R7
    equality_on_page = article_on_page or any(synonym_title(m) or article_synonym(m) for m in cands)
    primary, synonym, rejected, oversized, substring = [], [], [], [], []
    art_primary, art_synonym, carrier = [], [], False
    for m in cands:
        if m.get("format") == "ONE_SHOT":
            rejected.append("%s:ONE_SHOT" % m["id"])
            continue
        v = m.get("volumes")
        if v and volume_count and volume_count > 0:
            tol = max(3, 0.4 * volume_count)
            if m.get("status") == "RELEASING":
                tol *= 2
            if volume_count - v > tol:
                rejected.append("%s:volumes %s vs %s" % (m["id"], v, volume_count))
                continue
            if (volume_count > 2 or not own_name) and v > 4 * volume_count:   # R2 / R3
                rejected.append("%s:volumes %s > 4x %s" % (m["id"], v, volume_count))
                if own_name and (primary_title(m) or synonym_title(m)):
                    oversized.append(m)   # R4: rejected SOLELY by the ceiling
                continue
        if primary_title(m):
            primary.append(m)
        elif synonym_title(m):
            if primary_on_page:
                rejected.append("%s:synonym only (a primary-title candidate is on the page)" % m["id"])
                carrier = True   # passed the ceiling: R4 must not outrank it either
            else:
                synonym.append(m)
        elif article_primary(m):
            art_primary.append(m)
        elif article_synonym(m):
            if article_on_page:
                rejected.append("%s:synonym only (a primary-title candidate is on the page)" % m["id"])
            else:
                art_synonym.append(m)
        elif own_name and v and v == volume_count and contains(m):
            substring.append(m)
    pool = primary or synonym
    if pool:
        via = "primary" if primary else "synonym"
    elif (art_primary or art_synonym) and not primary_on_page:
        pool, via = art_primary or art_synonym, "article"   # R7: below exact equality, R1 across tiers
    elif not equality_on_page and len(substring) == 1:
        # R5: no equality anywhere on the page (R1's reading: a rejected equal title is the
        # work with a disputed count, so a substring candidate beside it is a side story)
        pool, via = substring, "substring"
    elif not carrier and not (art_primary or art_synonym):
        # R4 (Weed): only when nothing equal passed the ceiling -- an R1-rejected synonym carrier
        # or an article-equal candidate counts as passing -- and R1 still holds inside the tier
        pool = [m for m in oversized if primary_title(m)] or \
               ([] if primary_on_page else [m for m in oversized if synonym_title(m)])
        via = "ceiling"
    if not pool:
        return None, None, rejected
    best = max(pool, key=lambda m: m.get("popularity") or 0)   # stable: first in AniList order on a tie
    return best, via, rejected


def alias_terms(name, aliases):
    """The alias walk: every alias in stored order, one per normalized form, never the name
    itself, never a Wikipedia list-article name. Not capped -- only fresh searches are
    (ALIAS_LIMIT, in resolve). `seen` starts with the name's key, its de-slugged key and the key of
    the exporter's ASCII normalize() form (to_mangarr.normalize: "Fushigi Y\u00fbgi" -> "fushigi y gi"),
    so a stored, already-normalized copy of the name never burns a fresh search (2026-09-24)."""
    seen, out = {key(name), key(deslug(name)), key(ascii_normalize(name))}, []
    for a in aliases:
        a = for_search(a)
        k = key(a)
        if not k or k in seen or a.lower().startswith(LIST_PREFIXES):
            continue
        seen.add(k)
        out.append(a)
    return out


def ascii_normalize(s):
    """to_mangarr.normalize(): lower-case, every run of non-[a-z0-9] one space -- how the exporter
    stores a name's ASCII alias row."""
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def deslug(name):
    """Mangarr's de-slugged foreign id for a name: the slug with its dashes back as spaces
    (`Let's Do It Already!` -> `let s do it already`). Same key as the name; a different
    search term, which is the point."""
    return re.sub(r"[^a-z0-9]+", "-", for_search(name).lower()).strip("-").replace("-", " ")


# R6: what a trailing parenthetical may say for the name without it to still be the line's own
# name -- an edition / format / printing qualifier, never an arc ("chapter") or a nested series
EDITION_QUALIFIER = re.compile(r"edition|volume list|release|version|tank[o\u014d]bon|shins[o\u014d]ban|"
                               r"vizbig|2-in-1|parution|printing", re.I)


def edition_stripped(name):
    """R6: the name without a trailing edition-qualifier parenthetical, or None.
    `Inuyasha (VizBig edition)` -> `Inuyasha`; an unclosed outer parenthetical goes too
    (`Ranma ½ (2014 English release (2-in-1 Edition)` -> `Ranma ½`)."""
    s = for_search(name)
    m = re.search(r"\s*\(([^()]*)\)\s*$", s)
    if not m:
        return None
    base, inner = s[:m.start()], m.group(1)
    if base.count("(") > base.count(")"):
        i = base.rfind("(")
        base, inner = base[:i], base[i + 1:] + "(" + inner + ")"
    base, low = base.strip(), inner.lower()
    if not base or "chapter" in low or "series (" in low or any(q in inner for q in '"\u201c\u201d') \
            or not EDITION_QUALIFIER.search(inner):
        return None
    return base


def retry_terms(ln):
    """D3 order: the de-slugged form first, then the edition-stripped name (R6), then the aliases."""
    return [deslug(ln["name"])] + [t for t in [edition_stripped(ln["name"])] if t] + \
        alias_terms(ln["name"], ln["aliases"])


# ---------------------------------------------------------------- HTTP + cache

def _throttle():
    wait = MIN_INTERVAL - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()


def _post(body, retries=4):
    """One throttled POST with backoff on 429 (Retry-After honoured) and 5xx. 4xx raises."""
    if OFFLINE:   # backstop; search() and covers() raise OfflineMiss with the terms first
        raise OfflineMiss(["<request>"])
    data = json.dumps(body).encode()
    delay = 5.0
    for attempt in range(retries):
        _throttle()
        req = urllib.request.Request(API, data=data, headers={
            "Content-Type": "application/json", "Accept": "application/json", "User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if attempt < retries - 1 and e.code == 429:
                time.sleep(float(e.headers.get("Retry-After") or delay))
                delay *= 2
                continue
            if attempt < retries - 1 and e.code in (500, 502, 503, 504):
                time.sleep(delay)
                delay *= 2
                continue
            raise
    raise RuntimeError("exhausted retries")


def _cache_path(kind, family, term):
    """Readable, unique: kind-family-slug-hash.json (the slug is for humans, the hash for uniqueness)."""
    os.makedirs(CACHE, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", term.lower()).strip("-")[:60] or "x"
    h = hashlib.sha256(("%s|%s|%s" % (kind, family, term)).encode()).hexdigest()[:10]
    return os.path.join(CACHE, "%s-%s-%s-%s.json" % (kind, family, slug, h))


def _cache_get(path):
    if os.path.exists(path):
        with open(path, encoding="utf8") as f:
            return json.load(f)
    return None


def _cache_put(path, value):
    with open(path, "w", encoding="utf8") as f:
        json.dump(value, f, ensure_ascii=False)


def _search_query(n, novel):
    fmt = "format: NOVEL" if novel else "format_not: NOVEL"
    args = ", ".join("$s%d: String" % i for i in range(n))
    body = " ".join("q%d: Page(perPage: %d) { media(search: $s%d, type: MANGA, %s) { %s } }"
                    % (i, PER_PAGE, i, fmt, FIELDS) for i in range(n))
    return "query (%s) { %s }" % (args, body)


def _fetch_chunk(chunk, novel):
    """{term: [media]} for one request; halves the batch on a 400 (query complexity /
    validation) instead of guessing AniList's limit."""
    try:
        data = _post({"query": _search_query(len(chunk), novel),
                      "variables": {"s%d" % i: t for i, t in enumerate(chunk)}})
    except urllib.error.HTTPError as e:
        if e.code == 400 and len(chunk) > 1:
            half = len(chunk) // 2
            out = _fetch_chunk(chunk[:half], novel)
            out.update(_fetch_chunk(chunk[half:], novel))
            return out
        raise
    if data.get("errors") and not data.get("data"):
        raise RuntimeError("AniList: %s" % data["errors"][0].get("message"))
    out = {}
    for i, t in enumerate(chunk):
        page = (data.get("data") or {}).get("q%d" % i) or {}
        out[t] = page.get("media") or []
    return out


def search(terms, novel):
    """{term: [media]} for every term -- cache first, the misses batched BATCH per request."""
    family = "novel" if novel else "manga"
    out, todo = {}, []
    for t in dict.fromkeys(terms):
        cached = _cache_get(_cache_path("search", family, t))
        if cached is None:
            todo.append(t)
        else:
            out[t] = cached
    if todo and OFFLINE:
        raise OfflineMiss(todo)
    for i in range(0, len(todo), BATCH):
        fetched = _fetch_chunk(todo[i:i + BATCH], novel)
        for t, media in fetched.items():
            _cache_put(_cache_path("search", family, t), media)
        out.update(fetched)
    return out


# ---------------------------------------------------------------- lines

def load_line(db, sid):
    r = db.execute("SELECT gcd_series_id, name, medium, volume_count, anilist_id FROM series WHERE gcd_series_id=?",
                   (sid,)).fetchone()
    if not r:
        return None
    ln = dict(zip(("id", "name", "medium", "volume_count", "anilist_id"), r))
    ln["aliases"] = [a for (a,) in db.execute("SELECT alias FROM series_alias WHERE gcd_series_id=? ORDER BY rowid", (sid,))]
    ln["novel"] = ln["medium"] in NOVEL_MEDIUMS
    o = db.execute("""SELECT o.volume_count FROM series s JOIN series o ON o.gcd_series_id = s.orig_series_id
                      WHERE s.gcd_series_id=? AND o.gcd_series_id != s.gcd_series_id""", (sid,)).fetchone()
    ln["orig_vc"] = o[0] if o and o[0] else None   # the origin (JP) line's count, for the post-walk tiers
    return ln


def load_lines(db, limit=None, only=None):
    """English lines still without an id, most volumes first (they are the ones people add)."""
    where, params = "language='en' AND anilist_id IS NULL", []
    if only:
        where += " AND name=? COLLATE NOCASE"
        params.append(only)
    sql = "SELECT gcd_series_id FROM series WHERE %s ORDER BY volume_count DESC, gcd_series_id" % where
    if limit:
        sql += " LIMIT %d" % int(limit)
    return [load_line(db, sid) for (sid,) in db.execute(sql, params).fetchall()]


def _search_round(todo, novel):
    """One batched round of fresh searches: (line, term, own_name) triples, each ranked against
    its own page only (Mangarr ranks an alias against the name page, then its fresh page)."""
    if not todo:
        return
    results = search([t for _, t, _ in todo], novel)
    for ln, t, own in todo:
        ln["fetched"].append((t, results[t], own))   # post_walk() ranks these pages again, at no cost
        m, via, rej = pick(results[t], t, ln["volume_count"], own_name=own)
        ln["rejected"] += rej
        if m:   # a fallback tier (own-name terms: the de-slugged form) is reported as itself
            ln.update(pick=m, via=via if via in ("substring", "ceiling") else "alias", term=t)


def _next_alias_search(ln):
    """Mangarr's alias walk, resumed from the line's cursor: each alias is ranked against the
    name page at no cost (a hit binds the line and stops); a miss is the next fresh search
    while the line still has one of its ALIAS_LIMIT searches, otherwise the walk goes on
    page-ranking the remaining aliases. Returns the term to search, or None."""
    terms = alias_terms(ln["name"], ln["aliases"])
    while ln["cursor"] < len(terms):
        t = terms[ln["cursor"]]
        ln["cursor"] += 1
        m, via, _ = pick(ln["page"], t, ln["volume_count"], own_name=False)
        if m:
            ln.update(pick=m, via="alias", term=t)
            return None
        if ln["searches"] < ALIAS_LIMIT:
            ln["searches"] += 1
            return t
    return None


def resolve(lines):
    """Sets pick / via / term / rejected on every line. One batched pass on the names; then,
    for whatever is still unresolved, the de-slugged form (own name: ranked against the name
    page, else one search); then the edition-stripped name (R6, the same way); then Mangarr's alias walk (_next_alias_search) in batched rounds --
    every alias page-ranked for free, at most ALIAS_LIMIT fresh searches per line, each
    ranked against its own page. Only a page miss costs a request. Last, post_walk() on each family's
    still-unbound lines, over the pages already fetched (no request)."""
    for novel in (False, True):
        group = [ln for ln in lines if ln["novel"] == novel]
        if not group:
            continue
        results = search([for_search(ln["name"]) for ln in group], novel)
        for ln in group:
            term = for_search(ln["name"])
            ln["page"] = list(results[term])
            m, via, rej = pick(ln["page"], term, ln["volume_count"])
            ln.update(pick=m, via=via, term=term, rejected=rej, searches=0, cursor=0, fetched=[])
        todo = []
        for ln in group:
            if ln["pick"]:
                continue
            t = deslug(ln["name"])
            m, via, _ = pick(ln["page"], t, ln["volume_count"])
            if m:
                ln.update(pick=m, via="alias", term=t)
            else:
                todo.append((ln, t, True))
        _search_round(todo, novel)
        todo = []
        for ln in group:   # R6: ranked like an alias (R3 -- see the module docstring)
            t = None if ln["pick"] else edition_stripped(ln["name"])
            if not t:
                continue
            m, via, _ = pick(ln["page"], t, ln["volume_count"], own_name=False)
            if m:
                ln.update(pick=m, via="alias", term=t)
            else:
                todo.append((ln, t, False))
        _search_round(todo, novel)
        while True:
            todo = []
            for ln in group:
                if ln["pick"]:
                    continue
                t = _next_alias_search(ln)
                if t:
                    todo.append((ln, t, False))
            if not todo:
                break
            _search_round(todo, novel)
        post_walk(group)
    return lines


# ---------------------------------------------------------------- post-walk tiers

def _titles(m):
    t = m.get("title") or {}
    return [x for x in (t.get("romaji"), t.get("english"), t.get("native"), *(m.get("synonyms") or [])) if x]


def _words(s):
    """Lower-case ASCII words, one space apart -- V1's word-boundary prefix test."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", for_search(s).lower()).split())


def _amp_key(s):
    """V3: key() with every '&' read as 'and' ("Kiss & Fly" = "Kiss and Fly")."""
    return key(re.sub(r"\s*&\s*", " and ", for_search(s or "")))


def volumes_pass(m, volume_count, own_name):
    """pick()'s volume rule for one candidate, unchanged (ONE_SHOT, the smaller side, the 4x
    ceiling with R2 / R3): True when pick() would not reject it on format or volumes."""
    if m.get("format") == "ONE_SHOT":
        return False
    v = m.get("volumes")
    if v and volume_count and volume_count > 0:
        tol = max(3, 0.4 * volume_count) * (2 if m.get("status") == "RELEASING" else 1)
        if volume_count - v > tol:
            return False
        if (volume_count > 2 or not own_name) and v > 4 * volume_count:
            return False
    return True


def arc_parts(name):
    """V2: (base, arc) -- base is the name before its first ` (` / `: ` / ` - ` / ` / ` cut, arc the
    rest with its parentheses dropped (`Re:Zero (Truth of Zero)` -> `Re:Zero`, `Truth of Zero`).
    An edition-qualified name (R6) has no arc: (the stripped name, None); so has a name without a cut."""
    s = for_search(name)
    ed = edition_stripped(name)
    if ed:
        return ed, None
    m = DISPLAY_CUT.search(s)
    if not m or m.start() == 0:
        return s, None
    rest = " ".join(s[m.end():].replace("(", " ").replace(")", " ").split())
    return s[:m.start()], rest or None


def post_walk_pick(ln, pages):
    """The post-walk tiers for one line the walk left unbound, in order V1 -> V2 -> V3 -> V4, over
    `pages` = [(term, page, own_name)]: the name page first, then every page the walk fetched, in
    walk order. (media, via, term) or (None, None, None). See the module docstring."""
    vc, orig = ln["volume_count"], ln.get("orig_vc")
    name = ln["name"]
    # V1 prefix: a bare name that is the head of AniList's full title
    if vc and vc >= 3 and "(" not in name and parent_name(name) is None:
        for t, page, own in pages:
            if not own or len(key(t)) < 6 or equal_title_on_page(page, t):
                continue
            w = _words(t) + " "
            c = [m for m in page if m.get("format") != "ONE_SHOT" and any(_words(x).startswith(w) for x in _titles(m))]
            if len(c) == 1 and volumes_pass(c[0], vc, own) and (not c[0].get("volumes") or c[0]["volumes"] >= vc):
                return c[0], "prefix", t
    # V2 arc: base AND arc inside one title, count = the line's or its (different) origin line's
    base, arc = arc_parts(name)
    kb, ka = key(base), key(arc) if arc else ""
    if len(kb) >= 4 and len(ka) >= 4:
        counts = {vc, orig} - {None, 0}
        for t, page, own in pages:
            c = [m for m in page if volumes_pass(m, vc, own) and m.get("volumes") in counts
                 and any(kb in key(x) and ka in key(x) for x in _titles(m))]
            if len(c) == 1:
                return c[0], "arc", t
    # V3 amp: '&' = 'and', an equality tier like R7 -- primary titles only, never beside an exact
    # title (rejected ones included)
    for t, page, own in pages:
        if "&" not in t and " and " not in t.lower():
            continue
        k, ak = key(t), _amp_key(t)
        if any(key(x) == k for m in page for x in _titles(m)):
            continue
        pool = [m for m in page if volumes_pass(m, vc, own)
                and ak in [_amp_key(x) for x in (m.get("title") or {}).values() if x]]
        if pool:
            return max(pool, key=lambda m: m.get("popularity") or 0), "amp", t
    # V4 origin: on a retry term, an equal title rejected only by the 4x ceiling whose AniList count
    # is the origin line's
    if vc and vc >= 3 and orig and orig != vc:
        for t, page, own in pages[1:]:
            k = key(t)
            c = [m for m in page if m.get("format") != "ONE_SHOT" and m.get("volumes") == orig
                 and orig > 4 * vc and any(key(x) == k for x in _titles(m))]
            if len(c) == 1:
                return c[0], "origin", t
    return None, None, None


def post_walk(group):
    """Run the post-walk tiers on every line of `group` still unbound after the whole walk: the
    pages are the ones the walk already fetched (zero new queries), and a bind here never
    pre-empts an earlier tier -- a line any of them bound is skipped."""
    for ln in group:
        if ln["pick"]:
            continue
        m, via, t = post_walk_pick(ln, [(for_search(ln["name"]), ln["page"], True)] + ln["fetched"])
        if m:
            ln.update(pick=m, via=via, term=t)


def write(db, lines, dry_run):
    n = 0
    for ln in lines:
        if ln["pick"] and not dry_run:
            db.execute("UPDATE series SET anilist_id=? WHERE gcd_series_id=? AND anilist_id IS NULL",
                       (ln["pick"]["id"], ln["id"]))
            n += 1
    if not dry_run:
        db.commit()
    return n


def report(lines, path):
    with open(path, "w", encoding="utf8") as f:
        f.write("name\tmedium\tpicked id\ttitle\tvia\trejected\n")
        for ln in lines:
            m = ln["pick"] or {}
            t = m.get("title") or {}
            f.write("\t".join([ln["name"], ln["medium"] or "", str(m.get("id") or ""),
                               t.get("english") or t.get("romaji") or "", ln["via"] or "unresolved",
                               "; ".join(ln["rejected"])]) + "\n")


# ---------------------------------------------------------------- display fallback

DISPLAY_VIAS = ("parent", "medium")
DISPLAY_CUT = re.compile(r" \(|: | - | / ")


def parent_name(name):
    """The name before its first ` (`, `: `, ` - ` or ` / ` (dashes as for_search() writes them):
    an arc / side-story line's parent (`Re:Zero (Truth of Zero)` -> `Re:Zero`). None without a cut,
    so a whole-name twin (the LN `Bungo Stray Dogs` beside the bound manga) is never a 'parent'."""
    s = for_search(name)
    m = DISPLAY_CUT.search(s)
    return s[:m.start()] if m and m.start() > 0 else None


def equal_title_on_page(page, term):
    """Any candidate -- rejected or ONE_SHOT included -- whose title or synonym key-equals the
    term, with or without one leading article (pick()'s exact and R7 equality)."""
    k, ak = key(term), art_key(term)
    for m in page:
        for x in [*(m.get("title") or {}).values(), *(m.get("synonyms") or [])]:
            if (k and key(x) == k) or (ak and art_key(x) == ak):
                return True
    return False


def display(db):
    """series.display_anilist_id / display_anilist_via for EN lines the resolver left NULL --
    a cover / synopsis for the browser, NEVER a binding: it is never copied into anilist_id,
    never used for aliases, and Mangarr (which names its columns) never reads it. Recomputed
    from scratch, so it runs after corrections/anilist.json's pins (stage 8a's third call, before
    --covers-only): a pinned line has an id and gets none.

      * parent -- the line's name cut at its first ` (` / `: ` / ` - ` / ` / ` key-equals the
        name of a BOUND EN line of the same work (tome_work_id; any medium -- the catalogue's
        `Re:Zero (Truth of Zero)` manga is an arc of the bound `Re:Zero` light novel): that
        line's id. Never across works; never when the bound same-work lines of that name carry
        different ids (DanMachi's side stories: the manga 85161 and the novel 85162).
      * medium -- a novel / light_novel line with no parent candidate whose OWN (format: NOVEL)
        name page carries no title-equal candidate, rejected ones included (R1's reading: an
        equal NOVEL entry is the work with a disputed count -- Hollow Regalia's case, bound by
        R7 since), but whose manga-family page for the same name gives pick() a candidate
        (Otherside Picnic, Bungo Stray Dogs, Bride of the Barrier Master, Pretty Boy Detective
        Club -- the 2026-09-24 analysis; AniList has the adaptation, not the novel). The
        novel pages are the resolver's own (cached); the manga-family pages are one polite
        cached search() per name, bounded to these lines.

    Returns {via: rows written}."""
    db.execute("UPDATE series SET display_anilist_id=NULL, display_anilist_via=NULL")
    rows = db.execute("""SELECT gcd_series_id, name, medium, volume_count, anilist_id, tome_work_id
                         FROM series WHERE language='en'""").fetchall()
    bound = {}
    for sid, name, medium, vc, aid, wid in rows:
        if aid:
            bound.setdefault((wid, key(name)), set()).add(aid)
    picks, novel = {}, []
    for sid, name, medium, vc, aid, wid in rows:
        if aid:
            continue
        p = parent_name(name)
        ids = bound.get((wid, key(p)), set()) if p else set()
        if len(ids) == 1:
            picks[sid] = (next(iter(ids)), "parent")
        elif not ids and medium in NOVEL_MEDIUMS:
            novel.append((sid, for_search(name), vc))
    if novel:
        terms = [t for _, t, _ in novel]
        own, manga = search(terms, True), search(terms, False)
        for sid, t, vc in novel:
            m = None if equal_title_on_page(own[t], t) else pick(manga[t], t, vc)[0]
            if m:
                picks[sid] = (m["id"], "medium")
    for sid, (aid, via) in picks.items():
        db.execute("""UPDATE series SET display_anilist_id=?, display_anilist_via=?
                      WHERE gcd_series_id=? AND anilist_id IS NULL""", (aid, via, sid))
    db.commit()
    return {v: sum(1 for _, x in picks.values() if x == v) for v in DISPLAY_VIAS}


# ---------------------------------------------------------------- covers

def _cover_query(n):
    args = ", ".join("$i%d: Int" % i for i in range(n))
    body = " ".join("c%d: Media(id: $i%d) { id coverImage { large } }" % (i, i) for i in range(n))
    return "query (%s) { %s }" % (args, body)


def covers(db, path):
    """{anilist_id: cover url} for every EN line with an id -- bound, or a display id (the
    display fallback) -- and no ISBN-keyed volume cover of its own: what the browser's series
    card falls back to. Merged into `path`; an id already there (or cached) is never
    re-fetched. Returns (ids in the file, ids fetched)."""
    have = _cache_get(path) or {}
    ids = [i for (i,) in db.execute("""SELECT DISTINCT COALESCE(s.anilist_id, s.display_anilist_id) AS i
              FROM series s WHERE s.language='en' AND i IS NOT NULL AND NOT EXISTS (SELECT 1 FROM volumes v
              WHERE v.gcd_series_id=s.gcd_series_id AND v.cover_url IS NOT NULL) ORDER BY 1""")]
    todo = []
    for aid in ids:
        if str(aid) in have:
            continue
        c = _cache_get(_cache_path("cover", "id", str(aid)))
        if c is None:
            todo.append(aid)
        elif c:
            have[str(aid)] = c
    if todo and OFFLINE:
        raise OfflineMiss(todo)
    for i in range(0, len(todo), BATCH):
        chunk = todo[i:i + BATCH]
        data = _post({"query": _cover_query(len(chunk)), "variables": {"i%d" % j: aid for j, aid in enumerate(chunk)}})
        for j, aid in enumerate(chunk):
            m = (data.get("data") or {}).get("c%d" % j) or {}
            url = (m.get("coverImage") or {}).get("large") or ""
            _cache_put(_cache_path("cover", "id", str(aid)), url)
            if url:
                have[str(aid)] = url
    with open(path, "w", encoding="utf8") as f:
        json.dump(have, f, indent=0, sort_keys=True)
    return len(have), len(todo)


# ---------------------------------------------------------------- main

def main(argv):
    ap = argparse.ArgumentParser(description="bind OpenTome's English lines to AniList ids")
    ap.add_argument("artifact", nargs="?", default=os.path.join(ROOT, "build", "manga-metadata.sqlite"))
    ap.add_argument("--dry-run", action="store_true", help="resolve and report, write nothing (covers skipped too)")
    ap.add_argument("--limit", type=int, help="only the first N unresolved lines (most volumes first)")
    ap.add_argument("--only", help="only the unresolved line(s) with exactly this name")
    ap.add_argument("--covers", action="store_true",
                    help="also fill <build>/anilist-covers.json for EN lines with an id (bound or display) "
                         "and no volume cover")
    ap.add_argument("--covers-only", action="store_true",
                    help="resolve nothing, only fill <build>/anilist-covers.json -- stage 8a runs it after "
                         "corrections/anilist.json's pins land, so a pinned id gets a cover too")
    ap.add_argument("--display", action="store_true",
                    help="resolve nothing, only recompute series.display_anilist_id / _via (display-only "
                         "fallback) -- stage 8a runs it after the pins, before --covers-only")
    a = ap.parse_args(argv)
    build = os.path.dirname(os.path.abspath(a.artifact))
    db = sqlite3.connect(a.artifact)
    if a.covers_only:
        cpath = os.path.join(build, "anilist-covers.json")
        have, fetched = covers(db, cpath)
        print("anilist: covers -> %s (%d ids, %d fetched)" % (cpath, have, fetched))
        db.close()
        return
    if a.display:
        by = display(db)
        print("anilist: display fallback (display only, never a binding): %s"
              % ", ".join("%d via %s" % (by[v], v) for v in DISPLAY_VIAS))
        db.close()
        return
    lines = load_lines(db, a.limit, a.only)
    resolve(lines)
    n = write(db, lines, a.dry_run)
    rep = os.path.join(build, "anilist-resolve-report.tsv")
    report(lines, rep)
    by = {v: sum(1 for ln in lines if ln["via"] == v) for v in VIAS}
    resolved = sum(by.values())
    print("anilist: %d line(s) considered, %d resolved (%s), %d unresolved%s"
          % (len(lines), resolved, ", ".join("%d via %s" % (by[v], v) for v in VIAS), len(lines) - resolved,
             " -- dry run, nothing written" if a.dry_run else "; %d written" % n))
    tot, missing = db.execute("SELECT COUNT(*), SUM(anilist_id IS NULL) FROM series WHERE language='en' AND volume_count>=3").fetchone()
    print("anilist: EN lines with volume_count >= 3: %d, without anilist_id: %d (%.1f %%)"
          % (tot, missing or 0, 100.0 * (missing or 0) / max(tot, 1)))
    print("anilist: report -> %s" % rep)
    if a.covers and not a.dry_run:
        cpath = os.path.join(build, "anilist-covers.json")
        have, fetched = covers(db, cpath)
        print("anilist: covers -> %s (%d ids, %d fetched)" % (cpath, have, fetched))
    db.close()


if __name__ == "__main__":
    main(sys.argv[1:])
