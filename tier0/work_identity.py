"""Cross-language work identity via Wikipedia langlinks.

THE problem this fixes: "Attack on Titan" and "L'Attaque des Titans" were
separate works with separate ids. 323 of 400 sampled duplicate-ISBN cases were
one volume filed under two language-specific work records.

That makes the catalogue three parallel language catalogues rather than one
multi-market catalogue, and it breaks the flagship query outright -- *"I own
French volume 5, what is that in English?"* cannot be answered if the two
editions belong to unrelated works.

Wikipedia langlinks state, authoritatively and for free, which articles across
languages describe the same subject. Articles are grouped into equivalence
classes by union-find; each class becomes one work, and every language's title
is recorded in `work_title` -- which also gives the localized-title index the
European market queries need.
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from wikipedia_volumes import _get

# Build outputs live in the repo, not /tmp. macOS cleaned /tmp and destroyed a
# fully-built 200 MB catalogue; only the cache (also in-repo) made recovery cheap.
BUILD = os.path.join(os.path.dirname(HERE), "build")
os.makedirs(BUILD, exist_ok=True)

LANGS = ("en", "fr", "de", "ja")


class Union:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            # deterministic: lexicographically smaller key wins, so the same
            # corpus always produces the same canonical member
            lo, hi = sorted((ra, rb))
            self.p[hi] = lo


def langlinks(lang, titles, batch=50, verbose=True):
    """{title: {lang: title}} for the requested languages."""
    out = {}
    for i in range(0, len(titles), batch):
        chunk = titles[i:i + batch]
        try:
            d = _get(lang, {"action": "query", "titles": "|".join(chunk),
                            "prop": "langlinks", "lllimit": "500"})
        except Exception:
            continue
        for p in d.get("query", {}).get("pages", []):
            got = {}
            for ll in p.get("langlinks", []) or []:
                if ll.get("lang") in LANGS:
                    got[ll["lang"]] = ll["title"]
            if got:
                out[p["title"]] = got
        if verbose and (i // batch) % 25 == 0 and i:
            print("    %s langlinks %d/%d" % (lang, i, len(titles)), flush=True)
    return out


def ensure_corpus(path):
    """Regenerate the article list if absent. Discovery is `embeddedin`, which is
    cached, so this costs no network on a rebuild."""
    if os.path.exists(path):
        return json.load(open(path))
    from build_corpus import corpus as discover
    out = {lang: discover(lang) for lang in ("en", "fr")}
    json.dump(out, open(path, "w"), ensure_ascii=False)
    return out


def _reduced(key):
    from build_corpus import work_title
    return work_title(key.partition(":")[2]).strip().lower()


def ja_article(key):
    """The Japanese article a class member IS, or None. A section link ("ja:〈物語〉シリーズ#漫画",
    the manga section of the Monogatari series article) says the subject is a part of that
    article, not the article, so it is no evidence about which work the article is: it returns
    None. (Counting it as its article split Bakemonogatari's manga from its French edition,
    whose own langlink names the novel's article 化物語 -- one work, two Japanese articles.)"""
    lang, _, art = key.partition(":")
    if lang != "ja" or "#" in art:
        return None
    return art.strip() or None


def disagree(ja_a, ja_b):
    """True when both classes hold a Japanese article and share none: Wikipedia's langlinks have
    already said the two are different subjects. Only Japanese is compared -- the manga's home
    wiki keeps one article per work, with adaptations as sections, so two plain articles are two
    works; in English, French and German, list articles, section links and franchise articles
    differ by title all the time (16 pairs on the 2026-11-24 corpus, 15 of them one work)."""
    return bool(ja_a) and bool(ja_b) and ja_a.isdisjoint(ja_b)


def classify(corpus, links_by_lang):
    """Union the corpus articles into works. corpus: {lang: [article]}; links_by_lang:
    {lang: {article: {lang2: title2}}} as langlinks() returns it. Returns
    {key: {"canonical": key, "titles": {lang: title}}} for every article key seen."""
    u = Union()
    titles_by_key = {}

    for lang in ("en", "fr"):
        arts = corpus.get(lang, [])
        lm = links_by_lang.get(lang, {})
        for art, links in lm.items():
            key = "%s:%s" % (lang, art)
            u.find(key)
            titles_by_key.setdefault(key, {})[lang] = art
            for l2, t2 in links.items():
                k2 = "%s:%s" % (l2, t2)
                u.union(key, k2)
                titles_by_key.setdefault(k2, {})[l2] = t2
        # articles with no langlinks are still their own work
        for a in arts:
            u.find("%s:%s" % (lang, a))
            titles_by_key.setdefault("%s:%s" % (lang, a), {})[lang] = a

    # Second union pass: two articles that reduce to the same work title are the
    # same work even when no langlink connects them. Without this, multi-part
    # list articles in ONE language split into separate works.
    # Union by title ACROSS languages, not within. An English list article
    # ("List of We Never Learn chapters") and the French main article
    # ("We Never Learn") describe the same work but are often not langlinked to
    # each other -- the EN list article links to the FR *list* article instead.
    # Keying by (lang, title) left those as separate works with identical names,
    # which is worse for a consumer than either merging or not merging at all.
    # Manga titles are distinctive enough that a cross-language exact match is
    # far more likely to be the same work than a coincidence, and the langlink
    # pass has already run, so genuine collisions are rare.
    #
    # Rare, not absent (2026-11-24): the English "Kurogane (manga)" is Kei Toume's
    # 1996 series, the French "Kurogane (manga)" is Haruto Ikezawa's 2011 one, and
    # the title pass filed Ikezawa's eight Shueisha volumes as the Japanese main
    # line of Toume's work. The langlink pass already knew better: the two classes
    # named different Japanese articles (黒鉄, クロガネ). So a title match is refused
    # when both classes already hold a Japanese article and share none (disagree());
    # a class with no Japanese article is joined as before -- the title match is
    # the only evidence there, and it still wins. Refused pairs are printed.
    by_title = {}
    ja = {}                            # class root -> {Japanese articles}
    for k in list(u.p):
        t = _reduced(k)
        # Guard was len>2, which excluded legitimately short titles: CLAMP's "X"
        # split into two works, and two-character Japanese titles (蟲師, 屍鬼)
        # were excluded from the union entirely. Verified safe: of 36 titles of
        # length 1-2 in the corpus, only "x" mapped to more than one work, so
        # lowering the bound merges exactly that case and nothing else.
        if t:
            by_title.setdefault(t, []).append(k)
        art = ja_article(k)
        if art:
            ja.setdefault(u.find(k), set()).add(art)
    merged = 0
    blocked = []
    for members in by_title.values():
        for m in members[1:]:
            ra, rb = u.find(members[0]), u.find(m)
            if ra == rb:
                continue
            if disagree(ja.get(ra), ja.get(rb)):
                blocked.append((members[0], m))
                continue
            u.union(members[0], m)
            root = u.find(m)
            gone = rb if root == ra else ra
            if gone in ja:
                ja.setdefault(root, set()).update(ja.pop(gone))
            merged += 1
    print("  title-union merged %d additional article keys, refused %d pairs that name "
          "different Japanese articles" % (merged, len(blocked)), flush=True)
    for a, b in blocked:
        print("    kept apart: %s | %s" % (a, b), flush=True)

    classes = {}
    for k in list(u.p):
        classes.setdefault(u.find(k), []).append(k)
    print("  %d article keys -> %d distinct works" % (len(u.p), len(classes)), flush=True)

    result = {}
    for canon, members in classes.items():
        titles = {}
        for m in members:
            for l, t in titles_by_key.get(m, {}).items():
                titles.setdefault(l, t)
        for m in members:
            result[m] = {"canonical": canon, "titles": titles}
    return result


def build(corpus_path=None, out_path=None):
    corpus_path = corpus_path or os.path.join(BUILD, "corpus.json")
    out_path = out_path or os.path.join(BUILD, "work_identity.json")
    corpus = ensure_corpus(corpus_path)
    links_by_lang = {}
    for lang in ("en", "fr"):
        arts = corpus.get(lang, [])
        print("  resolving %s (%d articles)…" % (lang, len(arts)), flush=True)
        links_by_lang[lang] = langlinks(lang, arts)
    result = classify(corpus, links_by_lang)
    json.dump(result, open(out_path, "w"), ensure_ascii=False)
    print("  wrote %s (%d keys)" % (out_path, len(result)), flush=True)
    return result


if __name__ == "__main__":
    build()
