"""Stage 3d -- work relations, from facts the catalogue already holds.

`work_relation` was empty: no source states "X is a spin-off of Y" as a field.
Two things do state it, indirectly and reliably:

  * **Title prefix.** "Attack on Titan: Before the Fall" is a spin-off of
    "Attack on Titan"; "Dragon Ball Z" is a sequel of "Dragon Ball". Another
    work's title is a proper prefix, and what follows is a separator or a
    sequel word. The longest such parent wins ("Dragon Ball Super" -> "Dragon
    Ball", not "Dragon"). Short parents (< 5 letters) never match.
  * **Shared main article.** Two works whose list articles point at the same
    main article are one franchise: a light novel and its manga adaptation.
    'adaptation' when the media differ, 'alternative' when they do not; the
    other works point at the one named exactly like the article, else the
    one with the shortest title.

Both write `work_relation(from, to, kind)`; ids never change, so relations
survive rebuilds like everything else.
"""
import os
import re
import sqlite3
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from main_titles import main_article  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEQUEL = re.compile(r"^\s*[:\-–—]?\s*(?:part|season|book|arc|chapter|z\b|super\b|gt\b|kai\b|ii\b|iii\b|iv\b|\d+\b|ex\b|next\b|zero\b|r\b|2nd|3rd|second|third)", re.I)
SEP = re.compile(r"^\s*[:\-–—(]")


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").lower()
    return re.sub(r"[^a-z0-9]", "", s)


def parent_of(title, by_norm):
    """-> (parent_title, kind) or (None, None). by_norm: {norm(title): title}."""
    nt = norm(title)
    best = None
    for L in range(5, len(nt)):
        pt = by_norm.get(nt[:L])
        if not pt or norm(pt) == nt:
            continue
        if not title.lower().startswith(pt.lower()):
            continue                      # punctuation differs: not the same words
        rest = title[len(pt):]
        if SEQUEL.match(rest):
            kind = "sequel"
        elif SEP.match(rest):
            kind = "spin_off"
        else:
            continue
        best = (pt, kind)                 # longer prefixes come later: last wins
    return best or (None, None)


def run(dbpath, verbose=True):
    db = sqlite3.connect(dbpath, timeout=60)
    c = db.cursor()
    works = c.execute("SELECT id, primary_title FROM work").fetchall()
    by_norm, by_title = {}, {}
    for wid, t in works:
        by_norm.setdefault(norm(t), t)
        by_title.setdefault(t, wid)
    media = {}
    for wid, m in c.execute("SELECT DISTINCT work_id, medium FROM release_line"):
        media.setdefault(wid, set()).add(m)

    rows, samples = [], []
    for wid, t in works:
        pt, kind = parent_of(t, by_norm)
        if pt and by_title.get(pt) and by_title[pt] != wid:
            rows.append((wid, by_title[pt], kind))
            if len(samples) < 6:
                samples.append("%s -> %s (%s)" % (t, pt, kind))

    # shared main article (cached leads only)
    groups = {}
    for wid, art, prim in c.execute("""SELECT t.work_id, t.title, w.primary_title FROM work_title t
                                       JOIN work w ON w.id=t.work_id
                                       WHERE t.language='en' AND t.kind='official'"""):
        target, _ = main_article(art, work_title=prim)
        if target:
            groups.setdefault(target, []).append((wid, prim))
    n_shared = 0
    for target, members in groups.items():
        if len(members) < 2:
            continue
        primary = next((w for w, p in members if norm(p) == norm(target)), None)
        if primary is None:
            primary = min(members, key=lambda wp: len(wp[1]))[0]
        for wid, prim in members:
            if wid == primary:
                continue
            kind = "adaptation" if media.get(wid, set()) != media.get(primary, set()) else "alternative"
            rows.append((wid, primary, kind))
            n_shared += 1

    c.executemany("INSERT OR IGNORE INTO work_relation(from_work_id,to_work_id,kind) VALUES(?,?,?)", rows)
    db.commit()
    total = c.execute("SELECT COUNT(*) FROM work_relation").fetchone()[0]
    if verbose:
        print("  relations: %d by title prefix, %d by shared main article, %d rows in work_relation"
              % (len(rows) - n_shared, n_shared, total))
        for s_ in samples:
            print("    " + s_)
    return total


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "build", "opentome.db"))
