"""Load tier-0 extraction into the v1 schema, with per-field provenance.

IDs are derived from a STABLE NATURAL KEY via hash, so re-runs are
idempotent -- but they are stored opaquely and never parsed. If a natural
key ever changes, the old id must be written to id_redirect, never dropped.
"""
import hashlib, json, os, re, sqlite3, sys, datetime

import os


def _build(name):
    """Default build-output path. Never /tmp: macOS cleaned it and destroyed a
    fully-built catalogue. Outputs belong beside the cache, inside the repo."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    d = os.path.join(root, "build")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, name)


NOW = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

# licence per source -- drives the clean_claim view (commercial subset)
# VERIFIED against each source's published terms 2026-08-27. Earlier values were
# assumptions I had labelled "open" without checking, which made the
# "100% commercially clean" figure circular -- it was clean because I said so.
LICENCE = {
    # Etalab Open Licence since 2014: commercial reuse permitted, attribution
    # required. The only source verified clean for a paid product.
    "bnf":         "open",
    # CC0 -- public domain, no conditions at all.
    "dnb":         "cc0",
    # US government work (17 USC §105): public domain in the US -- Nick's decision (2026-09-27), not a
    # stated LoC licence; ONLY records LoC created (040 $a DLC). Records LoC copied from other libraries
    # are never read (docs/krcn-design.md §2, R4). Outside the US the EU database-right caveat applies.
    "loc":         "us_gov_pd",
    # Facts are not copyrightable (Feist). Defensible in the US. The EU sui
    # generis database right is a genuine open question and Europe is the
    # target market -- needs counsel before any commercial launch.
    "wikipedia":   "facts_only",
    # These are Wikipedia-derived values whose <ref> cites a publisher page. We
    # never fetched the publisher. Attribution points there; provenance is
    # Wikipedia. Labelling them "open" overstated it.
    "publisher":   "facts_only",
    # PURPOSE-LIMITED: rights are granted for "book promotion and introduction",
    # and data must not be altered. A paid metadata API is not obviously book
    # promotion. Fine for a free catalogue; NOT clear for a commercial one.
    "openbd":      "noncommercial",
    # Internet Archive terms: access "for scholarship and research purposes
    # only", use must be certified "noncommercial". Open Library also states
    # its API is not intended as a bulk backend -- use the monthly dumps.
    "openlibrary": "noncommercial",
    # Our own derived flags (isbn_collision etc.).
    "opentome":    "open",
    # corrections/*.json: a value a person read off the cited publisher page or
    # library record. Same footing as "publisher": a fact, attributed.
    "correction":  "facts_only",
    # The cover image Wikipedia's own infobox shows for the work -- a NON-FREE file
    # under fair use there. We store the file name as a pointer for a private
    # browser to link to; 'restricted' keeps it out of every export and clean view.
    "wikipedia_image": "restricted",
    # ToS forbids database-building and/or commercial use. Not used.
    "gbooks":      "restricted",
    "mangadex":    "restricted",
    "rakuten":     "restricted",
}


MARKET_LANG = {"JP": "ja", "EN": "en", "FR": "fr", "DE": "de", "KR": "ko",
               "IT": "it", "ES": "es", "BR": "pt-BR", "CN": "zh", "TW": "zh-TW",
               "HK": "zh-HK"}


def _id(prefix, *parts):
    key = "|".join(str(p).strip().lower() for p in parts)
    return prefix + hashlib.sha256(key.encode()).hexdigest()[:12]


ISBN_IN_URL = re.compile(r"(?<![0-9])(97[89](?:[- ]?[0-9]){10})(?![0-9])")


def url_isbn(url):
    """The ISBN-13 a cited publisher page carries in its own address (kodansha ?isbn=, shueisha ?isbn=978-4-…,
    yenpress /9781975…, hachette …/9780316346153/), normalised to 13 digits; None when the address carries
    none or the check digit fails. The corrections round (2026-11-23): a row's cell can carry a neighbour's
    ISBN (the English Prison School list repeats one Japanese ISBN on rows 26-28; its row 4 carries row 2's
    English one) while the row's own citation names the right page -- that address is the publisher's statement."""
    if not url:
        return None
    m = ISBN_IN_URL.search(url)
    if not m:
        return None
    digits = re.sub(r"[- ]", "", m.group(1))
    if len(digits) != 13 or not digits.isdigit():
        return None
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(digits[:12]))
    return digits if (10 - total % 10) % 10 == int(digits[12]) else None


def _src_name(url):
    if not url:
        return "wikipedia"
    u = url.lower()
    for host, name in (("shueisha", "publisher"), ("viz.com", "publisher"),
                       ("kodansha", "publisher"), ("yenpress", "publisher"),
                       ("hachettebookgroup", "publisher"),    # Yen Press's parent: the EN lists cite it
                       ("tokyopop", "publisher"),
                       ("pika.fr", "publisher"), ("glenat", "publisher")):
        if host in u:
            return name
    return "wikipedia"


def load(db, series_title, records, medium="manga", work_key=None, titles=None):
    """records may carry `medium` and `line` from tier0.release_lines.split()."""
    c = db.cursor()
    # work_key is the cross-language canonical key from tier0.work_identity.
    # Without it, "Attack on Titan" and "L'Attaque des Titans" become separate
    # works and the catalogue silently degrades into parallel language silos.
    wid = _id("w_", work_key or series_title)
    c.execute("INSERT OR IGNORE INTO work(id,primary_title,created_at,updated_at)"
              " VALUES(?,?,?,?)", (wid, series_title, NOW, NOW))
    for lang, t in (titles or {}).items():
        c.execute("""INSERT OR IGNORE INTO work_title(work_id,language,title,kind)
                     VALUES(?,?,?,'official')""", (wid, lang, t))

    lines, nvol, nclaim = {}, 0, 0
    written = set()     # (volume, field, source) this call wrote: an article's FIRST row for a number is its claim
    for r in records:
        via = r.get("wiki") or ""      # the article's wiki: one claim per article (schema.sql, claim.via)
        # the original slot's market (JP by convention, ISBN-corrected) is
        # what a licensed omnibus volume's composition refers back to
        orig_market = (r.get("markets", {}).get("original") or {}).get("market", "JP")
        for role, m in r.get("markets", {}).items():
            market = m.get("market")
            if not market:
                continue
            # a franchise article carries many lines; the splitter tells us which
            med  = r.get("medium", medium)
            line = r.get("line", series_title)
            rlid = _id("rl_", wid, med, market, line)
            if rlid not in lines:
                parent = _id("rl_", wid, med, market, r["arc_of"]) if r.get("arc_of") else None
                c.execute("INSERT OR IGNORE INTO release_line"
                          "(id,work_id,parent_id,medium,market,language,created_at,updated_at)"
                          " VALUES(?,?,?,?,?,?,?,?)",
                          (rlid, wid, parent, med, market, MARKET_LANG.get(market, "und"),
                           NOW, NOW))
                # one line_name claim per line, the last article's (its article is the source_url): the name
                # the export writes stays what it was before claim.via (the French list named 'xxxHOLiC',
                # the English article 'xxxHolic'; a per-article claim here renamed 4 carried lines)
                c.execute("INSERT OR REPLACE INTO claim"
                          "(entity,entity_id,field,value,source,source_url,licence,retrieved_at,via)"
                          " VALUES('release_line',?,'line_name',?,'wikipedia',?,?,?,'')",
                          (rlid, line, r.get("article"), LICENCE["wikipedia"], NOW))
                lines[rlid] = (med, market, line)

            role_title = (r.get("title_licensed") if role == "licensed" else r.get("title_original")) or r.get("title")
            # a collapsed omnibus line numbers its own units (collapse.py)
            number = m.get("number", r["volume"])
            vid = _id("v_", rlid, number)
            # composition: this licensed volume CONTAINS these original-market
            # volumes (2-in-1 editions, 'Tomes 17-18' doubles). ref_line_id
            # points at the original line so a consumer can map across markets.
            contains = m.get("contains") or (
                r.get("contains_volumes") if role == "licensed" else None)
            c.execute("""INSERT OR IGNORE INTO volume
                (id,release_line_id,number,title,isbn13,release_date,
                 release_date_precision,release_date_type,format,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (vid, rlid, number, role_title, m.get("isbn13"), m.get("date"),
                 m.get("date_precision"), "unknown",
                 "omnibus" if contains and len(contains) > 1 else None, NOW, NOW))
            nvol += 1
            if contains:
                c.execute("""INSERT OR IGNORE INTO composition
                    (volume_id,contains,ref_list,ref_line_id) VALUES(?,'volume',?,?)""",
                    (vid, json.dumps(contains), _id("rl_", wid, med, orig_market, line)))

            src = _src_name(m.get("date_source"))
            claims = [("release_date", m.get("date"), src)]
            page_isbn = url_isbn(m.get("date_source")) if src == "publisher" else None
            if page_isbn and page_isbn != m.get("isbn13"):
                # the cited publisher page names the ISBN; the cell's value stays Wikipedia's own claim
                claims += [("isbn13", page_isbn, "publisher"), ("isbn13", m.get("isbn13"), "wikipedia")]
            else:
                claims.append(("isbn13", m.get("isbn13"), src))
            for field, val, csrc in claims:
                if not val:
                    continue
                # one article, two rows for one number (a collected-edition table repeats it): the first row is
                # the article's claim, as the row's value was before claim.via; the last row's reissue date
                # pushed 19 English volumes out of order. A later load of the same article still replaces.
                if (vid, field, csrc) in written:
                    continue
                written.add((vid, field, csrc))
                c.execute("""INSERT OR REPLACE INTO claim
                    (entity,entity_id,field,value,source,source_url,licence,retrieved_at,via)
                    VALUES('volume',?,?,?,?,?,?,?,?)""",
                    (vid, field, val, csrc, m.get("date_source") if csrc != "wikipedia" or src == "wikipedia" else None,
                     LICENCE[csrc], NOW, via))
                nclaim += 1

            # composition: this volume contains these chapters (the unifying primitive)
            if r.get("chapters"):
                c.execute("""INSERT OR IGNORE INTO composition
                    (volume_id,contains,ref_list) VALUES(?,'chapter',?)""",
                    (vid, json.dumps(r["chapters"])))
    db.commit()
    return wid, len(lines), nvol, nclaim


if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "tier0"))
    from wikipedia_volumes import wikitext, parse_volumes

    out = sys.argv[1] if len(sys.argv) > 1 else _build("opentome.db")
    if os.path.exists(out):
        os.remove(out)
    db = sqlite3.connect(out)
    db.executescript(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "schema.sql")).read())

    import release_lines as RL
    for lang, page, title in [
            ("en", "List of Chainsaw Man chapters", "Chainsaw Man"),
            ("fr", "Liste des chapitres de L'Attaque des Titans", "Attack on Titan"),
            ("en", "List of Re:Zero volumes", "Re:Zero"),
            ("en", "List of Sword Art Online manga volumes", "Sword Art Online")]:
        w = wikitext(page, lang)
        recs = RL.split(w, page, title, parse_volumes(w, page, lang))
        wid, nl, nv, nc = load(db, title, recs)
        print(f"  {title:<16} ({lang}) -> {nl} release lines, {nv} volumes, {nc} claims")
    print(f"\nwrote {out}")
