"""KR/CN release lines from library records, one builder per source (docs/krcn-design.md §5-§8, §12).
Pure: records in, line dicts out -- no database, no network. tier0/krcn_identity.py gives them ids;
tier0/build_krcn.py links, clusters, creates and loads them.

A line dict (every source):
  key         natural key, from source data only (§8): 'dnb:<parent IDN | lowest member IDN>'
              (build_dnb's rule), 'loc:<LCCN of a set record | lowest kept member LCCN>' (string order
              of the normalised LCCN), 'bnf:<ark with the lowest 8-digit record number among the kept
              volumes>' -- a LoC / BnF key is always one of the line's own volumes
  source      'dnb' | 'loc' | 'bnf'; market 'DE' | 'EN' | 'FR'; language 'de' | 'en' | 'fr'
  name, publisher, pubfam, edition (DNB only; else None)
  medium      'manhwa' | 'manhua' | 'novel' | None. None = the line goes to REVIEW: medium_why says
              why, and a LoC line with medium_why None is an unresolved class (§7, the Ize order;
              build_krcn's reason 'ize-medium')
  medium_why  the review reason(s) when medium is None, else None: one reason, or several joined by
              '+' in this order (read it with medium_why.split('+')):
                'duplicate_numbers'  two volumes of one number were left over (a novel and its comic
                                     merged, a re-edition under the same key: controller ruling 3c)
                'both'               a comic AND a prose signal (LoC, §7)
                'writer_only'        DNB: no illustrator credit and median pages >= 320 -- a web-novel
                                     edition the publisher classed as a comic (ruling 3b)
              e.g. 'duplicate_numbers+both' (LoC). A LoC line with medium None and medium_why None is
              an unresolved class (the Ize order, resolve_media).
  medium_via  set by resolve_media only, on a LoC line it resolved: 'isbn' (an existing OpenTome line
              holds one of its ISBNs) | 'title' (a DE / FR comic line of the same title); absent otherwise
  medium_guess the medium the line would have without its review reason (None when unknown)
  origin      'kor' | 'chi' (majority of members); explicit: any member has 041$h / 101$c or a
              translation statement (§9 criterion 2); comic: any comic-classified volume, and never
              on a line whose medium (or guess) is novel (criterion 3)
  ize         LoC only: an Ize Press record among the members
  vols        [{"number", "isbn" (picked; build_krcn re-picks against existing ISBNs), "cands"
              [(isbn13, qualifiers)], "isbns", "pages", "date" (value, precision, type) | ('HELD', ..)
              | None, "date_member" (the member key whose record dated it), "members", "announced",
              "set_record"}]
  titles      title strings that key everywhere (title proper, bare title, series, Latin variants),
              one string per FIELD -- never joined, so an English and a Hangul title each key
  orig        romanised original titles -- they key within ONE library only (§10)
  native      Hangul / Hanzi titles (a field with any Hangul / Hanzi) -- they key everywhere
  authors, members (every member key), loc ([loc_member row tuples], LoC only)
Member keys: 'dnb:<IDN>', 'loc:<LCCN>' (a single-volume record), 'loc:<LCCN>#<volume>' (a volume of
a set record), 'bnf:<ark>'.
stats (every builder): records, kept_records, dropped {reason: n}, lines, review {medium_why: n}.
"""
import collections, re, statistics

import build_dnb as B
import dnb_link as L
import dnb_marc as M
import loc_marc as LM
import bnf_unimarc as U

COMIC_MEDIA = ("manga", "manhwa", "manhua", "webtoon")
SCRIPT = re.compile("[가-힣一-鿿]")
DUP = "dropped_duplicate_number"


def script_title(t):
    return bool(SCRIPT.search(t or ""))


def _medium(origin, prose):
    return "novel" if prose else ("manhwa" if origin == "kor" else "manhua")


def _majority(xs):
    c = collections.Counter(x for x in xs if x)
    return c.most_common(1)[0][0] if c else None


