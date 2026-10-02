"""Stage 3f: Korean and Chinese print editions from DNB (German), BnF (French) and the Library of
Congress (English, LoC-created records only) -- docs/krcn-design.md. After 3e (the German JP round),
before the enrichment:

    python3 tier0/build_krcn.py build/opentome.db [carry-artifact]

  1. records     dnb_enumerate.enumerate_krcn, loc_sru.enumerate_loc (canary first), bnf_sru.enumerate_bnf
  2. lines       krcn_lines (one builder per source)
  3. defer       a DNB line whose key the German JP round mints stays with that round (plan P25:
                 defer_jp_round, BEFORE the Ize order and ids -- a deferred line feeds no title to
                 3f; krcn-report.json deferred_to_jp_round); then the Ize medium order
                 (krcn_lines.resolve_media) on the lines 3f keeps
  4. ids         krcn_identity.line_ids(reserved=the JP round's ids) -- "continuity first": a line
                 whose own-key id shipped keeps it; the carry lookup only for the others; no absorption
  5. attach      krcn_identity.attach_roles -- ISBN majority with an existing line, in any direction
  6. decide      link (full-name authors, JP guard, link_work), apply lines.json cluster_with / review to
                 the pooled lines, cluster the unlinked lines of all markets, create works that pass §9's
                 four criteria AND have a COMIC line (manhwa / manhua; the anchor: the English one with the
                 lowest key, else -- the lift, 2026-10-01 -- the lowest key in any market), hold a cluster of
                 novels only (R6: no id, no integer, a NULL rl_id in krcn_line, build/krcn-held.tsv; reason
                 novel-without-comic), keep published lines, adopt ids (R1)
  7. load        works, lines, volumes, claims (source dnb / loc / bnf, their licences, record urls),
                 staging krcn_line / krcn_member / loc_member, adoption renames -- all BEFORE 4c / 7b
  8. files       build/krcn-review.tsv, krcn-held.tsv, krcn-new-works.tsv, krcn-duplicates.tsv, krcn-report.json
                 (gate_report: the Task 15 publish-gate lists); catalogue meta krcn:ids and
                 loc:degraded / bnf:degraded (record_meta; the export and publish.sh read them)

Library works are created AFTER Wikipedia works and linking, so a work Wikipedia knows is never
duplicated in the same build (§9). No covers, no 856, no publisher summaries from any library.
"""
import collections, datetime, difflib, json, os, re, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "schema"))
sys.path.insert(0, os.path.join(ROOT, "tier2"))
import dnb_link as L
import krcn_identity as KI
import build_dnb as B
import dnb_enumerate as E
import dnb_sru as S
import loc_sru as LS
import bnf_sru as BS
import lib_sru as SRU
import krcn_lines as KL
import loc_marc as LM
import bnf_unimarc as U
import corrections as CORR
from load import _id, LICENCE

NOW = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
BUILD = os.path.join(ROOT, "build")

EXPORTED = ("merged", "sibling", "adopting", "linked", "kept", "new_work")
ROLES = EXPORTED + ("held", "review", "unlinked", "absorbed")
ATTACHED = ("merged", "sibling", "adopting")
COMIC_ANCHOR = ("manhwa", "manhua")
LATIN_MIN = 5
KANA_CJK = re.compile("[぀-ヿ一-鿿]+")
NO_K = {"works": set(), "lines": {}, "series_ids": set(), "work_ids": set(), "int": {}, "line_work": {},
        "line_name": {}, "line_medium": {}, "line_pub": {}, "line_vols": {}, "redirect": {}, "line_market": {}}

STAGING_DDL = """
CREATE TABLE IF NOT EXISTS krcn_line (      -- one row per KR/CN library line, exported or not
    key TEXT PRIMARY KEY,                   -- 'dnb:<IDN>' | 'loc:<LCCN>' | 'bnf:<ark>' (krcn_lines)
    source TEXT NOT NULL, market TEXT NOT NULL,
    rl_id TEXT,                             -- staged_rl_id: the release line it ships as, ONLY when it
                                            -- exports -- its tome_id (carried: kept or taken; else
                                            -- minted), for a merged line the line it merged into (the
                                            -- 3e dnb_line convention); NULL for held / review /
                                            -- unlinked / absorbed rows: R6 and §13 -- a held cluster
                                            -- has no tome_id in krcn_line, release_line, id_map or
                                            -- the artifact. Adoption moves it to the public id.
    carried INTEGER NOT NULL,               -- the id came from the carry (§8)
    work TEXT,                              -- the work it ships under (NULL unless exported);
                                            -- rename_work follows adoption renames
    name TEXT, publisher TEXT, medium TEXT, medium_why TEXT, medium_guess TEXT,
    n_volumes INTEGER,
    origin TEXT, explicit INTEGER, comic INTEGER,
    tier TEXT, via TEXT, link_work TEXT, candidates TEXT,
    role TEXT NOT NULL,                     -- build_krcn.ROLES
    reason TEXT, cluster TEXT,
    target TEXT,                            -- merged / sibling / adopting: the existing line
                                            -- (adoption moves it to the public id)
    exported INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS krcn_member (    -- one row per member record (a set record: per volume)
    member TEXT PRIMARY KEY, line_key TEXT, number TEXT, isbn13 TEXT,
    volume_id TEXT,                         -- NULL when the volume did not reach `volume`
    fate TEXT NOT NULL,                     -- created | attached | held_future | dropped_* | line_<role>
    filled TEXT, announced_only INTEGER, dated INTEGER, paged INTEGER);
CREATE TABLE IF NOT EXISTS loc_member (     -- one row per LoC record volume (the §13 provenance gates)
    lccn TEXT NOT NULL, number TEXT, f040a TEXT NOT NULL, encoding_level TEXT, date_type TEXT,
    set_record INTEGER NOT NULL, f263 TEXT, member TEXT NOT NULL,
    line_key TEXT, volume_id TEXT, fate TEXT,
    PRIMARY KEY (member));
"""


def staged_rl_id(ln):
    """krcn_line.rl_id: NULL unless the line exports (R6: an unexported line holds no id anywhere; its
    minted id is never written). An exported line: its tome_id; a merged line: the line it merged
    into (it ships inside that line -- the 3e dnb_line convention, which corrections' run_link_work
    joins on)."""
    if not ln["exported"]:
        return None
    return ln["target"] if ln["role"] == "merged" else ln["tome_id"]


def vol_id(ln, number):
    """A library line's volume id: from the line's tome_id -- a line that took a carried id mints its
    volumes under THAT id (v_(tome_id, number)), never under its own natural key (controller ruling)."""
    return _id("v_", ln["tome_id"], number)


def defer_jp_round(lines, jp_rows):
    """Plan P25 / §10 disjointness: a KR/CN DNB line whose key the German JP round also mints stays
    with that round (its output is frozen). jp_rows: [(dnb_line.key, dnb_line.rl_id)], exported or
    not. -> (the lines 3f builds, the deferred lines, reserved ids for krcn_identity.line_ids: every
    JP-round key's id and every JP-round rl_id)."""
    keys = {k for k, _ in jp_rows}
    reserved = {_id("rl_", k) for k in keys} | {r for _, r in jp_rows if r}
    keep = [ln for ln in lines if ln["key"] not in keys]
    return keep, [ln for ln in lines if ln["key"] in keys], reserved


def _key_ok(k):
    if not k:
        return False
    if L.HANGUL_ONLY.fullmatch(k):
        return len(k) >= L.MIN_HANGUL_KEY
    if KANA_CJK.fullmatch(k):
        return len(k) >= L.MIN_KEY
    return len(k) >= LATIN_MIN


# Uniform/collective form titles (a uniform title for a collection, not a single work): 'Short
# stories', 'Poems. Selections' -- measured in the cached LoC records (Short stories x7, Poems
# x3, Essays, Novels), but the filter is applied to every source's titles in cluster_keys()
# below, not LoC's 240 field alone.
FORM_WORDS = {"short", "stories", "story", "poems", "poetry", "selections", "selected", "works", "novels",
              "novellas", "plays", "essays", "prose", "correspondence", "letters", "speeches", "fiction",
              "writings", "collections", "collected", "complete", "english", "and", "other", "the", "n"}


def _form_title(t):
    toks = re.findall(r"[a-z]+", (t or "").lower())
    return bool(toks) and all(w in FORM_WORDS for w in toks)


def cluster_keys(ln):
    """§10 step 1: folded titles and Hangul / Hanzi keys join lines across markets; a romanised
    original title (`orig`) joins only lines of the same library (DNB syllable-splits, LoC writes
    ALA-LC). A LoC 240 form title ('Short stories', 'Poems. Selections') never keys.
    Note: DNB original titles key GLOBALLY -- build_dnb puts 240 / 246 into a line's `titles` (the
    German JP round's linker reads them there), so krcn_lines' DNB `titles` carry them too; only
    LoC's and BnF's `orig` are library-scoped. Measured on the cached data: no effect (no cluster
    joins across libraries through a DNB original title alone)."""
    ks = set()
    for t in list(ln["titles"]) + list(ln["native"]) + [ln["name"] or ""]:
        k = L.fold(t, False)
        if _key_ok(k) and not _form_title(t):
            ks.add(("t", k))
    for t in ln["orig"]:
        k = L.fold(t, False)
        if _key_ok(k) and not _form_title(t):
            ks.add(("o", ln["source"], k))
    return ks


def clusters(pool, joins=()):
    """joins: (key, key) pairs of pooled lines whose clusters are unioned (lines.json cluster_with)."""
    up = list(range(len(pool)))

    def find(x):
        while up[x] != x:
            up[x] = up[up[x]]
            x = up[x]
        return x
    by = collections.defaultdict(list)
    for i, ln in enumerate(pool):
        for k in cluster_keys(ln):
            by[k].append(i)
    for ids in by.values():
        for j in ids[1:]:
            a, b = find(ids[0]), find(j)
            if a != b:
                up[max(a, b)] = min(a, b)
    pos = {ln["key"]: i for i, ln in enumerate(pool)}
    for ka, kb in joins:
        a, b = find(pos[ka]), find(pos[kb])
        if a != b:
            up[max(a, b)] = min(a, b)
    groups = collections.defaultdict(list)
    for i, ln in enumerate(pool):
        groups[find(i)].append(ln)
    return sorted((sorted(g, key=lambda l: l["key"]) for g in groups.values()), key=lambda g: g[0]["key"])


