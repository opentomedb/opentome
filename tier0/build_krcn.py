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
  6. decide      link (full-name authors, JP guard, link_work), cluster the unlinked lines of all
                 markets, create works that pass §9's four criteria AND have an English line, hold the
                 rest (R6: no id, no integer, build/krcn-held.tsv), keep published lines, adopt ids (R1)
  7. load        works, lines, volumes, claims (source dnb / loc / bnf, their licences, record urls),
                 staging krcn_line / krcn_member / loc_member, adoption renames -- all BEFORE 4c / 7b
  8. files       build/krcn-review.tsv, krcn-held.tsv, krcn-new-works.tsv, krcn-report.json
                 (gate_report: the Task 15 publish-gate lists)

Library works are created AFTER Wikipedia works and linking, so a work Wikipedia knows is never
duplicated in the same build (§9). No covers, no 856, no publisher summaries from any library.
"""
import collections, json, os, re, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "schema"))
sys.path.insert(0, os.path.join(ROOT, "tier2"))
import dnb_link as L
import krcn_identity as KI
from load import _id

EXPORTED = ("merged", "sibling", "adopting", "linked", "kept", "new_work")
ROLES = EXPORTED + ("held", "review", "unlinked", "absorbed")
ATTACHED = ("merged", "sibling", "adopting")
LATIN_MIN = 5
KANA_CJK = re.compile("[぀-ヿ一-鿿]+")
NO_K = {"works": set(), "lines": {}, "series_ids": set(), "work_ids": set(), "int": {}, "line_work": {},
        "line_name": {}, "line_medium": {}, "line_pub": {}, "line_vols": {}}

STAGING_DDL = """
CREATE TABLE IF NOT EXISTS krcn_line (      -- one row per KR/CN library line, exported or not.
                                            -- Placeholder for the controller ruling (a work column);
                                            -- Task 14 owns the staging DDL (krcn_member, loc_member)
    key TEXT PRIMARY KEY,                   -- 'dnb:<IDN>' | 'loc:<LCCN>' | 'bnf:<ark>' (krcn_lines)
    source TEXT NOT NULL, market TEXT NOT NULL,
    rl_id TEXT NOT NULL,                    -- the line's tome_id: carried (kept or taken) or minted;
                                            -- a held / review / unlinked row's id is never loaded
                                            -- (R6: absent from release_line, id_map, the artifact)
    carried INTEGER NOT NULL,
    work TEXT,                              -- the work it ships under (NULL unless exported);
                                            -- rename_work follows adoption renames
    name TEXT, publisher TEXT, medium TEXT, medium_why TEXT, medium_guess TEXT,
    n_volumes INTEGER,
    tier TEXT, via TEXT, link_work TEXT, candidates TEXT,
    role TEXT NOT NULL,                     -- build_krcn.ROLES
    reason TEXT, cluster TEXT,
    target TEXT,                            -- merged / sibling / adopting: the existing line
    exported INTEGER NOT NULL);