def _review(ln, why):
    """Send a line to review: medium None, the reason, the would-be medium kept aside."""
    ln["medium_guess"], ln["medium"], ln["medium_why"] = ln["medium"], None, why


def _stats(recs, kept, drop, lines, **extra):
    st = {"records": len(recs), "kept_records": kept, "dropped": dict(drop), "lines": len(lines),
          "review": dict(collections.Counter(ln["medium_why"] for ln in lines if ln["medium_why"]))}
    st.update(extra)
    return st


def _number_volumes(vols, one_shot_ok):
    """One volume per number (vols pre-sorted by preference); an unnumbered volume is volume 1 of a
    one-volume line only when one_shot_ok (build_dnb.shape_line's rule). -> (kept, [(vol, fate)])."""
    out, lost, seen = [], [], set()
    for v in vols:
        num = v["number"]
        if num is None:
            if len(vols) == 1 and one_shot_ok:
                num = "1"
            else:
                lost.append((v, "dropped_unnumbered"))
                continue
        if num in seen:
            lost.append((v, DUP))
            continue
        seen.add(num)
        out.append(dict(v, number=num))
    return out, lost


# ---- DNB ------------------------------------------------------------------------------------------------

# Controller ruling 3 (2026-09-27, KR/CN mapping only -- dnb_marc.classify and the JP round unchanged):
# DNB / VLB class Altraverse's Korean web-NOVEL editions 741.5 / XAM like its comics.
ROMAN = re.compile(r"\broman\b", re.I)
# a drawing role in 245 $c ('Zeichn.:', 'Zeichnungen:', 'Art:', 'Artwork:', 'Illustrationen:')
DRAW_ROLE = re.compile(r"zeichn|illustr|artwork|\bart\b", re.I)
WRITER_ONLY_PAGES = 320


def _roman(r):
    """A 'Roman' token in 245 $a $b $n $p, 250 or 490 -- never 245 $c ('nach dem Roman von ...' is
    a comic adaptation's credit)."""
    t = " ".join(M.subs(r, "245", "a") + M.subs(r, "245", "b") + M.subs(r, "245", "n") + M.subs(r, "245", "p")
                 + M.subs(r, "250", "a") + M.subs(r, "490", "a"))
    return ROMAN.search(t) is not None


def _illustrator(r):
    """An illustrator credit: a 100 / 700 relator ill / art, or a drawing role in 245 $c."""
    if any(v.strip() in ("ill", "art") for f in M.fields(r, "100") + M.fields(r, "700") for c, v in f if c == "4"):
        return True
    return DRAW_ROLE.search(" ".join(M.subs(r, "245", "c"))) is not None


