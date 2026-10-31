#!/usr/bin/env python3
"""Fetch Chechnya-related headlines from public RSS feeds and rebuild index.html.
Uses only the Python standard library. Add or remove feeds in FEEDS below."""
import html, re, sys, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

# (name, url, filter_by_keywords)
FEEDS = [
    ("Google News", "https://news.google.com/rss/search?q=Chechnya+OR+Kadyrov+when:7d&hl=en-US&gl=US&ceid=US:en", False),
    ("OC Media", "https://oc-media.org/feed/", True),
    ("The Moscow Times", "https://www.themoscowtimes.com/rss/news", True),
    ("Meduza", "https://meduza.io/rss/en/all", True),
]
KEYWORDS = re.compile(r"chechn|kadyrov|grozny|north caucasus|caucasian knot", re.I)
MAX_AGE_DAYS = 14
MAX_ITEMS = 30

# Only used for the very first build (python build.py --seed) when feeds can't be reached
def _d(s): return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
SEED = [
    dict(title="Kadyrov calls Chechens who left for Europe ‘despicable traitors’", link="https://oc-media.org/kadyrov-calls-chechens-who-left-for-europe-despicable-traitors/", src="OC Media", date=_d("2026-10-27"), snip=""),
    dict(title="Kadyrov confirms death in shootout after opposition movement claims unrest in Chechnya", link="https://oc-media.org/kadyrov-confirms-death-in-shootout-after-opposition-movement-claims-unrest-in-chechnya/", src="OC Media", date=_d("2026-10-24"), snip=""),
    dict(title="The North Caucasus: new group of Chechen soldiers dispatched to Ukraine (30 Oct digest)", link="https://oc-media.org/friday-30-october-2026/", src="OC Media", date=_d("2026-10-30"), snip=""),
    dict(title="Kadyrov starts fifth term as Chechen Head, promises to defend residents’ rights", link="https://oc-media.org/kadyrov-starts-fifth-term-as-chechen-head-promising-to-defend-residents-rights/", src="OC Media", date=_d("2026-10-05"), snip=""),
]

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; news-page-bot)"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read()

def clean(text, n=220):
    t = re.sub(r"<[^>]+>", " ", html.unescape(text or ""))
    t = re.sub(r"\s+", " ", t).strip()
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + "…"

def parse(name, url, filt):
    out = []
    root = ET.fromstring(fetch(url))
    for it in root.iter("item"):
        title = clean(it.findtext("title"), 200)
        link = (it.findtext("link") or "").strip()
        desc = clean(it.findtext("description"))
        if not title or not link.startswith(("http://", "https://")):
            continue
        if filt and not KEYWORDS.search(title + " " + desc):
            continue
        try:
            d = parsedate_to_datetime(it.findtext("pubDate"))
        except Exception:
            d = datetime.now(timezone.utc)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        src, snip = name, desc
        if name == "Google News":
            s = it.find("source")
            if s is not None and s.text:
                src = s.text.strip()
            if title.endswith(" - " + src):
                title = title[: -len(src) - 3]
            snip = ""  # Google's description is just a link list
        out.append(dict(title=title, link=link, src=src, date=d, snip=snip))
    return out

def collect():
    items = []
    for name, url, filt in FEEDS:
        try:
            got = parse(name, url, filt)
            print(f"{name}: {len(got)} items")
            items += got
        except Exception as e:
            print(f"{name}: failed ({e})")
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
    items = [i for i in items if i["date"] >= cutoff]
    items.sort(key=lambda i: i["date"], reverse=True)
    seen, unique = set(), []
    for i in items:
        k = re.sub(r"\W+", "", i["title"].lower())[:60]
        if k not in seen:
            seen.add(k)
            unique.append(i)
    return unique[:MAX_ITEMS]

def render(items):
    e = html.escape
    parts = []
    for i in items:
        snip = f"<p>{e(i['snip'])}</p>" if i["snip"] else ""
        parts.append(
            f'<div class="hl"><a href="{e(i["link"], quote=True)}" target="_blank" rel="noopener">{e(i["title"])}</a>'
            f'<div class="meta">{e(i["src"])} · {i["date"]:%d %b %Y}</div>{snip}</div>'
        )
    return "\n".join(parts)

def main():
    items = collect()
    if not items and "--seed" in sys.argv:
        items = SEED
    if not items:
        print("No headlines found; leaving index.html unchanged.")
        return
    tpl = open("template.html", encoding="utf-8").read()
    today = datetime.now(timezone.utc).strftime("%d %b %Y").upper()
    page = tpl.replace("{{LATEST}}", render(items)).replace("{{UPDATED}}", today)
    open("index.html", "w", encoding="utf-8").write(page)
    print(f"Wrote index.html with {len(items)} headlines.")

if __name__ == "__main__":
    main()
