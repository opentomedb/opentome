"""Build the catalogue at scale from every Wikipedia article we can parse.

Discovery is exact, not guessed: `list=embeddedin` returns every article that
uses the volume-list template, i.e. precisely the parseable set.

Resumable by construction -- responses are disk-cached and completed articles
are recorded in `meta`, so re-running skips finished work and costs no network.
"""
import json, os, re, sqlite3, sys, time, datetime, traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "schema"))

from wikipedia_volumes import _get, wikitext, parse_volumes, DIALECTS
import release_lines as RL
from collapse import collapse_licensed
from load import load

TPL = {"en": "Template:Graphic novel list", "fr": "Modèle:TomeBD"}

# "List of X chapters" / "Liste des chapitres de X" -> X
# Ordered: first match wins. Trailing parentheticals ("(Part I)", "(1-186)")
# are stripped first so the main patterns see a clean tail.
STRIP = [
    (r"^List of (.+?) (?:manga |anime |)(?:chapters|volumes|books|media|"
     r"light novels|novels|episodes|manga|comics)$", 1),
    (r"^List of (.+?) comics issued by .+$", 1),
    (r"^Liste des (?:chapitres|volumes|tomes|publications dérivées|"
     r"light novels|publications|romans) d[eu\'’]\s*(.+)$", 1),
    (r"^Liste des (?:chapitres|volumes|tomes|mangas|publications dérivées|"
     r"light novels|publications|romans) de (?:la |l\'|l’)?(.+)$", 1),
    (r"^Liste des (?:chapitres|volumes|tomes|mangas) (.+)$", 1),
]

# Trailing parentheticals that qualify a SPLIT of one work, never a different
# work: "(Part I)", "(1-186)", "(101-current)", "(series)".
TRAILING_PAREN = re.compile(
    r"\s*\((?:Part\s+[IVX]+(?:,\s*volumes?\s*[\d\u2013-]+)?|"
    r"[\d]+\s*[\u2013-]\s*(?:[\d]+|current)|"
    r"volumes?\s*[\d\u2013-]+(?:current)?|chapters?\s*[\d\u2013-]+(?:current)?|"
    r"series)\)\s*$", re.I)


def work_title(article):
    article = TRAILING_PAREN.sub("", article).strip()
    for pat, g in STRIP:
        m = re.match(pat, article, re.I)
        if m:
            return TRAILING_PAREN.sub("", m.group(g)).strip()
    return re.sub(r"\s*\((?:manga|manhwa|light novel|novel|film|anime|série|comics?)\)$",
                  "", article, flags=re.I).strip()


def corpus(lang):
    titles, cont = [], None
    while True:
        p = {"action": "query", "list": "embeddedin", "eititle": TPL[lang],
             "eilimit": "500", "einamespace": "0"}
        if cont:
            p["eicontinue"] = cont
        d = _get(lang, p)
        titles += [x["title"] for x in d.get("query", {}).get("embeddedin", [])]
        cont = d.get("continue", {}).get("eicontinue")
        if not cont:
            return titles


def done_set(db):
    return {r[0] for r in db.execute(
        "SELECT key FROM meta WHERE key LIKE 'done:%'")}


def load_identity(path=None):
    path = path or os.path.join(ROOT, "build", "work_identity.json")
    try:
        return json.load(open(path))
    except Exception:
        print("  WARNING: no work identity map -- works will NOT be merged "
              "across languages", flush=True)
        return {}


def main(dbpath, limit=None, langs=("en", "fr")):
    fresh = not os.path.exists(dbpath)
    db = sqlite3.connect(dbpath)
    if fresh:
        db.executescript(open(os.path.join(ROOT, "schema", "schema.sql")).read())
    done = done_set(db)
    identity = load_identity()

    todo = []
    for lang in langs:
        for a in corpus(lang):
            if f"done:{lang}:{a}" not in done:
                todo.append((lang, a))
    if limit:
        todo = todo[:limit]
    print(f"corpus: {len(todo)} articles to process ({len(done)} already done)", flush=True)

    ok = err = vols = 0
    t0 = time.time()
    for i, (lang, article) in enumerate(todo, 1):
        try:
            w = wikitext(article, lang)
            if not w:
                raise ValueError("no wikitext")
            title = work_title(article)
            ident = identity.get("%s:%s" % (lang, article), {})
            key = ident.get("canonical")
            titles = ident.get("titles") or {}
            # prefer the English title as primary when the class has one
            if titles.get("en"):
                title = work_title(titles["en"])
            recs = RL.split(w, article, title, parse_volumes(w, article, lang))
            recs = collapse_licensed(recs)
            if recs:
                _, nl, nv, _ = load(db, title, recs, work_key=key, titles=titles)
                vols += nv
            db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)",
                       (f"done:{lang}:{article}", str(len(recs))))
            db.commit()
            ok += 1
        except Exception as e:
            err += 1
            db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)",
                       (f"err:{lang}:{article}", f"{type(e).__name__}: {e}"[:200]))
            db.commit()
        if i % 100 == 0:
            el = time.time() - t0
            rate = i / el if el else 0
            eta = (len(todo) - i) / rate / 60 if rate else 0
            print(f"  {i}/{len(todo)}  ok={ok} err={err} vols={vols} "
                  f"{rate:.1f}/s eta={eta:.0f}m", flush=True)
    print(f"DONE  ok={ok} err={err} volumes={vols} elapsed={(time.time()-t0)/60:.1f}m",
          flush=True)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "build", "opentome.db"),
         int(sys.argv[2]) if len(sys.argv) > 2 else None)
