"""Unit tests for tier0/work_identity.py's union passes. Run: python3 tier0/test_work_identity.py

No network: the langlink maps are given to classify() directly, in the shape langlinks() returns
({article: {lang: title}} per corpus language).
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import work_identity as W

FAILS = []


def eq(label, got, want):
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else f"  got={got!r} want={want!r}"))
    if not ok:
        FAILS.append(label)


def canon(result, key):
    return result[key]["canonical"]


# 1. The Kurogane shape (2026-11-24, TypNull's AniList thread): the English "Kurogane (manga)" is
#    Kei Toume's 1996 Kodansha series, the French "Kurogane (manga)" is Haruto Ikezawa's 2011
#    Shueisha series. Their langlinks already name two different Japanese articles (黒鉄, クロガネ),
#    so the cross-language title union must not join them.
corpus = {"en": ["Kurogane (manga)"], "fr": ["Kuro Gane", "Kurogane (manga)"]}
links = {"en": {"Kurogane (manga)": {"fr": "Kuro Gane", "ja": "黒鉄"}},
         "fr": {"Kurogane (manga)": {"ja": "クロガネ"}}}
r = W.classify(corpus, links)
eq("Toume's English article and French edition are one work",
   canon(r, "en:Kurogane (manga)"), canon(r, "fr:Kuro Gane"))
eq("Ikezawa's French article stays its own work",
   canon(r, "fr:Kurogane (manga)") != canon(r, "en:Kurogane (manga)"), True)
eq("Ikezawa's Japanese article follows its French one",
   canon(r, "ja:クロガネ"), canon(r, "fr:Kurogane (manga)"))
eq("Toume's work keeps its Japanese title", r["en:Kurogane (manga)"]["titles"].get("ja"), "黒鉄")
eq("Ikezawa's work carries its own Japanese title", r["fr:Kurogane (manga)"]["titles"].get("ja"), "クロガネ")

# 2. The case the title pass exists for: an English list article links to the French list
#    article only, the French main article links to the English main article; no shared Japanese
#    article disagrees, so the title pass joins the two classes.
corpus = {"en": ["List of We Never Learn chapters", "We Never Learn"], "fr": ["We Never Learn"]}
links = {"en": {"List of We Never Learn chapters": {"fr": "Liste des chapitres de We Never Learn"},
                "We Never Learn": {"ja": "ぼくたちは勉強ができない"}},
         "fr": {"We Never Learn": {"en": "We Never Learn", "ja": "ぼくたちは勉強ができない"}}}
r = W.classify(corpus, links)
eq("list article and main article are one work",
   canon(r, "en:List of We Never Learn chapters"), canon(r, "fr:We Never Learn"))

# 3. Same title, no langlinks at all on one side: still joined (no evidence against it).
corpus = {"en": ["Blue Giant"], "fr": ["Blue Giant"]}
links = {"en": {"Blue Giant": {"ja": "BLUE GIANT"}}, "fr": {}}
r = W.classify(corpus, links)
eq("a title match with no contrary langlink joins", canon(r, "en:Blue Giant"), canon(r, "fr:Blue Giant"))

# 4. The disagreement that counts is between Japanese articles. A different German or French
#    article on each side is not evidence of two works: list articles, section links and
#    franchise articles differ by title all the time (16 pairs on the 2026-11-24 corpus, 15 of
#    them one work), so the pair is joined as before.
corpus = {"en": ["Doubt (manga)"], "fr": ["Doubt (manga)"]}
links = {"en": {"Doubt (manga)": {"de": "Doubt (Tonogai)"}}, "fr": {"Doubt (manga)": {"de": "Doubt (Izumi)"}}}
r = W.classify(corpus, links)
eq("a disagreement in a language other than Japanese does not keep the works apart",
   canon(r, "en:Doubt (manga)"), canon(r, "fr:Doubt (manga)"))

# 5. A section link into a Japanese article is not that article: the English manga article
#    links to the manga section of the Monogatari series article, the French edition links to
#    the novel's own article 化物語. Two Japanese articles, one work (the real corpus, 2026-11-24).
corpus = {"en": ["Bakemonogatari (manga)"], "fr": ["Bakemonogatari"]}
links = {"en": {"Bakemonogatari (manga)": {"ja": "〈物語〉シリーズ#漫画"}}, "fr": {"Bakemonogatari": {"ja": "化物語"}}}
r = W.classify(corpus, links)
eq("a Japanese section link is no evidence against the title match",
   canon(r, "en:Bakemonogatari (manga)"), canon(r, "fr:Bakemonogatari"))

# 6. One side has no Japanese article at all: the title match stands (the English list article
#    reaches the German main article by title; only the German side knows the Japanese one).
corpus = {"en": ["List of Radiant volumes"], "fr": ["Radiant (bande dessinée)"]}
links = {"en": {}, "fr": {"Radiant (bande dessinée)": {"ja": "ラディアン", "de": "Radiant (Comic)"}}}
r = W.classify(corpus, links)
eq("no Japanese article on one side: joined", canon(r, "en:List of Radiant volumes"), canon(r, "de:Radiant (Comic)"))

if FAILS:
    print("FAILED:", FAILS)
    sys.exit(1)
print("all work identity checks passed")