WORD_SPLIT = re.compile(r"[\W_]+")
WHOLE_WORD_MIN = 7


def _words(t):
    """A title's words, each folded: fold() strips every space and punctuation mark, so a key has no word
    boundaries -- the unfolded title is split where fold() strips, then each word is folded. A leading
    'the' is dropped, as fold() drops it ('The Breaker' and 'Breaker: New Waves' share the word run)."""
    w = tuple(w for w in (L.fold(p, False) for p in WORD_SPLIT.split(t or "")) if w)
    return w[1:] if w[:1] == ("the",) else w


def _whole_word(a, b):
    """The partial-containment rule for works created in this build (KR/CN hold lifted, 2026-10-01; see
    docs/krcn-design.md): word sequence a appears contiguously in b, or b in a, and the shorter one's
    joined length is >= WHOLE_WORD_MIN ('legend' inside 'Legend of the Sun Knight' does not count)."""
    if len(a) > len(b):
        a, b = b, a
    return len("".join(a)) >= WHOLE_WORD_MIN and any(b[i:i + len(a)] == a for i in range(len(b) - len(a) + 1))


def containment_hits(cluster, idx):
    """§9 criterion 4: existing KR/CN works whose official title key contains, or is contained in, a
    key of the cluster (both 5+ characters), and any existing work whose official key equals one of the
    cluster's original / native title keys. Catches DE 'Raeliana' (= Why Raeliana Ended Up at the
    Duke's Mansion); not Athanasia (syllable-split romanisation -- the review file's job). Works created
    earlier in this build (Index.add_krcn_work: title and orig keys) count as existing KR/CN works:
    clusters are decided in key order, so the outcome is deterministic. Against a work created by the
    library (the lift, 2026-10-01): an exact key always counts; a partial one only as a whole-word match
    (_whole_word); and the cluster's own orig keys count by equality against the created works' orig
    keys, whatever library either came from (a DE work and a LoC EN cluster of one series)."""
    wiki = [(k, w) for k, ws in idx.official.items() for w in ws if w in idx.krcn_works and len(k) >= LATIN_MIN]
    made = [(k, w) for k, ws in idx.created.items() for w in ws if w in idx.krcn_works and len(k) >= LATIN_MIN]
    hits = set()
    for ln in cluster:
        for t in list(ln["titles"]) + list(ln["native"]) + [ln["name"] or ""]:
            k = L.fold(t, False)
            if len(k) < LATIN_MIN:
                continue
            hits |= {w for ok, w in wiki if ok in k or k in ok}
            hits |= {w for ok, w in made if ok == k or ((ok in k or k in ok) and any(
                _whole_word(_words(c), _words(t)) for c in idx.created_titles[ok]))}
        for t in list(ln["orig"]) + list(ln["native"]):
            k = L.fold(t, False)
            if L.key_ok(k):
                hits |= idx.official.get(k, set())
        for t in ln["orig"]:
            k = L.fold(t, False)
            if L.key_ok(k):
                hits |= idx.created_orig.get(k, set())
    return hits


def _class(medium, origin):
    if not medium:
        return None
    if medium in ("novel", "light_novel"):
        return "novel"
    return "manhwa" if origin == "kor" else "manhua"


def _link(idx, ln_or_cluster):
    ls = ln_or_cluster if isinstance(ln_or_cluster, list) else [ln_or_cluster]
    en = [l for l in ls if l["market"] == "EN"]
    name = (min(en, key=lambda l: l["key"]) if en else ls[0])["name"]
    # original titles link too, as in the German JP round (build_dnb puts 240 / 246 into a line's titles);
    # BnF's 454 often IS the English title. They only CLUSTER within one library (cluster_keys).
    return L.link(idx, [t for l in ls for t in list(l["titles"]) + list(l["orig"]) + list(l["native"])],
                  [a for l in ls for a in l["authors"]], [t for l in ls for t in list(l["orig"]) + list(l["native"])],
                  name, full_names=True)


def _entry(cid, cl, criteria, reason):
    return {"cluster": cid, "lines": [l["key"] for l in cl], "markets": sorted({l["market"] for l in cl}),
            "criteria": criteria, "reason": reason,
            "title_keys": sorted({k[-1] for l in cl for k in cluster_keys(l)})[:12],
            "volumes": sum(len(l["vols"]) for l in cl),
            "members": [m for l in cl for m in l.get("members", [])]}


def _join(*reasons):
    return "+".join(r for r in reasons if r) or None


def _novel(medium):
    """to_mangarr's novel / comic class (Mangarr's IsNovel): 'novel' anywhere in the medium, or an artbook."""
    return bool(medium) and ("novel" in medium.lower() or medium.lower() == "artbook")


def _is_vol1(number):
    try:
        return float(number) == 1
    except (TypeError, ValueError):
        return False


