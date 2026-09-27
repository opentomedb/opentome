"""Replay gates for the KR/CN round -- docs/krcn-design.md §13, "The fold() change must not move
the German JP round". Offline: DNB_OFFLINE=1, zero requests. Nothing here writes to
build/opentome.db or the carry: snapshots run stage 3e on a COPY under build/krcn-replay/.

    python3 tier0/krcn_replay.py fold-gate [catalogue]
        dnb_link.fold() vs the frozen pre-round fold over every catalogue title string and every
        DNB record string that feeds a key; any string WITHOUT Hangul that folds differently fails.
    python3 tier0/krcn_replay.py jp-snapshot OUT.json [catalogue] [carry]
        stage 3e (build_dnb.run) with DNB_OFFLINE=1 on a copy of the catalogue ->
        {dnb_line.key: [tier, role, exported, rl_id, link_work]}. Note: build_dnb.run writes
        build/dnb-report.json and build/dnb-review.tsv (build outputs; the next build rewrites them).
    python3 tier0/krcn_replay.py jp-diff BASE.json NEW.json
        exit 1 unless 0 keys added / removed and 0 tiers / roles / exported flags / rl_ids /
        link_works changed (every snapshot field; each change names the field).

catalogue defaults to build/opentome.db, carry to build/alias-fix/carry.sqlite (opentome-2026-09-25).
"""
import json, os, re, shutil, sqlite3, subprocess, sys, unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
CAT = os.path.join(ROOT, "build", "opentome.db")
CARRY = os.path.join(ROOT, "build", "alias-fix", "carry.sqlite")
WORK = os.path.join(ROOT, "build", "krcn-replay")
# syllables, conjoining jamo (incl. extended A/B), compatibility jamo
HANGUL = re.compile("[ᄀ-ᇿ㄰-㆏ꥠ-꥿가-힣ힰ-퟿]")
FIELDS = ("tier", "role", "exported", "rl_id", "link_work")     # the whole snapshot tuple is gated


def has_hangul(s):
    return bool(HANGUL.search(s or ""))


def fold_v1(s, strip_vol=True):
    """tier0/dnb_link.fold as of ebe4368 (before the KR/CN round), frozen verbatim. The reference
    the byte-identical gate compares against -- never edit."""
    s = (s or "").replace("\x98", "").replace("\x9c", "")
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("×", "x").replace("&", " and ")
    s = "".join(c for c in unicodedata.normalize("NFD", s) if not unicodedata.combining(c))
    s = s.lower().strip()
    s = re.sub(r"^the\s+", "", s)
    if strip_vol:
        s = re.sub(r"\b(vol(ume)?|band|bd|tome|nr)\.?\s*\d+.*$", "", s)
        s = re.sub(r"[\s,.:;\-–]*\d{1,3}\.?\s*$", "", s)
    s = re.sub(r"\bwo\b", "o", s)
    s = s.replace("ou", "o").replace("oo", "o").replace("uu", "u")
    s = re.sub(r"\(.*?\)", " ", s)
    return re.sub("[^0-9a-z぀-ヿ一-鿿]+", "", s)


def diff_snapshots(base, new):
    changed = []
    for k in sorted(set(base) & set(new)):
        for i, f in enumerate(FIELDS):
            if base[k][i] != new[k][i]:
                changed.append((k, f, base[k][i], new[k][i]))
    return {"added": sorted(set(new) - set(base)), "removed": sorted(set(base) - set(new)), "changed": changed}


def _catalogue_strings(cat):
    db = sqlite3.connect("file:%s?mode=ro" % cat, uri=True)
    out = set()
    for q in ("SELECT primary_title FROM work", "SELECT title FROM work_title",
              "SELECT value FROM claim WHERE entity='work' AND field IN ('ja_romaji','ja_kanji')",
              "SELECT value FROM claim WHERE entity='release_line' AND field IN ('line_name','publisher')",
              "SELECT DISTINCT publisher FROM release_line WHERE publisher IS NOT NULL"):
        out |= {r[0] for r in db.execute(q) if r[0]}
    return out