def dnb_lines(recs, parents):
    """The German KR/CN lines: build_dnb's selection / twins / clustering / numbering unchanged, with
    the KR/CN origin predicate (§4, §5: 'run through the existing DNB parser and clustering unchanged').
    manga -> manhwa (kor) / manhua (chi); light_novel -> novel (§7). Then ruling 3, in this order:
      (c) a volume number left over twice (shape_line's duplicate fate) -> review 'duplicate_numbers';
      (a) a 'Roman' token on any member (or the parent set record) -> novel;
      (b) a comic-classed line with no illustrator credit on any member or on the parent set record
          (8 lines credit 'art' only there) and median pages >= 320 -> review 'writer_only'."""
    allparents = dict(parents)
    allparents.update({k: r for k, r in recs.items() if M.is_parent(r)})
    kept, drop = B.select(recs, allparents, in_scope=M.krcn_in_scope)
    groups, _ = B.twins(kept)
    clusters = B.cluster(groups, allparents)
    lines, lost = [], []
    for key in sorted(clusters):
        ln, l2 = B.shape_line(key, clusters[key], allparents)
        lost += [("dnb:" + m["idn"], f, key) for g, f in l2 for m in g["members"]]
        if not ln["vols"]:
            continue
        rs = [v["r"] for g in ln["vols"] for v in g["members"]]
        origins = [M.krcn_origin(r) for r in rs]
        origin = _majority(o for o, _ in origins)
        parent = allparents.get(key[4:])
        withp = rs + ([parent] if parent is not None else [])
        roman = any(_roman(r) for r in withp)
        prose = ln["medium"] == "light_novel" or roman
        pages = [g["pages"] for g in ln["vols"] if g["pages"]]
        out = {
            "key": key, "source": "dnb", "market": "DE", "language": "de", "name": ln["name"],
            "publisher": ln["publisher"], "pubfam": B.pubkey(ln["publisher"]), "edition": ln["edition"],
            "medium": _medium(origin, prose), "medium_why": None, "medium_guess": None,
            "origin": origin, "explicit": any(e for _, e in origins),
            "comic": not prose and any(g["medium"] == "manga" for g in ln["vols"]),
            "vols": [{"number": g["number"], "isbn": g["isbn"], "cands": [(i, "") for i in g["isbns"]],
                      "isbns": list(g["isbns"]), "pages": g["pages"], "date": g["date"],
                      "date_member": "dnb:" + g["primary"], "members": ["dnb:" + i for i in g["idns"]],
                      "announced": all(v["ann"] for v in g["members"]), "set_record": False}
                     for g in ln["vols"]],
            "titles": [t for t in ln["titles"] if not script_title(t)],
            "orig": [t for t in ln["orig"] if not script_title(t)],
            "native": list(dict.fromkeys(t for t in ln["titles"] + ln["orig"] if script_title(t))),
            "authors": ln["authors"], "members": ["dnb:" + i for g in ln["vols"] for i in g["idns"]], "loc": []}
        if any(f == DUP for _, f in l2):
            _review(out, "duplicate_numbers")
        elif not prose and pages and statistics.median(pages) >= WRITER_ONLY_PAGES and \
                not any(_illustrator(r) for r in withp):
            _review(out, "writer_only")
        lines.append(out)
    return lines, lost, _stats(recs, len(kept), drop, lines)


# ---- LoC ------------------------------------------------------------------------------------------------

# a publisher's catalogue number in 490 / 830 $v ('A Doubleday Anchor original ; AO-44', 'An Evergreen
# book, E-209', 'FA259'): an imprint collection's numbering, not a volume of a series ('3', 'v. 3',
# 'book 4', '#5', 'omnibus' all stay). Measured over every cached LoC record: AO-44, E-209, FA259 only.
CATALOGUE_V = re.compile(r"^\W*[A-Z]{1,4}\s*-?\s*\d+\W*$")


def _drop_catalogue_series(r):
    """The record without its 490 / 830 fields whose $v is a publisher's catalogue code. Such a field
    is an imprint collection (the DNB rule: dnb_marc.series_statements drops a 490 without $v): it
    never names, keys or titles a line, and its $v never numbers a volume (the one-shot rule gives
    '1'). Applied once, at intake (loc_lines), so every LoC reader sees the same record."""
    df = [f for f in r["df"] if not (f[0] in ("490", "830") and
                                     any(c == "v" and CATALOGUE_V.match(v or "") for c, v in f[3]))]
    return r if len(df) == len(r["df"]) else dict(r, df=df)


def _loc_row(r, lc, number, set_record, member):
    return (lc, number, LM.f040a(r), LM.encoding_level(r), LM.date_type(r), int(set_record),
            (M.first(r, "263", "a") or "").strip() or None, member)


def _has_b(r):
    return LM.full_title(r) != LM.title_proper(r)


def _own_title(r):
    """The record's own title with its other title information (controller ruling 2): 'Solo leveling
    : Ragnarok' is a sequel, never 'Solo leveling'. The bare title when there is no 245 $b."""
    if not _has_b(r):
        return LM.bare_title(r)
    return LM.bare_title(r) + LM.full_title(r)[len(LM.title_proper(r)):]


