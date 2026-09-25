"""Carry curated aliases forward from an existing artifact.

Measured against the live library, the hand-curated artifact matched 37/41
series and OpenTome only 31/41 -- despite OpenTome holding ~5x the data. The
entire gap is naming: TARGET_SERIES and BRIDGE_ALIASES were written for this
library's exact folder names, including misspellings ("Jujustu Kaisen").

Curation is real work and should not be thrown away just because the data
underneath it was replaced. This maps each old series onto its OpenTome
counterpart -- by shared ISBN first, since an ISBN is unambiguous, falling back
to title -- and copies the aliases across.

Guards added after review (docs/cleanup-v2.md): the join used to take the
FIRST matching ISBN and the FIRST rowid on a title tie, which attached
"Shonen Note" to Shangri-La Frontier and sent 64% of title joins to a
Japanese line. Now: majority vote over every old ISBN, same-language target
only (re-routed to the sibling line of the same work when the ISBN lands on
another market), and a join whose names share no token is refused and printed.
"""
import os, sqlite3, sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from to_mangarr import normalize, variants


def _tokens(s):
    """Significant name tokens; short-token names ('Yu-Gi-Oh!', 'No. 6',
    'B.O.D.Y.') fall back to every token so they are not refused as unrelated."""
    toks = normalize(s).split()
    long = {t for t in toks if len(t) > 2}
    return long or set(toks)


def merge(new_path, old_path, verbose=True):
    new = sqlite3.connect(new_path)
    old = sqlite3.connect(old_path)

    cols = [r[1] for r in new.execute("PRAGMA table_info(series)")]
    has_work = "tome_work_id" in cols

    lang = dict(new.execute("SELECT gcd_series_id, language FROM series"))
    name_of = dict(new.execute("SELECT gcd_series_id, name FROM series"))
    work_of = dict(new.execute("SELECT gcd_series_id, tome_work_id FROM series")) if has_work else {}
    medium_of = dict(new.execute("SELECT gcd_series_id, medium FROM series")) if "medium" in cols else {}
    vc_of = dict(new.execute("SELECT gcd_series_id, volume_count FROM series"))

    # ISBN -> every new series carrying it (an ISBN is unambiguous only when
    # exactly one series holds it; 6,377 ISBNs sit in more than one)
    isbn_map = {}
    for isbn, sid in new.execute("SELECT isbn13, gcd_series_id FROM volumes WHERE isbn13 IS NOT NULL"):
        isbn_map.setdefault(isbn, set()).add(sid)

    # normalized title/alias -> new series ids
    title_map = {}
    for sid, name in new.execute("SELECT gcd_series_id, name FROM series"):
        title_map.setdefault(normalize(name), set()).add(sid)
    for sid, alias in new.execute("SELECT gcd_series_id, alias FROM series_alias"):
        title_map.setdefault(normalize(alias), set()).add(sid)

    def sibling_same_language(sid, want_lang):
        """The same work's line in the wanted language (prefer same medium, most volumes)."""
        if not has_work or not work_of.get(sid):
            return None
        sibs = [s for s, w in work_of.items() if w == work_of[sid] and lang.get(s) == want_lang]
        if not sibs:
            return None
        sibs.sort(key=lambda s: (medium_of.get(s) != medium_of.get(sid), -vc_of.get(s, 0), s))
        return sibs[0]

    by_isbn = by_title = unmatched = rerouted = refused = added = 0
    for old_sid, old_name, old_lang in old.execute(
            "SELECT gcd_series_id, name, COALESCE(language,'en') FROM series"):
        votes = Counter()
        for (isbn,) in old.execute(
                "SELECT isbn13 FROM volumes WHERE gcd_series_id=? AND isbn13 IS NOT NULL", (old_sid,)):
            for sid in isbn_map.get(isbn, ()):
                votes[sid] += 1
        target, how = None, None
        if votes:
            best, n = votes.most_common(1)[0]
            tied = [s for s, c in votes.items() if c == n]
            if len(tied) == 1:
                target, how = best, "isbn"
        if target is None:
            cands = title_map.get(normalize(old_name), set())
            same = [s for s in cands if lang.get(s) == old_lang]
            if len(same) == 1:
                target, how = same[0], "title"
            elif same:
                target, how = sorted(same, key=lambda s: (-vc_of.get(s, 0), s))[0], "title"
        if target is None:
            unmatched += 1
            continue
        if lang.get(target) != old_lang:
            sib = sibling_same_language(target, old_lang)
            if sib is None:
                refused += 1
                if verbose:
                    print(f"    refused (language {lang.get(target)}): {old_name!r} -> {name_of[target]!r}")
                continue
            target, rerouted = sib, rerouted + 1
        if not (_tokens(old_name) & _tokens(name_of[target])) and how == "isbn":
            # an ISBN filed under two unrelated titles upstream -- do not bridge it
            refused += 1
            if verbose:
                print(f"    refused (no shared token): {old_name!r} -> {name_of[target]!r}")
            continue
        by_isbn += how == "isbn"
        by_title += how == "title"

        aliases = [old_name] + [r[0] for r in old.execute(
            "SELECT alias FROM series_alias WHERE gcd_series_id=?", (old_sid,))]
        for a in aliases:
            for v in variants(a):
                # Preferred Edition (2026-09-24): series_alias grew language/kind columns.
                # A carried-forward alias has no known work_title provenance -- closest of
                # the fixed kinds is 'correction' (hand-curated, outside the automated
                # derivation), same as corrections/aliases.json's language=NULL rows.
                cur = new.execute("""INSERT OR IGNORE INTO series_alias (gcd_series_id, alias, language, kind)
                                     VALUES(?,?,NULL,'correction')""", (target, v))
                added += cur.rowcount
    # Stamp the artifact: an artifact carrying aliases merged from a GCD-derived
    # source is not clean-room and must never be published. export/publish.sh
    # refuses on this key -- a rule that checks itself beats a rule in a doc.
    if added:
        new.execute("INSERT OR REPLACE INTO meta VALUES('alias_provenance',?)",
                    ("opentome+" + os.path.basename(old_path),))
    new.commit()
    if verbose:
        print("  old series matched by ISBN  : %s" % format(by_isbn, ","))
        print("  ...by title                 : %s" % format(by_title, ","))
        print("  rerouted to same-language   : %s" % format(rerouted, ","))
        print("  refused                     : %s" % format(refused, ","))
        print("  unmatched (dropped)         : %s" % format(unmatched, ","))
        print("  aliases carried forward     : %s" % format(added, ","))
    return added


if __name__ == "__main__":
    merge(sys.argv[1], sys.argv[2])