def _record_strings(recs):
    import dnb_marc as M
    out = set()
    for r in recs:
        for tag in ("240", "245", "246", "260", "264", "490", "830"):
            for s in M.fields(r, tag):
                out |= {v for c, v in s if c in ("a", "b", "n", "p", "t") and v}
        out.add(M.bare_title(r))
        out |= set(M.original_titles(r))
        out |= {s for s, _ in M.series_statements(r)}
    return {s for s in out if s}


def fold_gate(cat=CAT):
    os.environ["DNB_OFFLINE"] = "1"
    import dnb_enumerate as E, dnb_sru as S, dnb_marc as M, dnb_link as L
    recs, parents, _ = E.enumerate_all(verbose=False)
    strings = {"catalogue": _catalogue_strings(cat),
               "dnb (JP channels + parents)": _record_strings(list(recs.values()) + list(parents.values()))}
    extra = []
    for q in ("spo=kor and bbg=A*", "spo=chi and bbg=A*"):      # the source research's cached sets, if present
        have = S._cached_set(q)
        if have:
            extra += [r for t in have[1] for r in M.records(t)]
    if extra:
        strings["dnb (spike kor/chi sets)"] = _record_strings(extra)
    bad, hangul = [], 0
    for src, ss in strings.items():
        n_changed = 0
        for s in sorted(ss):
            new, old = (L.fold(s), L.fold(s, False)), (fold_v1(s), fold_v1(s, False))
            if new == old:
                continue
            if has_hangul(s):
                hangul += 1
                n_changed += 1
                continue
            bad.append((src, s, old, new))
        print("  %-30s %7d strings, %d fold differently (Hangul)" % (src, len(ss), n_changed))
    print("  Hangul strings that now fold differently (expected): %d" % hangul)
    if bad:
        for src, s, old, new in bad[:20]:
            print("  FAIL non-Hangul string changed [%s] %r: %r -> %r" % (src, s, old, new))
        raise SystemExit("fold-gate FAILED: %d non-Hangul strings fold differently" % len(bad))
    print("fold-gate ok: every string without Hangul folds byte-identically")


def jp_snapshot(out, cat=CAT, carry=CARRY):
    os.makedirs(WORK, exist_ok=True)
    tmp = os.path.join(WORK, "catalogue.db")
    shutil.copyfile(cat, tmp)
    env = dict(os.environ, DNB_OFFLINE="1")
    subprocess.run([sys.executable, os.path.join(HERE, "build_dnb.py"), tmp, carry], env=env, check=True)
    db = sqlite3.connect(tmp)
    snap = {k: [t, r, e, rid, lw] for k, t, r, e, rid, lw in
            db.execute("SELECT key, tier, role, exported, rl_id, link_work FROM dnb_line")}
    with open(out, "w", encoding="utf8") as f:
        json.dump(snap, f, sort_keys=True, indent=0)
    print("  snapshot: %d dnb_line rows -> %s" % (len(snap), out))


def jp_diff(a, b):
    base, new = (json.load(open(p, encoding="utf8")) for p in (a, b))
    d = diff_snapshots(base, new)
    print("  keys added %d, removed %d; tier/role/exported/rl_id/link_work changes %d" % (
        len(d["added"]), len(d["removed"]), len(d["changed"])))
    for row in d["changed"][:40]:
        print("    %s %s: %r -> %r" % row)
    for k in (d["added"] + d["removed"])[:20]:
        print("    key %s %s" % ("added" if k in d["added"] else "removed", k))
    if d["added"] or d["removed"] or d["changed"]:
        raise SystemExit("jp-diff FAILED")
    print("jp-diff ok: 0 changed keys, tiers, roles, exported flags, rl_ids, link_works")


