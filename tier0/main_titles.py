"""Official English titles and alternative names, from each work's MAIN article.

The corpus is discovered through `embeddedin` on the volume-list template, so
every English article it holds is a LIST article -- "List of Frieren chapters",
"List of Mushoku Tensei volumes". `work_title()` strips that to "Frieren" and
"Mushoku Tensei", and those become the work's English name.

Nobody's library folder is called that. Measured against the live library, a
build with no hand-curated aliases missed exactly the series whose official
English title carries a subtitle:

    folder "Frieren: Beyond Journey's End"        vs  work "Frieren"
    folder "Mushoku Tensei: Jobless Reincarnation" vs  work "Mushoku Tensei"

Two sources fix it, both about the work's MAIN article:

  1. The list article's own lead names the main article as its first italic
     wikilink, and a PIPED link carries the official title as its display text:
     ``''[[Frieren|Frieren: Beyond Journey's End]]''``. Free -- the wikitext is
     already cached.
  2. The main article's REDIRECTS are the names readers actually type. One
     batched API call per 50 works returns them:
     Frieren -> "Frieren: Beyond Journey's End", "Sousou no Frieren", 葬送のフリーレン
     Mushoku Tensei -> "Mushoku Tensei: Jobless Reincarnation"
     Re:Zero -> "Re:ZERO -Starting Life in Another World-"

Both are stored as `work_title` rows with kind='alias', which the exporter
already turns into series aliases for the work's main line per market. They are
titles -- facts about naming, the same class of data as the rest of the
catalogue -- never prose.

Run AFTER the corpus build (it reads `work_title`), BEFORE the export.
"""
import json, os, re, sqlite3, sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from wikipedia_volumes import _get, wikitext

NOW_KIND = "alias"

# The lead's first italic wikilink: ''[[Target]]'' or ''[[Target|Display]]''
LEAD_LINK = re.compile(r"''+\s*\[\[([^\]|#]+?)\s*(?:\|\s*([^\]]+?)\s*)?\]\]\s*''+"   # ''[[X|Y]]''
                       r"|\[\[([^\]|#]+?)\s*\|\s*(''+[^\]]+?)\s*\]\]")              # [[X|''Y'' and ''Z'']]

# Wikipedia namespaces that are not article titles.
NAMESPACE = re.compile(
    r"^(User|User talk|Talk|Wikipedia|Wikipedia talk|Template|Template talk|Category|"
    r"Category talk|Portal|Draft|File|Help|Module|MediaWiki|Special)\s*:", re.I)

# Redirects that are not another name for the WORK.
NOT_A_TITLE = re.compile(r"^(List of |Timeline of )", re.I)


def _norm(s):
    s = unicodedata.normalize("NFKD", s or "").lower()
    return re.sub(r"[^a-z0-9]", "", s)


def lead_link(w, work_title=None):
    """(target, display) of the lead's first italic wikilink that names the work.

    The first italic link in a list article's lead is usually the work -- but
    for 34 of 4,638 works it was the magazine ("Weekly Shōnen Jump"), the
    generic "tankōbon" article or a franchise page, and that page's redirects
    then became the work's aliases (One Piece acquired 45 names for Shōnen
    Jump). Given the work's title, every italic link in the lead is tried in
    order and the first whose target or display shares the title wins; if none
    does, the work has no main article rather than a wrong one.
    """
    wt = _norm(work_title) if work_title else None
    for m in LEAD_LINK.finditer(w[:4000]):
        target = (m.group(1) or m.group(3)).strip()
        display = re.sub(r"''+", "", m.group(2) or m.group(4) or target).strip()
        if NAMESPACE.match(target) or target.startswith("File:"):
            continue
        if wt is None:
            return target, display
        for cand in (target, display):
            n = _norm(cand)
            # the work's title must be IN the candidate, never the reverse: a
            # spin-off's lead links its parent first (Dragon Ball Z -> Dragon
            # Ball, five Kaiji sequels -> Kaiji) and the parent must not win
            if n and wt in n:
                return target, display
    return None, None


def main_article(article, lang="en", work_title=None):
    """-> (target, display) for the work's main article, or (None, None).

    Reads only the cache; an uncached article is skipped rather than fetched,
    so this stage never turns into a second full crawl.
    """
    if not article.lower().startswith(("list of ", "liste des ")):
        return article, article
    try:
        w = wikitext(article, lang)
    except Exception:
        return None, None
    if not w:
        return None, None
    return lead_link(w, work_title)


def redirects(titles, batch=50, verbose=True):
    """{main article: [redirect titles]} -- one API call per `batch` titles."""
    out = {}
    titles = sorted(set(titles))
    for i in range(0, len(titles), batch):
        chunk = titles[i:i + batch]
        try:
            d = _get("en", {"action": "query", "titles": "|".join(chunk),
                            "prop": "redirects", "rdlimit": "500", "rdnamespace": "0"})
        except Exception:
            continue
        for p in d.get("query", {}).get("pages", []):
            rs = [r["title"] for r in p.get("redirects", []) or []]
            if rs:
                out[p["title"]] = rs
        # `normalized` maps the title we asked for to the title the API used
        for n in d.get("query", {}).get("normalized", []) or []:
            if n["to"] in out:
                out.setdefault(n["from"], out[n["to"]])
        if verbose and (i // batch) % 20 == 0 and i:
            print("    redirects %d/%d" % (i, len(titles)), flush=True)
    return out


def acceptable(title):
    return bool(title) and not NAMESPACE.match(title) and not NOT_A_TITLE.match(title)


def run(dbpath, verbose=True):
    db = sqlite3.connect(dbpath, timeout=60)
    works = db.execute("""SELECT t.work_id, t.title, w.primary_title FROM work_title t
                          JOIN work w ON w.id=t.work_id
                          WHERE t.language='en' AND t.kind='official'""").fetchall()
    if verbose:
        print("  %d works with an English article" % len(works), flush=True)

    by_main, display_of = {}, {}
    for wid, art, prim in works:
        target, display = main_article(art, work_title=prim)
        if not target:
            continue
        by_main.setdefault(target, []).append(wid)
        if display and display != target:
            display_of.setdefault(wid, set()).add(display)

    if verbose:
        print("  %d main articles resolved from cached leads" % len(by_main), flush=True)
    red = redirects(list(by_main), verbose=verbose)

    rows, n_display, n_redirect = [], 0, 0
    for wid, ds in display_of.items():
        for d in ds:
            if acceptable(d):
                rows.append((wid, "en", d, NOW_KIND))
                n_display += 1
    for target, wids in by_main.items():
        names = [target] + red.get(target, [])
        # a redirect shared by two works is ambiguous by construction
        if len(wids) > 1:
            continue
        for name in names:
            if acceptable(name):
                rows.append((wids[0], "en", name, NOW_KIND))
                n_redirect += 1

    before = db.execute("SELECT COUNT(*) FROM work_title").fetchone()[0]
    db.executemany("INSERT OR IGNORE INTO work_title(work_id,language,title,kind)"
                   " VALUES(?,?,?,?)", rows)
    db.commit()
    after = db.execute("SELECT COUNT(*) FROM work_title").fetchone()[0]
    if verbose:
        print("  display titles %s | redirect titles %s | work_title rows %s -> %s (+%s)"
              % (format(n_display, ","), format(n_redirect, ","),
                 format(before, ","), format(after, ","), format(after - before, ",")))
    return after - before


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "build", "opentome.db"))