def _loc_titles(rs):
    """Linker titles, one per field. With a 245 $b the full title REPLACES the title proper / bare
    title (ruling 2: the reduced title would link a sequel to its parent)."""
    t = []
    for r in rs:
        t += [_own_title(r), LM.full_title(r)] if _has_b(r) else [LM.title_proper(r), LM.bare_title(r)]
        t += [n for n, _ in LM.series(r)] + LM.variant_titles(r)
    return [x for x in dict.fromkeys(t) if x]


def _loc_line(key, set_rec, singles):
    """One LoC line: a set record's volumes (from its $q ISBNs) and/or single-volume records. key None
    (no set record): 'loc:' + the lowest LCCN among the KEPT volumes' records -- a line key is always
    one of its volumes."""
    rs = ([set_rec] if set_rec is not None else []) + [r for _, r in singles]
    vols = {}
    if set_rec is not None:
        lc = LM.lccn(set_rec)
        for num, cands in LM.volume_isbns(set_rec).items():
            m = "loc:%s#%s" % (lc, num)
            vols[num] = {"number": num, "cands": list(cands), "isbns": [i for i, _ in cands],
                         "isbn": LM.pick_isbn(cands), "pages": None, "date": None, "date_member": None,
                         "members": [m], "announced": LM.is_prelim(set_rec), "set_record": True,
                         "rows": [_loc_row(set_rec, lc, num, True, m)]}
    loose = []
    for lc, r in sorted(singles):
        num = LM.volume_number(r)
        cands = [(i, q) for _, i, q in LM.qualified_isbns(r)]
        m = "loc:" + lc
        row = _loc_row(r, lc, num, False, m)
        twin = next((v for v in vols.values() if set(v["isbns"]) & {i for i, _ in cands}), None)
        if twin is None and num in vols and vols[num]["set_record"]:
            twin = vols[num]
        if twin is not None:                     # the same book as a set volume: it joins it
            twin["members"].append(m)
            twin["rows"].append(row)
            twin["cands"] += [c for c in cands if c[0] not in twin["isbns"]]
            twin["isbns"] = [i for i, _ in twin["cands"]]
            d = LM.volume_date(r, set_record=False)
            if d and not twin["date"]:
                twin["date"], twin["date_member"] = d, m
            twin["pages"] = twin["pages"] or LM.pages(r)
            twin["announced"] = twin["announced"] and LM.is_prelim(r)
            continue
        loose.append({"number": num, "cands": cands, "isbns": [i for i, _ in cands], "isbn": LM.pick_isbn(cands),
                      "pages": LM.pages(r), "date": LM.volume_date(r, set_record=False), "date_member": m,
                      "members": [m], "announced": LM.is_prelim(r), "set_record": False, "rows": [row],
                      "_pref": (LM.is_prelim(r), lc)})
    loose.sort(key=lambda v: v["_pref"])
    one_shot = set_rec is None and len(singles) == 1 and not LM.series(singles[0][1]) and \
        not re.search(r"\d", LM.title_proper(singles[0][1]))
    kept, lost = _number_volumes(loose, one_shot)
    kept = [v for v in kept if v["number"] not in vols]           # a set volume wins its number
    allv = sorted(list(vols.values()) + kept, key=lambda v: (len(v["number"]), v["number"]))
    classes = [LM.classify(r) for r in rs]
    origins = [LM.origin(r) for r in rs]
    origin = _majority(o for o, _ in origins)
    if "both" in classes:
        medium, why = None, "both"
    elif classes and all(c == "prose" for c in classes):
        medium, why = "novel", None
    elif "comic" in classes:
        medium, why = _medium(origin, False), None
    else:
        medium, why = None, None
    pubs = collections.Counter(LM.publisher(r) for r in rs if LM.publisher(r))
    pub = pubs.most_common(1)[0][0] if pubs else None
    name = LM.full_title(set_rec) if set_rec is not None else \
        (next((n for n, _ in LM.series(singles[0][1])), None) or _own_title(singles[0][1]))
    for v in allv:
        v.pop("_pref", None)
    if key is None:
        key = "loc:" + min([m[4:] for v in allv for m in v["members"]] or [lc for lc, _ in singles])
    ln = {"key": key, "source": "loc", "market": "EN", "language": "en", "name": name, "publisher": pub,
          "pubfam": LM.pubfam(pub), "edition": None, "medium": medium, "medium_why": why, "medium_guess": None,
          "origin": origin, "ize": any(LM.is_ize(r) for r in rs),
          "explicit": any(e for _, e in origins), "comic": "comic" in classes and medium != "novel", "vols": allv,
          "titles": [t for t in _loc_titles(rs) if not script_title(t)],
          "orig": list(dict.fromkeys(t for r in rs for t in LM.original_titles(r) if not script_title(t))),
          "native": list(dict.fromkeys(t for r in rs for t in LM.native_titles(r))),
          "authors": list(dict.fromkeys(a for r in rs for a in LM.creators(r))),
          "members": [m for v in allv for m in v["members"]],
          "loc": [row for v in allv for row in v.pop("rows")]}
    if any(f == DUP for _, f in lost):
        _review(ln, "+".join(["duplicate_numbers"] + ([why] if why else [])))
    return ln, [(m, f, key) for v, f in lost for m in v["members"]]