def _ol_v1(db, market, batch=50):
    """enrich_openlibrary as of ebe4368, frozen (the sorted-batch loop) -- the gate's reference."""
    sys.path.insert(0, os.path.join(ROOT, "tier1"))
    import enrich_more as EM
    from verify import _fetch
    rows = db.execute("""SELECT v.id, v.isbn13 FROM volume v JOIN release_line rl ON rl.id=v.release_line_id
        WHERE rl.market=? AND v.isbn13 IS NOT NULL AND NOT EXISTS (SELECT 1 FROM claim c WHERE
        c.entity='volume' AND c.entity_id=v.id AND c.source='openlibrary')""", (market,)).fetchall()
    by = {}
    for vid, isbn in rows:
        by.setdefault(isbn, []).append(vid)
    isbns = sorted(by)
    for i in range(0, len(isbns), batch):
        chunk = isbns[i:i + batch]
        d = _fetch(EM.ol_url(chunk), interval=0.6)
        if not isinstance(d, dict) or "_error" in d or "_http_error" in d:
            continue
        for key, rec in d.items():
            isbn = key.split(":", 1)[1]
            iso, _ = EM.parse_ol_date(rec.get("publish_date"), market)
            for vid in by.get(isbn, []):
                if iso:
                    EM._claim(db, vid, "release_date", iso, "openlibrary", f"https://openlibrary.org/isbn/{isbn}")
                if rec.get("number_of_pages"):
                    EM._claim(db, vid, "page_count", str(rec["number_of_pages"]), "openlibrary",
                              f"https://openlibrary.org/isbn/{isbn}")
    db.commit()


def ol_gate(cat=CAT):
    """Offline, network BLOCKED: the old and new Open Library code on two copies of the catalogue
    (openlibrary claims removed first). Every old claim must be reproduced with the same value;
    the new code may add claims (records found in other cached batches) -- reported. Writes the
    per-ISBN entries it derives into .cache/ (derived from cached responses; zero requests)."""
    import urllib.request
    sys.path.insert(0, os.path.join(ROOT, "tier1"))
    import enrich_more as EM

    def blocked(*a, **k):
        raise OSError("ol-gate: network blocked")
    urllib.request.urlopen = blocked
    os.makedirs(WORK, exist_ok=True)
    got = {}
    for tag in ("v1", "v2"):
        p = os.path.join(WORK, "ol-%s.db" % tag)
        shutil.copyfile(cat, p)
        db = sqlite3.connect(p)
        db.execute("DELETE FROM claim WHERE source='openlibrary'")
        for m in ("EN", "FR"):
            (_ol_v1 if tag == "v1" else lambda d, mk: EM.enrich_openlibrary(d, market=mk))(db, m)
        got[tag] = {(e, f): v for e, f, v in db.execute(
            "SELECT entity_id, field, value FROM claim WHERE source='openlibrary'")}
    lost = [k for k in got["v1"] if k not in got["v2"]]
    diff = [k for k in got["v1"] if k in got["v2"] and got["v1"][k] != got["v2"][k]]
    extra = len(set(got["v2"]) - set(got["v1"]))
    print("  old claims %d, new claims %d: lost %d, changed %d, added %d" % (
        len(got["v1"]), len(got["v2"]), len(lost), len(diff), extra))
    if lost or diff:
        raise SystemExit("ol-gate FAILED: %s" % (lost + diff)[:10])
    print("ol-gate ok: every old Open Library claim reproduced")


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        raise SystemExit(__doc__)
    if a[0] == "fold-gate":
        fold_gate(*a[1:2])
    elif a[0] == "jp-snapshot":
        jp_snapshot(*a[1:4])
    elif a[0] == "jp-diff":
        jp_diff(a[1], a[2])
    elif a[0] == "ol-gate":
        ol_gate(*a[1:2])
    else:
        raise SystemExit(__doc__)