"""


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


def cluster_keys(ln):
    """§10 step 1: folded titles and Hangul / Hanzi keys join lines across markets; a romanised
    original title joins only lines of the same library (DNB syllable-splits, LoC writes ALA-LC)."""
    ks = set()
    for t in list(ln["titles"]) + list(ln["native"]) + [ln["name"] or ""]:
        k = L.fold(t, False)
        if _key_ok(k):
            ks.add(("t", k))
    for t in ln["orig"]:
        k = L.fold(t, False)
        if _key_ok(k):
            ks.add(("o", ln["source"], k))
    return ks


def clusters(pool):
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
    groups = collections.defaultdict(list)
    for i, ln in enumerate(pool):
        groups[find(i)].append(ln)
    return sorted((sorted(g, key=lambda l: l["key"]) for g in groups.values()), key=lambda g: g[0]["key"])


def containment_hits(cluster, idx):
    """§9 criterion 4: existing KR/CN works whose official title key contains, or is contained in, a
    key of the cluster (both 5+ characters), and any existing work whose official key equals one of the
    cluster's original / native title keys. Catches DE 'Raeliana' (= Why Raeliana Ended Up at the
    Duke's Mansion); not Athanasia (syllable-split romanisation -- the review file's job)."""
    kr = [(k, w) for k, ws in idx.official.items() for w in ws if w in idx.krcn_works and len(k) >= LATIN_MIN]
    hits = set()
    for ln in cluster:
        for t in list(ln["titles"]) + list(ln["native"]) + [ln["name"] or ""]:
            k = L.fold(t, False)
            if len(k) >= LATIN_MIN:
                hits |= {w for ok, w in kr if ok in k or k in ok}
        for t in list(ln["orig"]) + list(ln["native"]):
            k = L.fold(t, False)
            if L.key_ok(k):
                hits |= idx.official.get(k, set())
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


def decide(lines, idx, K, link_work=None, comic_works=(), line_medium=None):
    """The decision order of the module plan (Task 12), steps 1-7. Pure: no database.
    Review reasons from the line builder (controller ruling): a line with medium_why goes to review
    with reason = medium_why verbatim ('duplicate_numbers', 'both', 'writer_only', '+'-joined in that
    order) -- attached or not; a link_work correction ships it with its medium_guess (none: it stays
    in review). A LoC line with no medium and no medium_why: 'ize-medium' | 'no-class-signal'."""
    K = K or NO_K
    link_work, line_medium = link_work or {}, line_medium or {}
    plan = {"works": {}, "clusters": [], "held": [], "adopt_works": [], "review": [], "adopt_conflicts": []}
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
                      % (ln["key"], ln["role"], ln["work"], lw, "" if lw == ln["work"] else ", CONFLICT"))
            if ln["medium"] is None and not ln["medium_why"]:
                ln["medium"] = _class(line_medium.get(ln.get("target")), ln["origin"])
        else:
            ln["role"] = None
            if lw and lw in idx.name:
                ln.update(role="linked", work=lw, via="correction", link_work=lw)
            else:
                if lw:
                    print("  STALE CORRECTION -- lines.json link_work %s -> %s: not a work in the catalogue" % (ln["key"], lw))
                tier, w, cands, via = _link(idx, ln)
                ln.update(tier=tier, link_work=w, candidates=cands, via=via)
                if tier in ("high", "medium"):
                    ln.update(role="linked", work=w)
                elif tier in ("low", "ambiguous"):
                    ln.update(role="review", reason=tier)
            if ln["role"] == "linked" and idx.jp_guard(ln["work"]):    # P17: a correction does not lift it
                ln.update(role="review", reason="jp-guard", work=None)
        if ln["medium"] is None:
            confirmed = lw is not None and lw == ln["work"] and ln["role"] in ("linked",) + ATTACHED
            if confirmed and ln["medium_guess"]:
                ln["medium"] = ln["medium_guess"]
            elif ln["medium_why"]:
                ln.update(role="review", reason=ln["medium_why"], work=None)
            elif ln["role"] in (None, "linked") + ATTACHED:
                # §7: 'neither' goes to review -- an Ize ECIP record, or any LoC record with no class signal
                ln.update(role="review", reason="ize-medium" if ln.get("ize") else "no-class-signal", work=None)
        if ln["role"] is None:
            pool.append(ln)
    for n, cl in enumerate(clusters(pool)):                           # 3-4
        cid = "c%04d" % n
        for ln in cl:
            ln["cluster"] = cid
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
        en = [l for l in cl if l["market"] == "EN"]
        hits = containment_hits(cl, idx)
        c2, c3 = any(l["explicit"] for l in cl), any(l["comic"] for l in cl)
        entry = _entry(cid, cl, {"linker": "none", "explicit_origin": c2, "comic": c3, "containment": sorted(hits)}, None)
        plan["clusters"].append(entry)
        frozen = sorted({K["line_work"].get(l["tome_id"]) for l in cl if l["carried"]} & set(K["works"]))
        if frozen:
            # a published library work is never demoted: it exports even without an English line
            wid, created = KI.older(frozen, K), False
            entry["reason"] = "frozen"
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
        elif not en:
            entry["reason"] = "no-english-line"
            plan["held"].append(entry)
            for ln in cl:
                ln.update(role="held", reason="no-english-line", work=None)
            continue
        else:
            wid, created = _id("w_", "krcn", min(l["key"] for l in en)), True
        entry["work"] = wid
        anchor = min(en, key=lambda l: l["key"]) if en else cl[0]
        plan["works"][wid] = {"anchor": anchor["key"], "created": created, "title": anchor["name"],
                              "lines": [l["key"] for l in cl], "cluster": cid, "frozen": frozen}
        for ln in cl:
            ln.update(role="new_work", work=wid)
        idx.add_krcn_work(wid)
    for ln in lines:                                                   # 5
        if ln["role"] in ("review", "unlinked", "held") and ln["carried"]:
            w = K["line_work"].get(ln["tome_id"])
            if w and (w in idx.name or w in plan["works"] or w in K["works"]):
                ln.update(role="kept", work=w, reason=(ln["reason"] or "") + ";kept")
                ln["medium"] = ln["medium"] or K["line_medium"].get(ln["tome_id"]) or ln["medium_guess"]
                if w not in idx.name:
                    e = plan["works"].setdefault(w, {"anchor": ln["key"], "created": False, "title": ln["name"],
                                                     "lines": [], "cluster": ln["cluster"], "frozen": [w]})
                    e["lines"].append(ln["key"])
    comic_now = set(comic_works) | set(plan["works"]) | {                # 6
        ln["work"] for ln in lines if ln["role"] in EXPORTED and ln["medium"] and ln["medium"] != "novel"}
    for ln in lines:
        if ln["medium"] == "novel" and ln["role"] in ("linked", "sibling", "adopting") and \
                ln["work"] not in comic_now and not ln["carried"]:
            ln.update(role="held", reason="novel-without-comic", candidates=[ln["work"]], work=None)
            plan["held"].append(_entry(ln["cluster"], [ln], {"novel_without_comic": ln["candidates"]},
                                       "novel-without-comic"))
    for e in plan["held"]:                                             # a published line is never held
        e["lines"] = [k for k in e["lines"] if k not in {l["key"] for l in lines if l["role"] == "kept"}]
    plan["held"] = [e for e in plan["held"] if e["lines"]]
    libs = collections.defaultdict(set)                                # 7
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
                    ln["work"] = public
    # rename_work(W, public) needs `public` absent: a frozen work of this build, or two works adopting one
    # public id, would collide -- reported (gate_report adopt_conflicts), never resolved silently
    plan["adopt_conflicts"] = sorted((w, p) for w, p in plan["adopt_works"] if p in plan["works"] or publics[p] > 1)
    for ln in lines:
        ln["exported"] = ln["role"] in EXPORTED
        if not ln["exported"]:
            ln["work"] = None
        if ln["role"] == "review":
            plan["review"].append(ln["key"])
    return plan


def _isbns(vols):
    return {i for _, i in vols if i}


def gate_report(lines, plan, rep, K, E=None, deferred=()):
    """The lists the Task 15 publish gate reads (controller rulings, krcn-report.json). Pure.
    rep: krcn_identity.line_ids' report; E: krcn_identity.existing_lines' E, merged over the markets.
      taken_weak           step-2 takes without a strict majority of the carried line's ISBNs
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
    """
    K, E = K or NO_K, E or {}
    taken = {k for _, k in rep.get("taken", [])}
    lv = K.get("line_vols") or {}
    out = {"taken_weak": [list(t) for t in rep.get("taken_weak", [])], "left": list(rep.get("left", [])),
           "kept_no_overlap": [], "absorbed_weak": [], "p22_thin": [], "work_redirects": [],
           "adopt_conflicts": [list(t) for t in plan.get("adopt_conflicts", [])],
           "carried_not_exported": [], "carried_work_changed": [], "hangul_only_authors": [],
           "authors_differ": [], "deferred_to_jp_round": sorted(ln["key"] for ln in deferred)}
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
