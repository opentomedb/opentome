"""Build the German slice.

Discovery is the interesting part. de.wikipedia has no volume-list template to
enumerate, `Vorlage:DatumZelle` is used site-wide (ISO 4217, Albany NY), and
`Kategorie:Manga` holds 95 meta-articles. So German articles are found via
**langlinks from the English corpus** -- which guarantees they are the same
works AND establishes cross-language work identity as a side effect.

Probe: 60% of English articles have a German equivalent.
"""
import json, os, re, sqlite3, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "schema"))

from wikipedia_volumes import _get, wikitext
from de_tables import extract
from build_corpus import work_title, load_identity
from load import load

import os


def _build(name):
    """Default build-output path. Never /tmp: macOS cleaned it and destroyed a
    fully-built catalogue. Outputs belong beside the cache, inside the repo."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    d = os.path.join(root, "build")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, name)



def de_equivalents(en_titles, batch=50):
    """EN article -> DE article, via langlinks."""
    out = {}
    for i in range(0, len(en_titles), batch):
        chunk = en_titles[i:i + batch]
        try:
            d = _get("en", {"action": "query", "titles": "|".join(chunk),
                            "prop": "langlinks", "lllang": "de", "lllimit": "500"})
        except Exception:
            continue
        for p in d.get("query", {}).get("pages", []):
            for ll in p.get("langlinks", []) or []:
                out[p["title"]] = ll["title"]
        if (i // batch) % 20 == 0 and i:
            print("    langlinks %d/%d -> %d found" % (i, len(en_titles), len(out)), flush=True)
    return out


def to_load_shape(recs):
    """de_tables keys markets by code; load() wants a `market` field inside."""
    out = []
    for r in recs:
        m2 = {}
        for mkt, m in r.get("markets", {}).items():
            e = dict(m)
            e["market"] = mkt
            m2[mkt] = e
        out.append({**r, "markets": m2, "medium": "manga"})
    return out


def main(dbpath, limit=None):
    db = sqlite3.connect(dbpath, timeout=60)
    done = {r[0] for r in db.execute("SELECT key FROM meta WHERE key LIKE 'done:de:%'")}
    # MUST use the same identity map as the en/fr pass. Loading without a
    # work_key falls back to hashing the title, which never collides with a
    # canonical-key hash -- so every German-sourced work silently became a TWIN
    # of the work that already existed. That was the entire cause of the 88
    # duplicate work titles the audit flagged.
    identity = load_identity()
    en = json.load(open(_build("corpus.json")))["en"]
    print("resolving German equivalents for %d EN articles…" % len(en), flush=True)
    mapping = de_equivalents(en)
    print("German articles found: %d" % len(mapping), flush=True)

    todo = [(e, d) for e, d in mapping.items() if ("done:de:" + d) not in done]
    if limit:
        todo = todo[:limit]
    print("to process: %d (%d already done)" % (len(todo), len(mapping) - len(todo)), flush=True)

    ok = err = vols = 0
    t0 = time.time()
    for i, (en_title, de_title) in enumerate(todo, 1):
        try:
            w = wikitext(de_title, "de")
            if not w:
                raise ValueError("no wikitext")
            recs = extract(w, de_title)
            if recs:
                ident = identity.get("en:" + en_title, {})
                titles = ident.get("titles") or {}
                title = work_title(titles.get("en") or en_title)
                _, nl, nv, _ = load(db, title, to_load_shape(recs),
                                    work_key=ident.get("canonical"), titles=titles)
                vols += nv
            db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)",
                       ("done:de:" + de_title, str(len(recs))))
            db.commit()
            ok += 1
        except Exception as e:
            err += 1
            db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)",
                       ("err:de:" + de_title, ("%s: %s" % (type(e).__name__, e))[:200]))
            db.commit()
        if i % 100 == 0:
            el = time.time() - t0
            print("  %d/%d ok=%d err=%d vols=%d %.1f/s eta=%.0fm"
                  % (i, len(todo), ok, err, vols, i/el, (len(todo)-i)/(i/el)/60), flush=True)
    print("DONE ok=%d err=%d volumes=%d elapsed=%.1fm"
          % (ok, err, vols, (time.time()-t0)/60), flush=True)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else _build("opentome.db"),
         int(sys.argv[2]) if len(sys.argv) > 2 else None)