def loc_lines(recs):
    """The English KR/CN lines from LoC (DLC-created records only, R4). recs: {001: record}.
    Scope (§6): DLC first -- a non-DLC record is never read further, not even its 010 (R4, controller
    ruling 1) --, then an LCCN (P9), a print monograph, not a bundle / artbook, KR/CN origin
    (explicit or the Ize imprint). A set record (>= 2 volume-qualified ISBNs) IS a line; single-volume
    records that repeat one of its ISBNs are that volume; the other single-volume records cluster by
    folded series (else their own title, 245 $b included: ruling 2) + publisher family + prose-or-not
    (P23), and join the one set line of that signature when there is exactly one (build_dnb.cluster's
    rule)."""
    drop, keep = collections.Counter(), {}
    for r in recs.values():
        if not LM.is_dlc(r):
            drop["non_dlc"] += 1                 # never read further: not a twin, not a hint (R4)
            continue
        lc = LM.lccn(r)
        if not lc:
            drop["no_lccn"] += 1
            continue
        if not (LM.is_monograph(r) and LM.is_print(r)):
            drop["not_print"] += 1
            continue
        kind = LM.excluded_kind(r)
        if kind:
            drop[kind] += 1
            continue
        if not LM.origin(r)[0]:
            drop["origin_out_of_scope"] += 1
            continue
        keep.setdefault(lc, _drop_catalogue_series(r))
    sets = {lc: r for lc, r in keep.items() if LM.is_set(r)}
    by_isbn = {i: lc for lc, r in sets.items() for cs in LM.volume_isbns(r).values() for i, _ in cs}

    def sig(r):
        s = LM.series(r)
        return (L.fold(s[0][0] if s else _own_title(r), False), LM.pubfam(LM.publisher(r)),
                LM.classify(r) == "prose")
    set_sig = collections.defaultdict(list)
    for lc, r in sets.items():
        set_sig[sig(r)].append(lc)
    attach, groups = collections.defaultdict(list), collections.defaultdict(list)
    for lc, r in sorted(keep.items()):
        if lc in sets:
            continue
        home = next((by_isbn[i] for _, i, _ in LM.qualified_isbns(r) if i in by_isbn), None)
        if home is None and len(set_sig.get(sig(r), [])) == 1:
            home = set_sig[sig(r)][0]
        (attach[home] if home else groups[sig(r)]).append((lc, r))
    lines, lost = [], []
    for lc in sorted(sets):
        ln, l2 = _loc_line("loc:" + lc, sets[lc], attach.get(lc, []))
        lines.append(ln)
        lost += l2
    for s in sorted(groups):
        singles = groups[s]
        ln, l2 = _loc_line(None, None, singles)
        lost += l2
        if ln["vols"]:
            lines.append(ln)
    return lines, lost, _stats(recs, len(keep), drop, lines, set_records=len(sets))