def decide(lines, idx, K, link_work=None, comic_works=(), line_medium=None, jp_override=None, present=None,
           cluster_with=(), review_lines=None, deferred=()):
    """The decision order of the module plan (Task 12), steps 1-7. Pure: no database.
    Review reasons from the line builder (controller ruling): a line with medium_why goes to review
    with reason = medium_why ('duplicate_numbers', 'both', 'writer_only', '+'-joined in that order) --
    attached or not; a link_work correction ships it with its medium_guess (none: it stays in review).
    A LoC line with no medium and no medium_why: 'ize-medium' | 'no-class-signal'. Every review reason
    is '+'-joined onto the linker's ('jp-guard+writer_only', 'low+ize-medium'), never overwritten.
    jp_override: {line key: why} -- link_work entries with override_jp_guard (corrections
    load_jp_guard_overrides): only these may link a line to a work the JP guard protects; each is
    logged and listed in plan['jp_overrides'] (gate_report jp_guard_overrides).
    present: {release_line id: work id} of the catalogue's lines before 3f loads (Wikipedia, 3e, corrections).
    A present line whose PUBLISHED work (the carry) is a library work id this build's catalogue holds under
    another work W was adopted by an earlier build (W's internal id was renamed to the public one): W adopts
    it again in step 7, and every published library work id resolves to the work holding it in this build
    (home: the carry's work id_redirect, then that adoption) wherever a line is placed -- a link_work
    correction, a frozen cluster, a kept line -- so an adopted work never splits (final review).
    cluster_with: [(key, key)] (corrections load_cluster_with) -- the two pooled lines' clusters are one
    (a DE and an FR cluster of one series); review_lines: {key: why} (load_review_lines) -- the pooled
    line's cluster goes to review with reason 'correction: <why>'. Both act before any work is created.
    An entry 3f cannot act on -- a key the build has but did not pool (linked, attached, review, carried),
    a deferred key (deferred: the P25 keys), a review cluster that holds a published line -- is skipped with
    a printed CLUSTER_WITH / REVIEW SKIPPED line and listed in plan['corrections_skipped'] (never a stop);
    a key the build does not have is a printed STALE CORRECTION, as for link_work."""
    K = K or NO_K
    link_work, line_medium, jp_override = link_work or {}, line_medium or {}, jp_override or {}
    # the carry's adoptions: {(public library work, the work now holding a line that shipped under it): lines}
    re_lines = collections.defaultdict(list)
    for r, w in sorted((present or {}).items()):
        if K["line_work"].get(r) in K["works"] and K["line_work"][r] != w:
            re_lines[(K["line_work"][r], w)].append(r)
    re_adopt = sorted(re_lines)
    adopted, by_public = {}, collections.defaultdict(list)
    for p_, w_ in re_adopt:
        adopted.setdefault(p_, w_)
        by_public[p_].append(w_)
    # one public id whose lines now sit under SEVERAL works: no work may take it silently (load stops the build)
    ambiguous = {p_: {w_: re_lines[(p_, w_)] for w_ in ws} for p_, ws in by_public.items() if len(ws) > 1}

    def redirected(w):
        seen = set()
        while w in K.get("redirect", {}) and w not in seen:
            seen.add(w)
            w = K["redirect"][w]
        return w

    def home(w):
        w = redirected(w)
        return adopted.get(w, w)
    plan = {"works": {}, "clusters": [], "held": [], "adopt_works": [], "review": [], "adopt_conflicts": [],
            "jp_overrides": []}
    pool = []
    for ln in lines:                                                   # 1-2
        for k, v in (("tier", None), ("via", None), ("reason", None), ("candidates", []), ("cluster", None),
                     ("link_work", None), ("work", ln.get("work")), ("medium_why", None), ("medium_guess", None)):
            ln.setdefault(k, v)
        lw = link_work.get(ln["key"])
        if ln.get("role") in ATTACHED:
            ln["via"] = "isbn"
            if lw:                      # the ISBNs decide (P17); a matching correction confirms the line
                print("  link_work %s: line is %s by ISBN under %s (link_work %s%s)"
                      % (ln["key"], ln["role"], ln["work"], lw, "" if home(lw) == ln["work"] else ", CONFLICT"))
            if ln["medium"] is None and not ln["medium_why"]:
                ln["medium"] = _class(line_medium.get(ln.get("target")), ln["origin"])
        else:
            ln["role"] = None
            # a Wikipedia work, a published library work (K works: library-born or adopted; decide
            # places it at its home), or one the carry redirected
            # -- but never an id the carry redirected: 8c's run_link_work reads the work the line ships under
            stale_red = redirected(lw) if lw and lw in K.get("redirect", {}) else None
            if lw and not stale_red and (home(lw) in idx.name or lw in K["works"]):
                ln.update(role="linked", work=home(lw), via="correction", link_work=lw)
            else:
                if stale_red:
                    print("  STALE CORRECTION -- lines.json link_work %s -> %s: that work id was redirected (the carry's "
                          "id_redirect) -- use %s" % (ln["key"], lw, stale_red))
                elif lw:
                    print("  STALE CORRECTION -- lines.json link_work %s -> %s: not a work in the catalogue" % (ln["key"], lw))
                tier, w, cands, via = _link(idx, ln)
                ln.update(tier=tier, link_work=w, candidates=cands, via=via)
                if tier in ("high", "medium"):
                    ln.update(role="linked", work=w)
                elif tier in ("low", "ambiguous"):
                    ln.update(role="review", reason=tier)
            if ln["role"] == "linked" and idx.jp_guard(ln["work"]):
                # P17: a correction does not lift the guard -- unless it says so, with a why (ruling)
                why = jp_override.get(ln["key"]) if ln["via"] == "correction" else None
                if why:
                    ln["via"] = "correction+override_jp_guard"
                    plan["jp_overrides"].append((ln["key"], ln["work"], why))
                    print("  JP GUARD OVERRIDE -- lines.json link_work %s -> %s: %s" % (ln["key"], ln["work"], why))
                else:
                    ln.update(role="review", reason="jp-guard", work=None)
        if ln["medium"] is None:
            confirmed = lw is not None and home(lw) == ln["work"] and ln["role"] in ("linked",) + ATTACHED
            if confirmed and ln["medium_guess"]:
                ln["medium"] = ln["medium_guess"]
            else:
                # §7: 'neither' goes to review -- an Ize ECIP record, or any LoC record with no class signal
                why = ln["medium_why"] or ("ize-medium" if ln.get("ize") else "no-class-signal")
                ln.update(role="review", reason=_join(ln["reason"] if ln["role"] == "review" else None, why), work=None)
        if ln["role"] is None:
            pool.append(ln)
    by_key, pooled, review_lines = {ln["key"]: ln for ln in lines}, {ln["key"] for ln in pool}, review_lines or {}

    def correctable(k, shape):
        """lines.json cluster_with / review act on pooled lines only (the lift, 2026-10-01)."""
        if k in pooled:
            return True
        if k in by_key or k in deferred:
            # a line the linker placed (linked, attached, review, fragment, carried...) or deferred: the entry cannot
            # act -- skipped and listed, never a stop (F2, 2026-10-01: a weekly build must not fail on a correction)
            ln = by_key.get(k)
            what = "deferred to the German JP round" if ln is None else \
                "%s%s%s" % ("carried line now " if ln["carried"] else "", ln["role"],
                            " (%s)" % ln["reason"] if ln["reason"] else "")
            print("  CLUSTER_WITH / REVIEW SKIPPED -- lines.json %s %s: %s" % (shape, k, what))
            skipped.append([shape, k, what])
            return False
        print("  STALE CORRECTION -- lines.json %s %s: not a line of this build" % (shape, k))
        return False
    joins = []
    skipped = plan["corrections_skipped"] = []
    for a, b in cluster_with:
        if all([correctable(a, "cluster_with"), correctable(b, "cluster_with")]):    # both checked, both named
            joins.append((a, b))
    review_lines = {k: why for k, why in sorted(review_lines.items()) if correctable(k, "review")}
    # a pooled line sharing a cluster key with a line this build linked / attached to a work is that
    # work's (Penelope / Villains): its cluster goes to review with the work as the candidate
    placed = collections.defaultdict(set)
    for ln in lines:
        if ln["role"] in ("linked",) + ATTACHED and ln["work"]:
            for k in cluster_keys(ln):
                placed[k].add(ln["work"])
    for n, cl in enumerate(clusters(pool, joins)):                    # 3-4
        cid = "c%04d" % n
        for ln in cl:
            ln["cluster"] = cid
        why = next((review_lines[l["key"]] for l in cl if l["key"] in review_lines), None)
        if why:
            carried = [l["key"] for l in cl if l["carried"]]
            if carried:
                # a published line never goes back to review (fix: link_work): skipped and listed, not a stop
                for k in sorted(k for k in review_lines if k in {l["key"] for l in cl}):
                    print("  CLUSTER_WITH / REVIEW SKIPPED -- lines.json review %s: cluster %s holds the published line %s"
                          % (k, cid, carried[0]))
                    skipped.append(["review", k, "cluster %s holds the published line %s" % (cid, carried[0])])
            else:
                print("  REVIEW CORRECTION -- lines.json review: cluster %s (%s) to review: %s"
                      % (cid, " ".join(l["key"] for l in cl), why))
                for ln in cl:
                    ln.update(role="review", reason="correction: " + why)
                continue
        if len(cl) > 1:
            tier, w, cands, via = _link(idx, cl)
            if tier in ("high", "medium") and not idx.jp_guard(w):
                for ln in cl:
                    ln.update(role="linked", work=w, tier=tier, link_work=w, via="cluster:%s" % via, candidates=cands)
                continue
            if tier != "none":
                why = "cluster-jp-guard" if tier in ("high", "medium") else "cluster-" + tier
                for ln in cl:
                    ln.update(role="review", reason=why, candidates=cands)
                continue
        # the anchor of a new work is a COMIC line (controller ruling), English first: a cluster of novels
        # only is held (novel-without-comic)
        comic = [l for l in cl if l["medium"] in COMIC_ANCHOR]
        en = [l for l in comic if l["market"] == "EN"]
        hits = containment_hits(cl, idx)
        c2, c3 = any(l["explicit"] for l in cl), any(l["comic"] for l in cl)
        entry = _entry(cid, cl, {"linker": "none", "explicit_origin": c2, "comic": c3, "containment": sorted(hits)}, None)
        plan["clusters"].append(entry)
        frozen = sorted({K["line_work"].get(l["tome_id"]) for l in cl if l["carried"]} & set(K["works"]))
        if frozen:
            # a published library work is never demoted: it exports even without an English line
            wid, created = KI.older(frozen, K), False
            entry["reason"] = "frozen"
            if home(wid) != wid:
                # adopted by an earlier build (or redirected): its lines ship under the work holding it now,
                # which step 7 renames back to the public id -- never a second work of that id
                entry["work"] = home(wid)
                for ln in cl:
                    if ln["carried"]:
                        ln.update(role="kept", work=home(wid), reason=(ln["reason"] or "") + ";kept")
                    else:
                        ln.update(role="linked", work=home(wid), via="cluster:frozen")
                continue
        elif any(placed.get(k) for l in cl for k in cluster_keys(l)):
            sib = sorted({w for l in cl for k in cluster_keys(l) for w in placed.get(k, ())})
            entry["reason"] = "linked-sibling-key"
            for ln in cl:
                ln.update(role="review", reason="linked-sibling-key", candidates=sib)
            continue
        elif hits:
            entry["reason"] = "containment"
            for ln in cl:
                ln.update(role="review", reason="containment", candidates=sorted(hits))
            continue
        elif not (c2 and c3):
            entry["reason"] = "no-explicit-origin" if not c2 else "no-comic"
            for ln in cl:
                ln.update(role="unlinked", reason=entry["reason"])
            continue
        elif any(l["carried"] and K["line_work"].get(l["tome_id"]) and home(K["line_work"][l["tome_id"]]) in idx.name
                 and home(K["line_work"][l["tome_id"]]) not in K["works"] for l in cl):
            # F2 (2026-10-01): a carried line published under a Wikipedia work the linker no longer reaches must not
            # seed a new work; review, then step 5 keeps it under its published work (the pre-lift held -> kept)
            entry["reason"] = "carried-elsewhere"
            for ln in cl:
                ln.update(role="review", reason="carried-elsewhere")
            continue
        elif not comic:
            # R6 for prose (unchanged): no work is ever created from novels alone
            entry["reason"] = "novel-without-comic"
            plan["held"].append(entry)
            for ln in cl:
                ln.update(role="held", reason=entry["reason"], work=None)
            continue
        else:
            # the lift (2026-10-01): an English comic line anchors as before; without one, the comic line
            # with the lowest key in any market (bnf: sorts before dnb:, so an FR+DE cluster anchors on FR)
            anchor = min(en or comic, key=lambda l: l["key"])
            wid, created = _id("w_", "krcn", anchor["key"]), True
        entry["work"] = wid
        title = anchor["name"] if created else None
        if not created:
            # frozen: the line whose key the published id hashes is the anchor (the id is _id("w_", "krcn", its
            # key)), titled with its carried name; only without one, the first round's rule (min EN, else cl[0])
            anchor = next((l for l in cl if _id("w_", "krcn", l["key"]) == wid), None) or \
                (min(en, key=lambda l: l["key"]) if en else cl[0])
            title = K["line_name"].get(anchor["tome_id"]) or anchor["name"]
        if wid in plan["works"]:
            # a second cluster frozen to the same published work (two halves a cluster_with once joined): its
            # lines join the work; the first cluster's anchor and title stay
            e = plan["works"][wid]
            e["lines"] += [l["key"] for l in cl]
            e["frozen"] = sorted(set(e["frozen"]) | set(frozen))
            if _id("w_", "krcn", anchor["key"]) == wid and _id("w_", "krcn", e["anchor"]) != wid:
                e.update(anchor=anchor["key"], title=title)     # F2: the line the id hashes anchors, whichever cluster
        else:
            plan["works"][wid] = {"anchor": anchor["key"], "created": created, "title": title,
                                  "lines": [l["key"] for l in cl], "cluster": cid, "frozen": frozen}
        for ln in cl:
            ln.update(role="new_work", work=wid)
        idx.add_krcn_work(wid, [t for l in cl for t in list(l["titles"]) + list(l["native"]) + [l["name"] or ""]],
                          [t for l in cl for t in l["orig"]])
    # a fragment (export fixes E1, 2026-09-28): a NEW library line linked by title (not a hand-checked link_work
    # correction) or an ISBN sibling (attach_roles merges exactly one line per target; a second line sharing its
    # ISBNs is a sibling with its own id), with no vol 1, in a work and market that already has a carried line,
    # goes to review. Exported, it became that market's counterpart / is_main / parent over the carried line
    # (Solo Leveling FR: a Kbooks 4/15/17 line over the 19-volume Medias line; DE: a vol-15-only sibling)
    # keyed by novel / comic class, the split the export's counterpart guard and Mangarr's PickSibling use (review fix)
    carried_wm = {(home(w), K.get("line_market", {}).get(t), _novel(K.get("line_medium", {}).get(t)))
                  for t, w in K["line_work"].items() if w}
    for ln in lines:
        if ln["carried"] or not ln["work"] or (ln["work"], ln["market"], _novel(ln["medium"])) not in carried_wm:
            continue
        if (ln["role"] == "sibling" or (ln["role"] == "linked" and not (ln["via"] or "").startswith("correction"))) \
                and not any(_is_vol1(v["number"]) for v in ln["vols"]):
            ln.update(role="review", reason=_join(ln["reason"], "fragment"), candidates=[ln["work"]], work=None)
    for ln in lines:                                                   # 5
        if ln["role"] in ("review", "unlinked", "held") and ln["carried"]:
            w = K["line_work"].get(ln["tome_id"])
            w = home(w) if w else None
            if w and (w in idx.name or w in plan["works"] or w in K["works"]):
                ln.update(role="kept", work=w, reason=(ln["reason"] or "") + ";kept")
                ln["medium"] = ln["medium"] or K["line_medium"].get(ln["tome_id"]) or ln["medium_guess"]
                if w not in idx.name:
                    e = plan["works"].setdefault(w, {"anchor": ln["key"], "created": False, "title": ln["name"],
                                                     "lines": [], "cluster": ln["cluster"], "frozen": [w]})
                    e["lines"].append(ln["key"])
    for ln in lines:                    # a link_work correction to a published library-born work
        if ln["role"] == "linked" and ln["work"] not in idx.name and ln["work"] not in plan["works"]:
            plan["works"][ln["work"]] = {"anchor": ln["key"], "created": False, "title": ln["name"], "lines": [ln["key"]],
                                         "cluster": ln["cluster"], "frozen": [ln["work"]]}
    comic_now = set(comic_works) | set(plan["works"]) | {                # 6
        ln["work"] for ln in lines if ln["role"] in EXPORTED and ln["medium"] and ln["medium"] != "novel"}
    for ln in lines:
        if ln["medium"] == "novel" and ln["role"] in ("linked", "sibling", "adopting") and \
                ln["work"] not in comic_now and not ln["carried"]:
            ln.update(role="held", reason="novel-without-comic", candidates=[ln["work"]], work=None)
            plan["held"].append(_entry(ln["cluster"], [ln], {
                "linker": ln["tier"], "explicit_origin": ln["explicit"], "comic": ln["comic"],
                "containment": sorted(containment_hits([ln], idx)), "novel_without_comic": ln["candidates"]},
                "novel-without-comic"))
    for e in plan["held"]:                                             # a published line is never held
        e["lines"] = [k for k in e["lines"] if k not in {l["key"] for l in lines if l["role"] == "kept"}]
    plan["held"] = [e for e in plan["held"] if e["lines"]]
    libs = collections.defaultdict(set)                                # 7
    for p_, w_ in re_adopt:            # a present line shipped under a published library work: adopt it again
        libs[w_].add(p_)
    for ln in lines:
        if ln["role"] in EXPORTED and ln["work"] and ln["work"] not in plan["works"]:
            for t in [ln["tome_id"]] * bool(ln["carried"]) + list(ln.get("absorbed_ids", [])):
                lw = K["line_work"].get(t)
                if lw in K["works"] and lw != ln["work"]:
                    libs[ln["work"]].add(lw)
    publics = collections.Counter()
    for w_now, ws in sorted(libs.items()):
        public = KI.older(sorted(ws | ({w_now} if w_now in K["work_ids"] else set())), K)
        if public != w_now:
            plan["adopt_works"].append((w_now, public))
            publics[public] += 1
            for ln in lines:
                if ln["work"] == w_now:
                    ln["work"], ln["adopted_from"] = public, w_now
    # rename_work(W, public) needs `public` absent: a frozen work of this build, or two works adopting one
    # public id, would collide -- reported (gate_report adopt_conflicts), never resolved silently
    plan["adopt_conflicts"] = sorted({(w, p) for w, p in plan["adopt_works"] if p in plan["works"] or publics[p] > 1} |
                                     {(w, p) for p, ws in ambiguous.items() for w in ws})
    plan["adopt_ambiguous"] = ambiguous
    for ln in lines:
        ln["exported"] = ln["role"] in EXPORTED
        if not ln["exported"]:
            ln["work"] = None
        if ln["role"] == "review":
            plan["review"].append(ln["key"])
    return plan


