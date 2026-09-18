"""Per-volume cover URLs, keyed by the edition's ISBN. Cache only -- zero requests.

The rule that makes a cover right: it is looked up by the ISBN of the exact
edition, never by a title search. A title search returns *a* cover for *some*
edition of *something* with that name, which is how a volume ends up wearing
another volume's face. Both sources below are queried by ISBN and both were
already fetched for date/page enrichment, so every URL here comes from the
disk cache.

  Open Library `api/books?bibkeys=ISBN:…&jscmd=data`  -> rec.cover.large   (EN, FR)
  openBD      `v1/get?isbn=…`                          -> summary.cover       (JP)

Only a URL and its source are stored -- never the image. Mangarr fetches at
display time into its own cache; nothing is hosted. A record without a cover
yields no claim, so there is no placeholder image to filter: Open Library only
includes `cover` when one exists, and openBD leaves `cover` empty otherwise.
"""
import datetime, glob, json, os, re, sqlite3, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "schema"))
from load import LICENCE

CACHE = os.path.join(ROOT, ".cache")
NOW = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def covers_from_cache(verbose=True):
    """-> {isbn13: (url, source)} from every cached Open Library / openBD response."""
    out, files = {}, 0
    for f in glob.glob(os.path.join(CACHE, "*.json")):
        try:
            with open(f, encoding="utf8") as fh:
                d = json.load(fh)
        except Exception:
            continue
        files += 1
        if isinstance(d, dict) and d and all(k.startswith("ISBN:") for k in list(d)[:3]):
            for key, rec in d.items():
                isbn = key.split(":", 1)[1]
                cover = (rec.get("cover") or {})
                url = cover.get("large") or cover.get("medium")
                if url and isbn not in out:
                    out[isbn] = (url, "openlibrary")
        elif isinstance(d, list) and d and isinstance(d[0], dict) and "summary" in d[0]:
            for rec in d:
                if not rec:
                    continue
                s = rec.get("summary") or {}
                isbn, url = s.get("isbn"), s.get("cover")
                if isbn and url and isbn not in out:
                    out[isbn] = (url, "openbd")
    if verbose:
        by = {}
        for _, src in out.values():
            by[src] = by.get(src, 0) + 1
        print("  cache files %s -> cover URLs for %s ISBNs (%s)" % (
            format(files, ","), format(len(out), ","),
            ", ".join("%s %s" % (k, format(v, ",")) for k, v in sorted(by.items()))))
    return out


def run(dbpath, verbose=True):
    db = sqlite3.connect(dbpath, timeout=60)
    covers = covers_from_cache(verbose)
    rows = db.execute("SELECT id, isbn13 FROM volume WHERE isbn13 IS NOT NULL").fetchall()
    ins = 0
    for vid, isbn in rows:
        hit = covers.get(isbn)
        if not hit:
            continue
        url, src = hit
        db.execute("""INSERT OR REPLACE INTO claim
            (entity,entity_id,field,value,source,source_url,licence,retrieved_at)
            VALUES('volume',?,'cover_url',?,?,?,?,?)""",
            (vid, url, src, url, LICENCE[src], NOW))
        ins += 1
    db.commit()
    if verbose:
        print("  volumes with an ISBN %s -> cover_url claims %s (%.1f%%)"
              % (format(len(rows), ","), format(ins, ","), 100.0 * ins / max(1, len(rows))))
    return ins


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "build", "opentome.db"))