# ---- BnF ------------------------------------------------------------------------------------------------

def bnf_lines(recs):
    """The French KR/CN lines from BnF (§4-§8). Scope: a KR/CN origin -- 101 $c kor / chi, or, for a
    volume with no 101 $c of its own, the 101 $c of the series head it hangs under (461 $0; the head
    is a set record of the same channels) --, a monograph, not a set record (P8), not a bundle /
    range / extra. A relay through English (101 $b eng) stays in (controller ruling). Every record of
    the publisher channels is a comic (§7). ISBN twins (same ISBN, same number) are one volume; an
    ISBN on two DIFFERENT numbers is dropped from both (build_dnb.twins' box-set rule).
    Lines: the volumes of one series head (461 $0) are one line -- two heads are never merged; a
    volume with no 461 $0 joins the one head line of its signature (folded series, else 200 $a, +
    publisher family) when there is exactly one, else lines by that signature. Key 'bnf:' + the ark
    with the lowest record number among the line's KEPT volumes (a line key is always one of its
    volumes). A number left over twice -> review."""
    drop, keep = collections.Counter(), []
    heads = {U.ark_number(U.ark(r)): r for r in recs.values() if U.ark(r)}
    inherited = 0
    for r in recs.values():
        a = U.ark(r)
        if not a:
            drop["no_ark"] += 1
            continue
        o = U.origin(r)
        if not o and U.head_number(r) in heads:
            o = U.origin(heads[U.head_number(r)])
            inherited += bool(o)
        if not o:
            drop["origin_out_of_scope"] += 1
            continue
        if not U.is_monograph(r):
            drop["not_monograph"] += 1
            continue
        if U.is_set_record(r):
            drop["set_record"] += 1
            continue
        kind = U.excluded_kind(r)
        if kind:
            drop[kind] += 1
            continue
        keep.append((U.ark_number(a), a, r, o))
    keep.sort(key=lambda t: (t[0], t[1]))
    nums = collections.defaultdict(set)
    for _, a, r, _o in keep:
        for i in U.isbns(r):
            nums[i].add(U.volume_number(r))
    boxset = {i for i, ns in nums.items() if len(ns) > 1}

    def sig(r):
        return (L.fold(U.series(r) or U.title(r), False), U.pubfam(U.publisher(r)))
    groups, head_sigs = collections.defaultdict(list), collections.defaultdict(set)
    for m in keep:
        h = U.head_number(m[2])
        if h is not None:
            groups[("h", "%08d" % h, "")].append(m)
            head_sigs[sig(m[2])].add(("h", "%08d" % h, ""))
    for m in keep:
        if U.head_number(m[2]) is None:
            hs = head_sigs.get(sig(m[2]), set())
            groups[next(iter(hs)) if len(hs) == 1 else ("s",) + sig(m[2])].append(m)
    lines, lost = [], []
    for g, members in sorted(groups.items()):
        members.sort(key=lambda t: (t[0], t[1]))
        vols, by_isbn = [], {}
        for n, a, r, _o in members:
            isb = [i for i in U.isbns(r) if i not in boxset]
            twin = next((by_isbn[i] for i in isb if i in by_isbn), None)
            if twin is not None:
                twin["members"].append("bnf:" + a)
                continue
            y = U.year(r)
            v = {"number": U.volume_number(r), "cands": [(i, "") for i in isb], "isbns": isb,
                 "isbn": isb[0] if isb else None, "pages": U.pages(r),
                 "date": (y, "year", "published") if y else None, "date_member": "bnf:" + a,
                 "members": ["bnf:" + a], "announced": False, "set_record": False}
            for i in isb:
                by_isbn[i] = v
            vols.append(v)
        one_shot = len(members) == 1 and not U.series(members[0][2])
        kept, l2 = _number_volumes(vols, one_shot)
        # the key: the lowest record number among the KEPT volumes' members (never a dropped record)
        pool = [m[4:] for v in kept for m in v["members"]] or [members[0][1]]
        key = "bnf:" + min(pool, key=lambda a: (U.ark_number(a), a))
        lost += [(m, f, key) for v, f in l2 for m in v["members"]]
        if not kept:
            continue
        rs = [r for _, _, r, _o in members]
        origin = _majority(o for _, _, _, o in members)
        pubs = collections.Counter(U.publisher(r) for r in rs if U.publisher(r))
        pub = pubs.most_common(1)[0][0] if pubs else None
        titles = [t for t in dict.fromkeys([U.series(rs[0]), U.title(rs[0])] + [U.series(r) for r in rs]) if t]
        ln = {"key": key, "source": "bnf", "market": "FR", "language": "fr",
              "name": U.series(rs[0]) or U.title(rs[0]), "publisher": pub, "pubfam": U.pubfam(pub),
              "edition": None, "medium": _medium(origin, False), "medium_why": None, "medium_guess": None,
              "origin": origin, "explicit": True, "comic": True, "vols": kept,
              "titles": [t for t in titles if not script_title(t)],
              "orig": list(dict.fromkeys(t for r in rs for t in U.original_titles(r) if not script_title(t))),
              "native": list(dict.fromkeys(t for r in rs for t in U.original_titles(r) + [U.title(r)]
                                           if script_title(t))),
              "authors": list(dict.fromkeys(a for r in rs for a in U.creators(r))),
              "members": [m for v in kept for m in v["members"]], "loc": []}
        if any(f == DUP for _, f in l2):
            _review(ln, "duplicate_numbers")
        lines.append(ln)
    return lines, lost, _stats(recs, len(keep), drop, lines, origin_inherited=inherited)


