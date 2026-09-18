"""ISBN helpers shared by every extractor.

The registration group of an ISBN identifies the market outright, which is the
one piece of structure every source agrees on. It replaces two things that were
wrong before:

  * `de_tables.GROUP_MARKET` keyed on the 4th digit only, so 979-11 (Korea)
    and 979-10 (France) were labelled English and 979-8 (US) was dropped. The
    live series Solo Leveling bound to a Korean-ISBN "English" line with no
    dates because of it.
  * `wikipedia_volumes` hard-coded the template's first slot as Japan. 233
    "JP" lines held no Japanese ISBN at all (Korean manhwa, French BD, US
    comics), and Mangarr would have shown their dates as Japanese.

Rules are the ISBN registration-group list; only the groups that occur in
this catalogue's sources are mapped, everything else returns None and is
counted rather than guessed.
"""
import re

# prefix (after 978/979) -> market. Longest prefix wins.
_GROUPS_978 = {
    "0": "EN", "1": "EN",
    "2": "FR",
    "3": "DE",
    "4": "JP",
    "7": "CN",
    "84": "ES",
    "85": "BR",
    "88": "IT",
    "89": "KR",
    "957": "TW", "986": "TW",
    "962": "HK", "988": "HK",
}
_GROUPS_979 = {
    "8": "EN",       # United States
    "10": "FR",
    "11": "KR",
    "12": "IT",
    "13": "ES",
}


def digits(s):
    return re.sub(r"[^0-9Xx]", "", s or "")


def isbn_market(isbn):
    """Market code from the registration group, or None when unknown."""
    d = digits(isbn)
    if len(d) != 13:
        return None
    table = _GROUPS_978 if d.startswith("978") else _GROUPS_979 if d.startswith("979") else None
    if table is None:
        return None
    rest = d[3:]
    for n in (3, 2, 1):
        if rest[:n] in table:
            return table[rest[:n]]
    return None


def isbn13_check(d):
    """True when the 13 digits carry a valid check digit."""
    if len(d) != 13 or not d.isdigit():
        return False
    s = sum((1 if i % 2 == 0 else 3) * int(c) for i, c in enumerate(d[:12]))
    return (10 - s % 10) % 10 == int(d[12])


def isbn10_to_13(s):
    d = digits(s)
    if len(d) != 10:
        return None
    core = "978" + d[:9]
    chk = (10 - sum((1 if i % 2 == 0 else 3) * int(c)
                    for i, c in enumerate(core)) % 10) % 10
    return core + str(chk)


def normalise_isbn(s):
    """-> (isbn13, isbn10). Either may be None.

    Rejects 13-digit codes that are not ISBNs: JAN/EAN barcodes (45…, 49…)
    were passing the old length-only check and being stored as ISBNs.
    """
    d = digits(s)
    if len(d) == 13:
        return (d, None) if d.startswith(("978", "979")) else (None, None)
    if len(d) == 10:
        return isbn10_to_13(d), d
    return None, None