def _isbns(vols):
    return {i for _, i in vols if i}


# Fuzzy duplicate candidates (KR/CN hold lifted, 2026-10-01; docs/krcn-design.md): fold keys of 7+ characters at
# difflib ratio >= 0.8 are listed; export/test_artifact.py (DUP_GATE) needs a verdict for the rows at 0.9 or more.
DUP_MIN_KEY = 7
DUP_RATIO = 0.8
DUP_HEADER = ["kind", "work", "title", "other", "other_title", "key", "other_key", "ratio", "anilist_id"]


def duplicate_rows(lines, plan, idx):
    """The duplicate-candidate list (KR/CN hold lifted, 2026-10-01), after step 4: every work created in this build whose title / native / orig
    keys (fold, >= DUP_MIN_KEY characters) fuzzy-match a key of another created work, of a published library
    work this build froze (only ever the `other` side), or of an existing work (idx.official / idx.alias: the
    catalogue's work titles before 3f) at difflib ratio >= DUP_RATIO.
    Bounded: only keys in the length window a ratio of DUP_RATIO allows, then real_quick_ratio /
    quick_ratio before ratio(). Pure. -> rows in DUP_HEADER order, kind 'title', the best key pair per
    (work, other), highest ratio first."""
    by = {l["key"]: l for l in lines}
    keys, frozen = {}, {}
    for w, e in plan["works"].items():
        ts = [t for k in e["lines"] if k in by for t in
              list(by[k]["titles"]) + list(by[k]["native"]) + list(by[k]["orig"]) + [by[k]["name"] or ""]]
        (keys if e["created"] else frozen)[w] = sorted({k for k in (L.fold(t, False) for t in ts) if len(k) >= DUP_MIN_KEY})
    by_len = collections.defaultdict(list)
    for w, ks in keys.items():
        for k in ks:
            by_len[len(k)].append((k, w, True))
    for w, ks in frozen.items():        # published library works: only ever the `other` side
        for k in ks:
            by_len[len(k)].append((k, w, False))
    for table in (idx.official, idx.alias):
        for k, ws in table.items():
            if len(k) >= DUP_MIN_KEY:
                by_len[len(k)] += [(k, w, False) for w in sorted(ws)]
    best = {}
    sm = difflib.SequenceMatcher(autojunk=False)
    for w in sorted(keys):
        for a in keys[w]:
            sm.set_seq2(a)
            for n in range(-(-2 * len(a) // 3), 3 * len(a) // 2 + 1):     # 2 * min / (la + lb) >= DUP_RATIO
                for b, o, made in by_len.get(n, ()):
                    if o == w or (made and o < w):          # one row per pair of created works
                        continue
                    sm.set_seq1(b)
                    if sm.real_quick_ratio() < DUP_RATIO or sm.quick_ratio() < DUP_RATIO:
                        continue
                    r = sm.ratio()
                    if r >= DUP_RATIO and r > best.get((w, o), (0,))[0]:
                        best[(w, o)] = (r, a, b, made)
    title = lambda w, made: plan["works"][w]["title"] if w in plan["works"] else idx.name.get(w, "?")
    return [["title", w, title(w, True), o, title(o, made), a, b, "%.3f" % r, ""]
            for (w, o), (r, a, b, made) in sorted(best.items(), key=lambda kv: (-kv[1][0], kv[0]))]


def gate_report(lines, plan, rep, K, E=None, deferred=()):
    """The lists the Task 15 publish gate reads (controller rulings, krcn-report.json). Pure.
    rep: krcn_identity.line_ids' report; E: krcn_identity.existing_lines' E, merged over the markets.
      taken_weak           step-2 takes without a strict majority of the carried line's ISBNs, except a
                           0-of-0 take (no ISBN on either side) -- BLOCKING in test_artifact.run_krcn
                           unless krcn_linker_labels.json taken_ok confirms [line key, carried id]
      left                 carried library ids neither kept nor taken: 7b redirects or orphans them
      kept_no_overlap      step-1 keeps (own key carried) sharing 0 ISBNs with their carried line
      absorbed_weak        a published id that goes away into another line (a carried line merged into
                           an existing line, a carried existing line a library line adopts, any
                           absorbed_ids) where the absorber lacks a strict majority of its ISBNs
      p22_thin             a one-volume carried library line adopting a larger carried line (P22)
      work_redirects       adopt_works whose internal work was published (7b redirects it) and
                           frozen clusters holding several published library works
      adopt_conflicts      renames that would collide (decide)
      carried_not_exported published lines that do not export (their ids fall to 7b)
      carried_work_changed published lines exporting under another work than their published one
      hangul_only_authors  lines with creators but no Latin name: no author evidence (full-name rule)
      authors_differ       lines whose linker verdict was a title collision (authors differ; MR vs RR)
      deferred_to_jp_round P25
      jp_guard_overrides   link_work corrections that lifted the JP guard (line key, work, why)
      corrections_skipped  review: lines.json cluster_with / review entries 3f could not act on (a key the linker
                           placed, a deferred one, a review cluster that holds a published line) --
                           [shape, key, why]; the build never stops on one
      containment_created  review (the lift): every cluster the containment guard sent to review because
                           of a work created in THIS build -- [cluster, its line keys, those works]; the
                           reviewer reads it (a pair of one series becomes a cluster_with)
      adoption_isbn_clash  review: an adopted Wikipedia volume's ISBN already on another volume of the
                           public line (offset numbering) -- [line key, public, number, Wikipedia ISBN,
                           ISBN kept]; set by load (adopt), so gate_report runs after load
    """
    K, E = K or NO_K, E or {}
    taken = {k for _, k in rep.get("taken", [])}
    lv = K.get("line_vols") or {}
    # a 0-of-0 take (neither the line nor the carried line has an ISBN; it qualified by the same name and
    # publisher family) is the only evidence such a line can ever give: not weak (controller ruling)
    no_isbn = {ln["key"] for ln in lines if not any(v["isbns"] for v in ln["vols"])}
    weak = [list(t) for t in rep.get("taken_weak", []) if not (t[3] == 0 and t[1] in no_isbn)]
    out = {"taken_weak": weak, "left": list(rep.get("left", [])),
           "kept_no_overlap": [], "absorbed_weak": [], "p22_thin": [], "work_redirects": [],
           "adopt_conflicts": [list(t) for t in plan.get("adopt_conflicts", [])],
           "carried_not_exported": [], "carried_work_changed": [], "hangul_only_authors": [],
           "authors_differ": [], "deferred_to_jp_round": sorted(ln["key"] for ln in deferred),
           "jp_guard_overrides": [list(t) for t in plan.get("jp_overrides", [])],
           "corrections_skipped": [list(t) for t in plan.get("corrections_skipped", [])],
           "containment_created": [],
           "adoption_isbn_clash": [list(t) for t in plan.get("adoption_isbn_clash", [])]}
    renamed = dict(plan.get("adopt_works", []))
    for ln in lines:
        mine = {i for v in ln["vols"] for i in v["isbns"]}
        t = ln["tome_id"]
        if ln["carried"] and ln["key"] not in taken:
            n = _isbns(lv.get(t, []))
            if not (mine & n):
                out["kept_no_overlap"].append([t, ln["key"], 0, len(n), len(mine)])
        x = ln.get("target")
        if ln["role"] == "merged" and ln["carried"] and x != t:     # the library line's published id goes into x
            n = _isbns(lv.get(t, []))
            have = {i for _, i in E.get(x, {}).get("vols", {}).values() if i}
            if 2 * len(n & have) <= len(n):
                out["absorbed_weak"].append([t, x, "merged", len(n & have), len(n)])
        if ln["role"] == "adopting" and x in K["series_ids"]:        # x's published id goes into the library line
            n = _isbns(lv.get(x, []))
            if 2 * len(n & mine) <= len(n):
                out["absorbed_weak"].append([x, t, "adopting", len(n & mine), len(n)])
            if len(ln["vols"]) == 1 and len(n) > 1:
                out["p22_thin"].append([t, ln["key"], x, len(n)])
        for a in ln.get("absorbed_ids", []):
            n = _isbns(lv.get(a, []))
            if 2 * len(n & mine) <= len(n):
                out["absorbed_weak"].append([a, t, "absorbed", len(n & mine), len(n)])
        if ln["carried"]:
            was = K["line_work"].get(t)
            if not ln["exported"]:
                out["carried_not_exported"].append([t, ln["key"], ln["role"], ln["reason"]])
            elif was and ln["work"] != was and renamed.get(was) != ln["work"]:
                out["carried_work_changed"].append([t, ln["key"], was, ln["work"], ln["role"]])
        if ln["authors"] and not any(L.full_splits(a) for a in ln["authors"]):
            out["hangul_only_authors"].append([ln["key"], ln["role"], ln["authors"][:3]])
        if "authors differ" in (ln["via"] or ""):
            out["authors_differ"].append([ln["key"], ln["tier"], ln["link_work"], ln["name"]])
    made = {w for w, e in plan.get("works", {}).items() if e.get("created")}
    by_cluster = collections.defaultdict(list)
    for ln in lines:
        if ln["role"] == "review" and ln["reason"] == "containment" and set(ln.get("candidates") or ()) & made:
            by_cluster[ln.get("cluster")].append(ln)
    for cid, ls in by_cluster.items():
        out["containment_created"].append([cid, sorted(l["key"] for l in ls),
                                           sorted({w for l in ls for w in l["candidates"]} & made)])
    for w, p in plan.get("adopt_works", []):
        if w in K["work_ids"]:
            out["work_redirects"].append([w, p, "adopted"])
    for wid, e in plan.get("works", {}).items():
        for f in e.get("frozen", []):
            if f != wid:
                out["work_redirects"].append([f, wid, "frozen-merge"])
    for k in out:
        out[k].sort()
    return out


def krcn_ids(lines, plan):
    """Plan P3, catalogue meta 'krcn:ids' (the export copies it to meta.krcn_ids, keeping only the ids
    the artifact ships; krcn_identity.read_carry reads it back next build). Pure.
      works    the library works exported lines ship under: created or frozen in this build, and
               the public (library) ids that works adopted (decide step 7) -- an adopted id stays
               library-born, or the next build would not adopt again
      created  the works created in this build
      lines    {tome_id: source} of every exported library-born line; a merged line ships inside an
               existing line, so it is not one"""
    shipped = {ln["work"] for ln in lines if ln["exported"]}
    works = (set(plan.get("works", {})) | {p for _, p in plan.get("adopt_works", [])}) & shipped
    created = {w for w, e in plan.get("works", {}).items() if e.get("created")} & shipped
    return {"works": sorted(works), "created": sorted(created),
            "lines": {ln["tome_id"]: ln["source"] for ln in lines if ln["exported"] and ln["role"] != "merged"}}


DEGRADED_KEY = {"loc": "loc:degraded", "bnf": "bnf:degraded"}


def record_meta(db, lines, plan, reports, offline=None):
    """Catalogue meta for the export (controller rulings 1 and 3):
      krcn:ids                   krcn_ids(lines, plan)
      loc:degraded, bnf:degraded a source whose refresh failed this build (lib_sru kept the previous
                                 complete result set) or whose set came back incomplete: {"reason",
                                 "kept_previous": the degraded queries} (build_dnb's dnb:degraded
                                 shape). 3f owns both keys: written or cleared here. The export copies
                                 them to meta.loc_degraded / bnf_degraded; export/publish.sh refuses.
      dnb:degraded               the KR/CN DNB channels share it with stage 3e (build_dnb, another
                                 process, so dnb_sru's DEGRADED does not carry over): merged in under
                                 "krcn", never cleared -- 3e's own value stays.
      loc:offline, bnf:offline   NOT blocking (plan P13): CI's reachability probe found the gateway
                                 unreachable (LOC_UNREACHABLE / BNF_UNREACHABLE=1), so the source was
                                 read from the cache: offline[src] = {"reason": "unreachable", "stale_sets":
                                 result sets served past their refresh window}. Written or cleared here,
                                 printed; the export does not copy it and publish.sh does not refuse it.
    reports: {"loc": loc_sru.enumerate_loc report, "bnf": bnf_sru.enumerate_bnf tally,
              "dnb": dnb_enumerate.enumerate_krcn tally}, all three, each with its "degraded" key -- a
    missing source or key raises (a typo must never pass as a clean run and let a degraded build publish)."""
    missing = sorted(src for src in ("dnb", "loc", "bnf") if "degraded" not in (reports.get(src) or {}))
    if missing:
        raise ValueError("build_krcn.record_meta: no report, or no 'degraded' key, for %s" % missing)
    db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('krcn:ids',?)",
               (json.dumps(krcn_ids(lines, plan), sort_keys=True),))
    for src in ("dnb", "loc", "bnf"):
        rep = reports[src]
        bad = bool(rep.get("degraded") or rep.get("degraded_queries"))
        val = {"reason": rep.get("degraded") or "incomplete", "kept_previous": list(rep.get("degraded_queries") or [])}
        if bad:
            print("  WARNING %s refresh degraded (%s): %d result set(s) kept their previous complete set -- "
                  "this build will not publish" % (src.upper(), val["reason"], len(val["kept_previous"])), flush=True)
        if src == "dnb":
            if bad:
                old = db.execute("SELECT value FROM meta WHERE key='dnb:degraded'").fetchone()
                cur = dict(json.loads(old[0]), krcn=val) if old else dict(val, round="krcn")
                db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('dnb:degraded',?)", (json.dumps(cur),))
            continue
        db.execute("DELETE FROM meta WHERE key=?", (DEGRADED_KEY[src],))
        if bad:
            db.execute("INSERT INTO meta(key,value) VALUES(?,?)", (DEGRADED_KEY[src], json.dumps(val)))
        db.execute("DELETE FROM meta WHERE key=?", (src + ":offline",))
        if src in (offline or {}):
            o = offline[src]
            print("  NOTE %s unreachable from this runner: read from the cache (%d result set(s) past the %s_REFRESH_DAYS "
                  "window) -- meta %s:offline (does not block publishing)" % (src.upper(), o["stale_sets"], src.upper(), src),
                  flush=True)
            db.execute("INSERT INTO meta(key,value) VALUES(?,?)", (src + ":offline", json.dumps(o, sort_keys=True)))


# ---- stage 3f, part 2: load, staging, adoption, files (Task 14) ------------------------------------------

def member_url(m):
    """'dnb:<IDN>' / 'loc:<LCCN>[#<vol>]' / 'bnf:<ark>' (a member or a line key) -> the record's url."""
    src, rest = m.split(":", 1)
    if src == "dnb":
        return B.url(rest)
    if src == "loc":
        return LM.url(rest.split("#")[0])
    return U.url(rest)


def _claim(c, entity, eid, field, value, src, url, own=None):
    """own: on an ATTACHED volume, the source urls 3f writes (member_url of every member / line key of
    this run). An existing claim of the same key (entity, id, field, source) citing any other url is
    another stage's (3e's dnb, enrich_bnf's per-ISBN bnf lookup) and is kept, never displaced; 3f's
    own earlier claims are gone already (unload runs first). own None: insert or replace."""
    if own is not None:
        old = c.execute("SELECT source_url FROM claim WHERE entity=? AND entity_id=? AND field=? AND source=?",
                        (entity, eid, field, src)).fetchone()
        if old and old[0] not in own:
            return
    c.execute("""INSERT OR REPLACE INTO claim (entity,entity_id,field,value,source,source_url,licence,retrieved_at)
                 VALUES(?,?,?,?,?,?,?,?)""", (entity, eid, field, str(value), src, url, LICENCE[src], NOW))


def _volume_claims(c, vid, v, src, own=None):
    """A volume's library claims, each citing the member record that gave the fact: ISBN and number the
    first member; the date its date_member (a LoC date always a single-volume record, never a set
    record, §12); pages the first single-record member. own: see _claim (attached volumes)."""
    first = v["members"][0]
    if v["isbn"]:
        _claim(c, "volume", vid, "isbn13", v["isbn"], src, member_url(first), own)
    d = v["date"]
    if d and d[0] != "HELD":
        _claim(c, "volume", vid, "release_date" if d[2] == "published" else "projected_date", d[0], src,
               member_url(v["date_member"] or first), own)
    if v["pages"]:
        _claim(c, "volume", vid, "page_count", v["pages"], src,
               member_url(next((m for m in v["members"] if "#" not in m), first)), own)
    _claim(c, "volume", vid, "volume_number", v["number"], src, member_url(first), own)


def _meta(c, key):
    row = c.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row[0] if row else None


def unload(c):
    """Take back what an earlier 3f run wrote (a development rerun on one catalogue). A run that
    ADOPTED ids re-keyed Wikipedia rows (P2) and cannot be taken back: rebuild from stage 1.
    Claims: every library claim on a volume / line 3f created, and on a volume it attached to only the
    claims citing one of its own member records -- another stage's dnb / bnf claims (3e, enrich_bnf)
    on the same volume stay."""
    adopted = json.loads(_meta(c, "krcn:adopted") or "[]")
    if adopted:
        raise SystemExit("stage 3f already adopted %d id(s) in this catalogue -- rebuild from stage 1 "
                         "(rebuild_all.sh builds a fresh database unless KEEP_DB=1)" % len(adopted))
    try:
        made_lines = [r[0] for r in c.execute("SELECT rl_id FROM krcn_line WHERE exported=1 AND role<>'merged'")]
        made_vols = [r[0] for r in c.execute("SELECT volume_id FROM krcn_member WHERE fate='created'")]
        urls = {member_url(m) for (m,) in c.execute("SELECT member FROM krcn_member")} | \
            {member_url(k) for (k,) in c.execute("SELECT key FROM krcn_line")}
    except sqlite3.OperationalError:
        return
    for vid, filled in c.execute("""SELECT DISTINCT volume_id, filled FROM krcn_member WHERE fate='attached'
                                    AND filled IS NOT NULL""").fetchall():
        for col in json.loads(filled):
            if col == "release_date":
                c.execute("""UPDATE volume SET release_date=NULL, release_date_precision=NULL,
                             release_date_type='unknown' WHERE id=?""", (vid,))
            else:
                c.execute("UPDATE volume SET %s=NULL WHERE id=?" % col, (vid,))
    c.execute("CREATE TEMP TABLE IF NOT EXISTS krcn_unload_url (u TEXT PRIMARY KEY)")
    c.execute("DELETE FROM krcn_unload_url")
    c.executemany("INSERT OR IGNORE INTO krcn_unload_url VALUES(?)", [(u,) for u in urls])
    c.execute("""DELETE FROM claim WHERE source IN ('dnb','loc','bnf') AND (
                     (entity='volume' AND entity_id IN (SELECT volume_id FROM krcn_member WHERE fate='created'))
                  OR (entity='release_line' AND entity_id IN (SELECT rl_id FROM krcn_line
                                                              WHERE exported=1 AND role<>'merged'))
                  OR (entity='volume' AND source_url IN (SELECT u FROM krcn_unload_url) AND entity_id IN
                      (SELECT volume_id FROM krcn_member WHERE volume_id IS NOT NULL)))""")
    c.execute("DROP TABLE krcn_unload_url")
    c.executemany("DELETE FROM volume WHERE id=?", [(v,) for v in made_vols])
    c.executemany("DELETE FROM release_line WHERE id=?", [(r,) for r in made_lines])
    for w in json.loads(_meta(c, "krcn:works_made") or "[]"):
        c.execute("DELETE FROM work_title WHERE work_id=?", (w,))
        c.execute("DELETE FROM work WHERE id=?", (w,))
    for t in ("krcn_line", "krcn_member", "loc_member"):
        c.execute("DELETE FROM %s" % t)
    c.execute("DELETE FROM meta WHERE key IN ('krcn:ids','krcn:adopted','krcn:works_made','krcn:stats',"
              "'loc:degraded','bnf:degraded','loc:offline','bnf:offline')")
    # dnb:degraded is shared with 3e: record_meta merged 3f's part in under "krcn", or -- 3e clean --
    # wrote its own value with round "krcn"; take back only that
    old = _meta(c, "dnb:degraded")
    if old:
        val = json.loads(old)
        if val.get("round") == "krcn":
            c.execute("DELETE FROM meta WHERE key='dnb:degraded'")
        elif "krcn" in val:
            val.pop("krcn")
            c.execute("UPDATE meta SET value=? WHERE key='dnb:degraded'", (json.dumps(val),))


def adopt(c, internal, public, key=None):
    """krcn_identity.adopt_line (R1 / P2) plus the staging rows it does not know (controller ruling):
    the staging is written before adoption, so krcn_member / loc_member volume ids pointing at the
    internal line's volumes move to what adopt_line made of them (a moved volume: v_(public, n); a
    merged one: the public line's volume of that number), and krcn_line target / rl_id move to the
    public id. A merged volume keeps the internal (Wikipedia) volume's present values -- isbn13, page_count
    and the date triple -- over the library's: the library only fills what Wikipedia left empty, the
    fill_attached rule (§8, controller ruling), even when the library's date is finer. A Wikipedia ISBN
    that already sits on ANOTHER volume of the public line (the two sources number the line differently)
    is not written: the volume keeps its value, and the clash is returned for review (gate list
    adoption_isbn_clash) -- one ISBN never lands on two volumes.
    -> (moved, merged, clashes: [[line key, public, number, Wikipedia ISBN, ISBN kept]])."""
    have = {n: v for v, n in c.execute("SELECT id, number FROM volume WHERE release_line_id=?", (public,))}
    wiki = c.execute("""SELECT id, number, isbn13, page_count, release_date, release_date_precision, release_date_type
                        FROM volume WHERE release_line_id=?""", (internal,)).fetchall()
    remap = {v: have.get(n) or _id("v_", public, n) for v, n, *_ in wiki}
    moved, merged = KI.adopt_line(c, internal, public)
    clashes = []
    for _, n, isbn, pc, rd, rp, rt in wiki:
        if n not in have:
            continue
        if isbn:
            other = c.execute("SELECT id FROM volume WHERE release_line_id=? AND isbn13=? AND id<>? LIMIT 1",
                              (public, isbn, have[n])).fetchone()
            if other:
                kept = c.execute("SELECT isbn13 FROM volume WHERE id=?", (have[n],)).fetchone()[0]
                clashes.append([key, public, n, isbn, kept])
            else:
                c.execute("UPDATE volume SET isbn13=? WHERE id=?", (isbn, have[n]))
        if pc is not None:
            c.execute("UPDATE volume SET page_count=? WHERE id=?", (pc, have[n]))
        if rd:
            c.execute("UPDATE volume SET release_date=?, release_date_precision=?, release_date_type=? WHERE id=?",
                      (rd, rp, rt, have[n]))
    for old, new in remap.items():
        for t in ("krcn_member", "loc_member"):
            c.execute("UPDATE %s SET volume_id=? WHERE volume_id=?" % t, (new, old))
    for col in ("target", "rl_id"):
        c.execute("UPDATE krcn_line SET %s=? WHERE %s=?" % (col, col), (public, internal))
    return moved, merged, clashes


def load(db, lines, lost, plan, K):
    """Works, lines, volumes, claims (source dnb / loc / bnf, LICENCE[src], the member record's url), the
    staging (krcn_line / krcn_member / loc_member), then adoption (R1 / P2: adopt_line for every
    adopting line, rename_work for every plan['adopt_works']) -- all BEFORE 4c / 7b. How a volume loads
    (build_dnb.load's rules, per line role): an adopting line's volume is created under the public id
    (never attached by ISBN; adopt_line folds the internal line's volumes into it); another exported
    line's volume whose ISBN an existing volume has is 'attached' (it gains the claims; fill_attached
    fills only empty columns, never a Wikipedia date, §8); else held_future / dropped_no_date_no_isbn /
    a merged line's number the target has ('attached', or dropped_number_clash on differing ISBNs) /
    'created' as vol_id (a merged line: v_(target, number)). -> Counter of volume fates."""
    n_pub = collections.Counter(p for _, p in plan["adopt_works"])
    clash = sorted(p for p, n in n_pub.items() if n > 1)
    ambiguous = plan.get("adopt_ambiguous") or {}
    if clash or ambiguous:
        # ids are a public contract: two works adopting one public id would leave release_line.work_id on
        # a work that does not exist, or merge two works silently -- fail before anything is written. The
        # same for a public id whose present lines sit under several works (decide: ambiguous re-adoption),
        # whichever of them step 7 would rename -- one would take the id, the other keep the lines
        msg = []
        for p, by_w in sorted(ambiguous.items()):
            lib = sorted(l["key"] for l in lines if l.get("work") in set(by_w) | {p} or l.get("adopted_from") in by_w)
            msg.append("public work id %s now held by several works: %s; library lines under them: %s" % (
                p, ", ".join("%s (lines %s)" % (w, " ".join(rs)) for w, rs in sorted(by_w.items())),
                " ".join(lib) or "none"))
        for p in (p for p in clash if p not in ambiguous):     # an ambiguous one is named above, with its lines
            ws = sorted(w for w, q in plan["adopt_works"] if q == p)
            by_w = {w: sorted(l["key"] for l in lines if l.get("adopted_from") == w) for w in ws}
            if all(by_w.values()):
                msg += ["work %s (lines %s) -> public id %s" % (w, " ".join(by_w[w]), p) for w in ws]
            else:             # decide sets adopted_from; a plan from elsewhere may not
                msg.append("works %s -> public id %s (the lines cannot be attributed to a work; lines now under "
                           "%s: %s)" % (", ".join(ws), p, p, " ".join(sorted(l["key"] for l in lines
                                                                           if l.get("work") == p)) or "none"))
        raise SystemExit("stage 3f: two works would adopt one public work id -- %s. Decide which work the "
                         "lines belong to and add a link_work correction (corrections/lines.json)." % "; ".join(msg))
    c = db.cursor()
    st = collections.Counter()
    by_key = {l["key"]: l for l in lines}
    made = []
    own = {member_url(m) for l in lines for m in l["members"]} | {member_url(l["key"]) for l in lines}
    for wid, w in sorted(plan["works"].items()):
        if c.execute("SELECT 1 FROM work WHERE id=?", (wid,)).fetchone():
            continue
        members = sorted((by_key[k] for k in w["lines"] if k in by_key), key=lambda l: (l["key"] != w["anchor"], l["key"]))
        native = next((t for l in members for t in l["native"]), None)
        c.execute("INSERT INTO work(id,primary_title,native_title,status,created_at,updated_at) VALUES(?,?,?,NULL,?,?)",
                  (wid, w["title"], native, NOW, NOW))
        made.append(wid)
        for l in members:
            olang = "ko" if l["origin"] == "kor" else "zh"
            for lang, title, kind in ([(l["language"], l["name"], "official")] +
                                      [(olang, t, "romanized") for t in l["orig"]] +
                                      [(olang, t, "official") for t in l["native"]]):
                if title:
                    c.execute("INSERT OR IGNORE INTO work_title VALUES(?,?,?,?)", (wid, lang, title, kind))
    ex_isbn, targets = {}, {}
    for market in ("DE", "EN", "FR"):
        E_, e_isbn = KI.existing_lines(db, market)
        ex_isbn[market] = e_isbn
        targets.update(E_)
    for ln in lines:
        src, role = ln["source"], ln["role"]
        rid = ln["target"] if role == "merged" else ln["tome_id"]
        exported = ln["exported"]
        if exported and role != "merged":
            c.execute("""INSERT INTO release_line (id,work_id,parent_id,medium,market,language,publisher,format,
                         created_at,updated_at) VALUES(?,?,NULL,?,?,?,?,?,?,?)""",
                      (rid, ln["work"], ln["medium"], ln["market"], ln["language"], ln["publisher"],
                       B.FORMAT.get(ln.get("edition")), NOW, NOW))
            _claim(c, "release_line", rid, "line_name", ln["name"], src, member_url(ln["key"]))
            if ln["publisher"]:
                _claim(c, "release_line", rid, "publisher", ln["publisher"], src, member_url(ln["key"]))
        tvols = targets.setdefault(rid, {"work": ln["work"], "medium": ln["medium"], "vols": {}})["vols"] \
            if role == "merged" else {}
        e_isbn = ex_isbn[ln["market"]]
        n_out = 0
        for v in ln["vols"]:
            if src == "loc":
                v["isbn"] = LM.pick_isbn(v["cands"], e_isbn)
            fate, vid, filled = "line_" + role, None, None
            hit = None if role == "adopting" else next((e_isbn[i] for i in v["isbns"] if i in e_isbn), None)
            if exported and hit:
                vid, fate = hit[1], "attached"
            elif exported:
                if v["date"] and v["date"][0] == "HELD":
                    fate = "held_future"
                elif not v["isbn"] and not v["date"]:
                    fate = "dropped_no_date_no_isbn"
                elif v["number"] in tvols:
                    wvid, wisbn = tvols[v["number"]]
                    if wisbn and wisbn not in v["isbns"]:
                        fate = "dropped_number_clash"
                    else:
                        vid, fate = wvid, "attached"
                else:
                    vid = _id("v_", rid, v["number"]) if role == "merged" else vol_id(ln, v["number"])
                    fate = "created"
                    d = v["date"] if v["date"] else (None, None, None)
                    c.execute("""INSERT OR IGNORE INTO volume (id,release_line_id,number,title,isbn13,page_count,format,
                                 release_date,release_date_precision,release_date_type,created_at,updated_at)
                                 VALUES(?,?,?,NULL,?,?,?,?,?,?,?,?)""",
                              (vid, rid, v["number"], v["isbn"], v["pages"], B.FORMAT.get(ln.get("edition")),
                               d[0], d[1], d[2] or "unknown", NOW, NOW))
                    if role == "merged":      # a later line merged into the same target meets this number
                        tvols[v["number"]] = (vid, v["isbn"])
            if vid:
                _volume_claims(c, vid, v, src, own if fate == "attached" else None)
                if fate == "attached":
                    done = B.fill_attached(c, vid, {"isbn": v["isbn"], "date": v["date"], "pages": v["pages"]})
                    filled = json.dumps(done) if done else None
                n_out += fate == "created"
            st[fate] += 1
            dated = int(bool(v["date"] and v["date"][0] != "HELD"))
            for m in v["members"]:
                c.execute("""INSERT OR REPLACE INTO krcn_member (member,line_key,number,isbn13,volume_id,fate,filled,
                             announced_only,dated,paged) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                          (m, ln["key"], v["number"], v["isbn"], vid, fate, filled, int(bool(v["announced"])), dated,
                           int(bool(v["pages"]))))
        if exported and role != "merged" and not n_out and not c.execute(
                "SELECT 1 FROM volume WHERE release_line_id=?", (rid,)).fetchone():
            # every volume attached elsewhere or held back: no empty line (3e's 'absorbed')
            c.execute("DELETE FROM release_line WHERE id=?", (rid,))
            c.execute("DELETE FROM claim WHERE entity='release_line' AND entity_id=?", (rid,))
            ln["role"], ln["exported"] = "absorbed", False
        fate_of = {m: (vid, f) for m, vid, f in c.execute(
            "SELECT member, volume_id, fate FROM krcn_member WHERE line_key=?", (ln["key"],))}
        for row in ln["loc"]:
            vid, f = fate_of.get(row[7], (None, None))
            c.execute("""INSERT OR REPLACE INTO loc_member (lccn,number,f040a,encoding_level,date_type,set_record,
                         f263,member,line_key,volume_id,fate) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                      tuple(row) + (ln["key"], vid, f))
        c.execute("""INSERT OR REPLACE INTO krcn_line (key,source,market,rl_id,carried,work,name,publisher,medium,
                     medium_why,medium_guess,n_volumes,origin,explicit,comic,tier,via,link_work,candidates,role,
                     reason,cluster,target,exported) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (ln["key"], src, ln["market"], staged_rl_id(ln), int(bool(ln["carried"])),
                   ln["work"] if ln["exported"] else None, ln["name"], ln["publisher"], ln["medium"],
                   ln.get("medium_why"), ln.get("medium_guess"), len(ln["vols"]), ln["origin"],
                   int(bool(ln["explicit"])), int(bool(ln["comic"])), ln["tier"], ln["via"], ln["link_work"],
                   json.dumps(ln["candidates"][:8]), ln["role"], ln["reason"], ln["cluster"], ln.get("target"),
                   int(bool(ln["exported"]))))
    # the lift (spec 2026-10-01, F1a): a CREATED work none of whose lines export (every volume held back by the date
    # rule, attached elsewhere...) is not written: its lines stay `absorbed` with no work, the plan forgets it, and
    # the deterministic id appears in a later build once a volume publishes. A frozen work is never dropped here
    # (a published work with no exported line is a carried-id problem, caught by the carried-id gates).
    for wid in [w for w, e in plan["works"].items() if e["created"] and w in made and not any(
            by_key[k]["exported"] for k in e["lines"] if k in by_key)]:
        c.execute("DELETE FROM work_title WHERE work_id=?", (wid,))
        c.execute("DELETE FROM work WHERE id=?", (wid,))
        made.remove(wid)
        for k in plan["works"].pop(wid)["lines"]:
            if k in by_key:
                by_key[k]["work"] = None
        print("  work %s not written: none of its lines export (every volume held back or attached elsewhere)" % wid)
    for m, fate, key in lost:
        c.execute("""INSERT OR IGNORE INTO krcn_member (member,line_key,number,isbn13,volume_id,fate,filled,
                     announced_only,dated,paged) VALUES(?,?,NULL,NULL,NULL,?,NULL,0,0,0)""", (m, key, fate))
        st[fate] += 1
    adopted = []
    for ln in lines:                                   # R1 / P2: before 4c and 7b, never a redirect
        if ln["role"] == "adopting" and ln["exported"]:
            for x in adopt(c, ln["target"], ln["tome_id"], ln["key"])[2]:
                print("  WARNING adoption ISBN clash -- %s (%s) v.%s: Wikipedia ISBN %s is on another volume of the "
                      "line; kept %s (review: gate adoption_isbn_clash)" % tuple(x))
                plan.setdefault("adoption_isbn_clash", []).append(x)
            adopted.append(["release_line", ln["target"], ln["tome_id"]])
    conflicts = {tuple(t) for t in plan.get("adopt_conflicts", [])}
    for internal, public in plan["adopt_works"]:
        if (internal, public) in conflicts:          # decide reported it (gate_report adopt_conflicts)
            # the one case left (two adopters raised above): `public` is a library work this build ships
            # (created or frozen); the moved lines ship under it already, `internal` keeps its own id
            print("  ADOPTION CONFLICT -- work %s -> %s not renamed: %s is a library work this build already ships "
                  "(its lines moved under it); %s keeps its id (gate_report adopt_conflicts)"
                  % (internal, public, public, internal))
            continue
        KI.rename_work(c, internal, public)
        adopted.append(["work", internal, public])
    for k, v in (("krcn:adopted", adopted), ("krcn:works_made", made)):
        c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", (k, json.dumps(v, sort_keys=True)))
    db.commit()
    return st


def _tsv(path, header, rows):
    with open(path, "w", encoding="utf8") as f:
        f.write("\t".join(header) + "\n")
        for r in rows:
            f.write("\t".join(str(x if x is not None else "").replace("\t", " ").replace("\n", " ") for x in r) + "\n")


def write_files(lines, plan, idx, stats):
    """build/krcn-review.tsv, krcn-held.tsv (R6, §9: every held cluster with its lines, member keys,
    reason, candidate title keys and the four criteria), krcn-new-works.tsv, krcn-duplicates.tsv (the
    lift: duplicate_rows; stage 8a adds its AniList-id rows), krcn-report.json.
    -> (review lines, held clusters)."""
    os.makedirs(BUILD, exist_ok=True)
    rev = sorted((l for l in lines if l["role"] == "review"), key=lambda l: (l["reason"] or "", -len(l["vols"]), l["key"]))
    _tsv(os.path.join(BUILD, "krcn-review.tsv"),
         ["reason", "tier", "via", "line_key", "market", "name", "publisher", "medium", "volumes", "candidates",
          "original_titles", "native_titles", "authors", "url"],
         [(l["reason"], l["tier"], l["via"], l["key"], l["market"], l["name"], l["publisher"], l["medium"], len(l["vols"]),
           "; ".join("%s %s" % (w, idx.name.get(w, "?")) for w in l["candidates"][:6]), " | ".join(l["orig"][:3]),
           " | ".join(l["native"][:3]), " | ".join(l["authors"][:3]), member_url(l["key"])) for l in rev])
    by = {l["key"]: l for l in lines}
    # every held line has its plan['held'] entry (decide: novel-without-comic, the one reason since the
    # lift), so the hold file is exactly plan['held']
    held = list(plan["held"])
    _tsv(os.path.join(BUILD, "krcn-held.tsv"),
         ["cluster", "reason", "markets", "lines", "members", "volumes", "title_keys", "criteria"],
         [(h["cluster"], h["reason"], ",".join(h["markets"]), " ".join(h["lines"]),
           " ".join(m for k in h["lines"] for m in by[k]["members"][:10]), h["volumes"], " | ".join(h["title_keys"]),
           json.dumps(h["criteria"], sort_keys=True)) for h in held])
    _tsv(os.path.join(BUILD, "krcn-new-works.tsv"),
         ["work_id", "anchor_key", "title", "markets", "lines", "volumes", "verdict", "existing_work", "reason"],
         [(w, e["anchor"], e["title"], ",".join(sorted({by[k]["market"] for k in e["lines"] if k in by})),
           " ".join(e["lines"]), sum(len(by[k]["vols"]) for k in e["lines"] if k in by), "", "", "")
          for w, e in sorted(plan["works"].items()) if e["created"]])
    _tsv(os.path.join(BUILD, "krcn-duplicates.tsv"), DUP_HEADER, duplicate_rows(lines, plan, idx))
    with open(os.path.join(BUILD, "krcn-report.json"), "w", encoding="utf8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=1, sort_keys=True)
    return len(rev), len(held)


def run(dbpath, carry=None):
    db = sqlite3.connect(dbpath, timeout=60)
    db.executescript(STAGING_DDL)
    unload(db.cursor())
    db.commit()
    # a DNB stop in stage 3e (another process) carries into 3f: no DNB refetch after 3e's sticky stop --
    # stale sets are served from the cache and the run is degraded (read AFTER unload: 3f's own old part is gone)
    seed = _meta(db, "dnb:degraded")
    if seed and not S.DEGRADED[0]:
        S.DEGRADED[0] = "stage 3e: %s" % json.loads(seed).get("reason")
        print("  DNB degraded in stage 3e (%s) -- 3f refetches nothing from DNB" % S.DEGRADED[0], flush=True)
    print("  enumerating (cached; live requests go to build/{dnb,loc,bnf}-netlog.tsv)", flush=True)
    d_recs, d_parents, d_tally = E.enumerate_krcn(verbose=False)
    gaps = {k: v for k, v in d_tally.items() if k.endswith("_slice_gap") and v}
    if gaps and not d_tally.get("degraded"):
        raise SystemExit("DNB KR/CN enumeration incomplete -- slices miss records: %s" % gaps)
    l_recs, l_report = LS.enumerate_loc(verbose=False)            # the canary first; fails the stage on a bad canary
    b_recs, b_tally = BS.enumerate_bnf(verbose=False)
    lines, lost, src_stats = [], [], {}
    for name, (ls_, lo, st_) in (("dnb", KL.dnb_lines(d_recs, d_parents)), ("loc", KL.loc_lines(l_recs)),
                                 ("bnf", KL.bnf_lines(b_recs))):
        lines += ls_
        lost += lo
        src_stats[name] = st_
    # P25: a DNB set whose volumes split between the rounds gives BOTH rounds the key 'dnb:<parent IDN>'
    # (14 such sets in the cached records, King of Hell's published German line among them). The German
    # JP round keeps the key (its output is frozen); 3f defers the line -- not staged, listed in the
    # report -- BEFORE the Ize order and ids, and its ids are reserved from line_ids.
    try:
        jp_rows = db.execute("SELECT key, rl_id FROM dnb_line").fetchall()
    except sqlite3.OperationalError:
        jp_rows = []
    lines, deferred, reserved = defer_jp_round(lines, jp_rows)
    jp_keys = {k for k, _ in jp_rows}
    lost = [x for x in lost if x[2] not in jp_keys]
    isbn_medium = dict(db.execute("""SELECT v.isbn13, rl.medium FROM volume v JOIN release_line rl
                                     ON rl.id=v.release_line_id WHERE v.isbn13 IS NOT NULL
                                     ORDER BY rl.id DESC, v.id DESC"""))   # deterministic: the lowest line wins
    KL.resolve_media(lines, isbn_medium)
    K = KI.read_carry(carry) or NO_K
    id_rep = KI.line_ids(lines, K, reserved=reserved)
    line_medium, E_all = {}, {}
    for market in ("DE", "EN", "FR"):
        E_, e_isbn = KI.existing_lines(db, market)
        E_all.update(E_)
        line_medium.update({r: e["medium"] for r, e in E_.items()})
        KI.attach_roles([l for l in lines if l["market"] == market], E_, e_isbn, K)
    idx = L.Index(db)
    present = dict(db.execute("SELECT id, work_id FROM release_line"))      # before 3f loads (unload ran)
    comic_works = {w for (w,) in db.execute("SELECT DISTINCT work_id FROM release_line WHERE medium IN (?,?,?,?)",
                                            KL.COMIC_MEDIA)}
    plan = decide(lines, idx, K, CORR.load_link_work(), comic_works, line_medium,
                  jp_override=CORR.load_jp_guard_overrides(), present=present,
                  cluster_with=CORR.load_cluster_with(), review_lines=CORR.load_review_lines(),
                  deferred={l["key"] for l in deferred})
    fates = load(db, lines, lost, plan, K)
    # CI's reachability probe (catalogue.yml): a source read from the cache because its gateway was unreachable
    offline = {src: {"reason": "unreachable", "stale_sets": len(o.stale_queries)} for src, o in (("loc", LS.LOC), ("bnf", BS.BNF))
               if os.environ.get(src.upper() + "_UNREACHABLE") == "1"}
    record_meta(db, lines, plan, {"loc": l_report, "bnf": b_tally, "dnb": d_tally}, offline)
    roles = collections.Counter((l["market"], l["role"]) for l in lines)
    exported = collections.Counter(l["market"] for l in lines if l["exported"])
    stats = {"sources": src_stats, "dnb_tally": d_tally,
             "loc": {k: l_report.get(k) for k in ("distinct", "live_requests", "degraded", "degraded_queries")},
             "bnf": b_tally, "ids": id_rep, "roles": {"%s %s" % k: n for k, n in sorted(roles.items())},
             "exported_lines": dict(exported), "volume_fates": dict(fates),
             "works_created": sum(1 for e in plan["works"].values() if e["created"]),
             "works_frozen": sum(1 for e in plan["works"].values() if not e["created"]),
             "held_clusters": len(plan["held"]), "adopted": json.loads(_meta(db, "krcn:adopted") or "[]"),
             "deferred_to_jp_round": sorted(l["key"] for l in deferred), "offline": offline,
             "gate": gate_report(lines, plan, id_rep, K, E_all, deferred)}
    n_rev, n_held = write_files(lines, plan, idx, stats)
    db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('krcn:stats',?)", (json.dumps(stats, sort_keys=True),))
    db.commit()
    print("  lines %d: %s" % (len(lines), ", ".join("%s %s %d" % (m, r, n) for (m, r), n in sorted(roles.items()))))
    print("  exported lines: %s" % ", ".join("%s %d" % kv for kv in sorted(exported.items())))
    print("  works: created %d, frozen %d; held clusters %d; review %d -> build/krcn-review.tsv" % (
        stats["works_created"], stats["works_frozen"], len(plan["held"]), n_rev))
    print("  volume fates: %s" % ", ".join("%s %d" % kv for kv in sorted(fates.items())))
    print("  ids: carried lines kept %d, taken %d (weak %d for the gate, %d raw incl. 0-of-0), left %d; adopted %d" % (
        id_rep["kept"], len(id_rep["taken"]), len(stats["gate"]["taken_weak"]), len(id_rep["taken_weak"]),
        len(id_rep["left"]), len(stats["adopted"])))
    if deferred:
        print("  deferred to the German JP round (a DNB set split across the rounds, P25): %d %s" % (
            len(deferred), stats["deferred_to_jp_round"][:5]))
    print("  live requests: DNB %d, LoC %d, BnF %d" % (S.live_requests[0], LS.LOC.live, BS.BNF.live))
    return stats


def same_ids(catalogue, carry):
    """Rebuild the KR/CN lines offline from the cached records, with the carry lookup, and compare:
    every exported non-merged krcn_line row must get the same rl_id (§13 'The idempotent reload gives
    the same ids'). The steps before the ids mirror run(): the P25 deferral and its reserved ids from
    the catalogue's dnb_line. Adopting rows keep their public (carried) id by construction and merged
    rows ship inside another line, so both are left out (the offline reload has no attach roles). An
    uncached result set fails the gate (R7), it never goes live. -> (ok, detail)."""
    for s in ("DNB", "LOC", "BNF"):
        os.environ[s + "_OFFLINE"] = "1"
    S.OFFLINE = True
    LS.LOC.offline = BS.BNF.offline = True
    report, LS.REPORT = LS.REPORT, None       # stage 3f's build/loc-report.json is not this gate's to rewrite
    try:
        d_recs, d_parents, _ = E.enumerate_krcn(verbose=False)
        l_recs = LS.enumerate_loc(verbose=False)[0]
        b_recs = BS.enumerate_bnf(verbose=False)[0]
    except SRU.FAIL as e:           # an offline miss, a failed canary, an incomplete set
        return False, "the cached records are incomplete (%s: %s)" % (type(e).__name__, e)
    finally:
        LS.REPORT = report
    lines = KL.dnb_lines(d_recs, d_parents)[0] + KL.loc_lines(l_recs)[0] + KL.bnf_lines(b_recs)[0]
    C = sqlite3.connect(catalogue)
    try:
        jp_rows = C.execute("SELECT key, rl_id FROM dnb_line").fetchall()
    except sqlite3.OperationalError:
        jp_rows = []
    lines, _, reserved = defer_jp_round(lines, jp_rows)
    KI.line_ids(lines, KI.read_carry(carry) or NO_K, reserved=reserved)
    now = {l["key"]: l["tome_id"] for l in lines}
    was = dict(C.execute("SELECT key, rl_id FROM krcn_line WHERE exported=1 AND role NOT IN ('merged','adopting')"))
    moved = sorted(k for k, rid in was.items() if now.get(k) != rid)
    return (not moved and set(was) <= set(now),
            "%d exported lines, %d with another id on reload %s" % (len(was), len(moved), moved[:3]))


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else os.path.join(BUILD, "opentome.db"),
        sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] else None)