# ---- the Ize order (§7) -------------------------------------------------------------------------------------

def resolve_media(lines, isbn_medium):
    """A LoC line with no medium (and no review reason), in the §7 order:
      1. an existing OpenTome line holds one of its ISBNs -> that line's medium class;
      2. DNB / BnF KR/CN lines of this build with the same folded title, all of ONE comic medium
         (manhwa / manhua) -> that medium; a title match to a novel line (alone or beside a comic
         line: Ize prints both) resolves nothing;
      3. otherwise it stays None -- build_krcn sends it to review (reason 'ize-medium').
    Sets medium_via 'isbn' | 'title' on the lines it resolves.
    A line in review (medium None) is never a title source. A later LoC upgrade of the record
    classifies it on its own (a refresh, §7)."""
    by_title = collections.defaultdict(set)
    for ln in lines:
        if ln["source"] in ("dnb", "bnf") and ln["medium"]:
            for t in ln.get("titles", []) + [ln["name"]]:
                k = L.fold(t or "", False)
                if L.key_ok(k):
                    by_title[k].add(ln["medium"])
    for ln in lines:
        if ln["source"] != "loc" or ln["medium"] or ln["medium_why"]:
            continue
        have = {isbn_medium[i] for v in ln["vols"] for i in v["isbns"] if i in isbn_medium}
        if have:
            ln["medium"] = "novel" if have <= {"novel", "light_novel"} else _medium(ln["origin"], False)
            ln["medium_via"] = "isbn"
            continue
        got = by_title.get(L.fold(ln["name"] or "", False), set())
        if len(got) == 1 and next(iter(got)) in COMIC_MEDIA:
            ln["medium"], ln["medium_via"] = next(iter(got)), "title"
