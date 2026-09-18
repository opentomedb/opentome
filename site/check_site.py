#!/usr/bin/env python3
"""Check a generated site: every internal href/src resolves to a file, every page
has a title. Exits 1 on the first kind of failure.

    python3 site/check_site.py _site
"""
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.title, self._in_title = [], "", False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("a", "link") and a.get("href"):
            self.links.append(a["href"])
        elif tag in ("script", "img") and a.get("src"):
            self.links.append(a["src"])
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data


def main(root):
    root = Path(root)
    site = root.resolve()
    pages = sorted(root.rglob("*.html"))
    if not pages:
        sys.exit(f"no pages under {root}")
    broken, untitled, checked = [], [], 0
    for page in pages:
        p = Links()
        p.feed(page.read_text(encoding="utf-8"))
        if not p.title.startswith("OpenTomeDB"):
            untitled.append(f"{page.relative_to(root)}: title {p.title!r}")
        for href in p.links:
            parts = urlsplit(href)
            if parts.scheme or href.startswith("#") or href.startswith("//"):
                continue                       # external, anchor, or protocol-relative
            target = (page.parent / unquote(parts.path)).resolve() if parts.path else page
            if target.is_dir() or parts.path.endswith("/"):
                target = target / "index.html"
            checked += 1
            if not target.is_file() or not target.is_relative_to(site):
                broken.append(f"{page.relative_to(root)} -> {href}")
    print(f"{len(pages)} pages, {checked} internal links checked, {len(broken)} broken, {len(untitled)} untitled")
    for line in broken + untitled:
        print("  " + line)
    sys.exit(1 if broken or untitled else 0)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "_site")
