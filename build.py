#!/usr/bin/env python3
"""Fetch Chechnya-related headlines from public RSS feeds and rebuild index.html.
Uses only the Python standard library. Add or remove feeds in FEEDS below."""
import html, json, random, re, sys, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

# (name, url, filter_by_keywords, language)
FEEDS = [
    ("Google News", "https://news.google.com/rss/search?q=Chechnya+OR+Kadyrov+when:7d&hl=en-US&gl=US&ceid=US:en", False, "en"),
    ("OC Media", "https://oc-media.org/feed/", True, "en"),
    ("The Moscow Times", "https://www.themoscowtimes.com/rss/news", True, "en"),
    ("Meduza", "https://meduza.io/rss/en/all", True, "en"),
    ("Google News", "https://news.google.com/rss/search?q=%D0%A7%D0%B5%D1%87%D0%BD%D1%8F+OR+%D0%9A%D0%B0%D0%B4%D1%8B%D1%80%D0%BE%D0%B2+when:7d&hl=ru&gl=RU&ceid=RU:ru", False, "ru"),
    ("Meduza", "https://meduza.io/rss/all", True, "ru"),
    ("Google News", "https://news.google.com/rss/search?q=Tschetschenien+OR+Kadyrow+when:7d&hl=de&gl=DE&ceid=DE:de", False, "de"),
]
KEYWORDS = re.compile(r"chechn|kadyrov|kadyrow|grozny|grosny|tschetschen|north caucasus|caucasian knot|чечн|кадыров|грозн", re.I)
EMPTY = {"en": "Headlines will appear after the next update.", "ru": "Заголовки появятся после следующего обновления.", "de": "Schlagzeilen erscheinen nach dem nächsten Update."}
MAX_AGE_DAYS = 14
MAX_ITEMS = 30

# Only used for the very first build (python build.py --seed) when feeds can't be reached
def _d(s): return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
SEED = [
    dict(title="Kadyrov calls Chechens who left for Europe ‘despicable traitors’", link="https://oc-media.org/kadyrov-calls-chechens-who-left-for-europe-despicable-traitors/", src="OC Media", lang="en", date=_d("2026-10-27"), snip=""),
    dict(title="Kadyrov confirms death in shootout after opposition movement claims unrest in Chechnya", link="https://oc-media.org/kadyrov-confirms-death-in-shootout-after-opposition-movement-claims-unrest-in-chechnya/", src="OC Media", lang="en", date=_d("2026-10-24"), snip=""),
    dict(title="The North Caucasus: new group of Chechen soldiers dispatched to Ukraine (30 Oct digest)", link="https://oc-media.org/friday-30-october-2026/", src="OC Media", lang="en", date=_d("2026-10-30"), snip=""),
    dict(title="Kadyrov starts fifth term as Chechen Head, promises to defend residents’ rights", link="https://oc-media.org/kadyrov-starts-fifth-term-as-chechen-head-promising-to-defend-residents-rights/", src="OC Media", lang="en", date=_d("2026-10-05"), snip=""),
]

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; news-page-bot)"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read()

def clean(text, n=220):
    t = re.sub(r"<[^>]+>", " ", html.unescape(text or ""))
    t = re.sub(r"\s+", " ", t).strip()
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + "…"

MEDIA = "{http://search.yahoo.com/mrss/}"
UA = {"User-Agent": "Mozilla/5.0 (compatible; CaucasusCourierBot/1.0; GitHub Pages news site)"}

def find_image(it, raw_desc):
    """Best-effort thumbnail URL from an RSS item."""
    for tag in ("content", "thumbnail"):
        for el in it.iter(MEDIA + tag):
            u = el.get("url", "")
            if u.startswith("https://") and (tag == "thumbnail" or (el.get("medium", "image") == "image" and el.get("type", "image").startswith("image"))):
                return u
    for el in it.iter("enclosure"):
        if (el.get("type") or "").startswith("image") and (el.get("url") or "").startswith("https://"):
            return el.get("url")
    blob = (raw_desc or "") + (it.findtext("{http://purl.org/rss/1.0/modules/content/}encoded") or "")
    m = re.search(r'<img[^>]+src=["\'](https://[^"\']+)["\']', blob)
    return m.group(1) if m else ""

def og_meta(url):
    """Publisher-provided preview image and short description from an article page."""
    try:
        page = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=12).read(250000).decode("utf-8", "ignore")
        def get(prop):
            m = (re.search(r'<meta[^>]+(?:property|name)=["\']%s["\'][^>]+content=["\']([^"\']+)' % prop, page)
                 or re.search(r'content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']%s["\']' % prop, page))
            return html.unescape(m.group(1)) if m else ""
        img = get("og:image")
        return (img if img.startswith("https://") else ""), clean(get("og:description"), 300)
    except Exception:
        return "", ""

COMMONS_QUERIES = ["Grozny", "Akhmat Kadyrov Mosque Grozny", "Grozny City", "Chechnya mountains", "Argun gorge Chechnya", "Chechen Republic landscape"]
OK_LICENSE = re.compile(r"^(CC BY|CC0|Public domain|PD)", re.I)
BAD_TITLE = re.compile(r"map|flag|coat|logo|portrait|poster|stamp|screenshot|diagram", re.I)

def commons_photos():
    """Freely licensed landscape photos from Wikimedia Commons, rotated by date."""
    pool, seen = [], set()
    for q in COMMONS_QUERIES:
        try:
            url = ("https://commons.wikimedia.org/w/api.php?action=query&format=json&generator=search"
                   "&gsrsearch=" + urllib.parse.quote(q + " filetype:bitmap") + "&gsrnamespace=6&gsrlimit=25"
                   "&prop=imageinfo&iiprop=url|size|extmetadata&iiurlwidth=1200")
            data = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25).read())
            for p in data.get("query", {}).get("pages", {}).values():
                ii = (p.get("imageinfo") or [{}])[0]
                meta = ii.get("extmetadata", {})
                lic = meta.get("LicenseShortName", {}).get("value", "")
                title = p.get("title", "")
                if not ii.get("thumburl") or title in seen or not OK_LICENSE.match(lic) or BAD_TITLE.search(title):
                    continue
                if ii.get("width", 0) < 1200 or ii.get("width", 0) < ii.get("height", 1) * 1.2:
                    continue
                seen.add(title)
                artist = clean(meta.get("Artist", {}).get("value", ""), 60) or "Wikimedia Commons"
                pool.append(dict(url=ii["thumburl"], page=ii.get("descriptionurl", "https://commons.wikimedia.org"),
                                 credit=f"{artist} · {lic}", alt=re.sub(r"^File:|\.\w+$", "", title).replace("_", " ")))
            print(f"Commons '{q}': pool {len(pool)}")
        except Exception as e:
            print(f"Commons '{q}': failed ({e})")
    random.Random(datetime.now(timezone.utc).strftime("%Y-%m-%d")).shuffle(pool)
    return pool

def parse(name, url, filt, lang="en"):
    out = []
    root = ET.fromstring(fetch(url))
    for it in root.iter("item"):
        title = clean(it.findtext("title"), 200)
        link = (it.findtext("link") or "").strip()
        raw_desc = it.findtext("description") or ""
        desc = clean(raw_desc)
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
        out.append(dict(title=title, link=link, src=src, date=d, snip=snip, lang=lang, img=find_image(it, raw_desc) if name != "Google News" else ""))
    return out

def collect():
    items = []
    for name, url, filt, lang in FEEDS:
        try:
            got = parse(name, url, filt, lang)
            print(f"{name} [{lang}]: {len(got)} items")
            items += got
        except Exception as e:
            print(f"{name} [{lang}]: failed ({e})")
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
    items = [i for i in items if i["date"] >= cutoff]
    items.sort(key=lambda i: i["date"], reverse=True)
    result = {"en": [], "ru": [], "de": []}
    seen = set()
    for i in items:
        k = i["lang"] + re.sub(r"\W+", "", i["title"].lower())[:60]
        if k not in seen and len(result[i["lang"]]) < MAX_ITEMS:
            seen.add(k)
            result[i["lang"]].append(i)
    budget = 16  # limit extra page fetches
    for lang in result:
        for i in result[lang][:10]:
            if (not i["img"] or not i["snip"]) and budget > 0 and "news.google.com" not in i["link"]:
                budget -= 1
                img, desc = og_meta(i["link"])
                i["img"] = i["img"] or img
                i["snip"] = i["snip"] or desc
    return result

def render(items, lang):
    e = html.escape
    if not items:
        return f'<div class="t {lang} none">{e(EMPTY[lang])}</div>'
    parts = []
    for i in items:
        img = i.get("img", "")
        thumb = (f'<img src="{e(img, quote=True)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">' if img.startswith("https://") else "")
        init = e(i["src"][:1].upper())
        snip = f"<p>{e(i['snip'])}</p>" if i["snip"] else ""
        parts.append(
            f'<a class="hl" href="{e(i["link"], quote=True)}" target="_blank" rel="noopener" data-img="{e(img, quote=True)}" data-title="{e(i["title"], quote=True)}" data-src="{e(i["src"], quote=True)}" data-date="{i["date"]:%d.%m.%Y}" data-snip="{e(i["snip"], quote=True)}">'
            f'<div class="thumb">{thumb or init}</div><div class="hb">'
            f'<span class="meta">{e(i["src"])} · {i["date"]:%d.%m.%Y}</span><strong>{e(i["title"])}</strong>{snip}</div></a>'
        )
    return f'<div class="hls t {lang}">' + "\n".join(parts) + "</div>"

def fig(photo):
    e = html.escape
    return (f'<figure class="ph"><img src="{e(photo["url"], quote=True)}" alt="{e(photo["alt"], quote=True)}" loading="lazy" '
            f'referrerpolicy="no-referrer" onerror="this.parentNode.remove()">'
            f'<figcaption><a href="{e(photo["page"], quote=True)}" target="_blank" rel="noopener">{e(photo["credit"])}</a></figcaption></figure>')

def main():
    result = collect()
    if not any(result.values()) and "--seed" in sys.argv:
        result["en"] = SEED
    if not any(result.values()):
        print("No headlines found; leaving index.html unchanged.")
        return
    tpl = open("template.html", encoding="utf-8").read()
    today = datetime.now(timezone.utc).strftime("%d.%m.%Y")
    page = tpl.replace("{{UPDATED}}", today)
    photos = commons_photos()
    hero = photos.pop(0) if photos else None
    if hero:
        page = page.replace("{{HERO_STYLE}}", 'style="--img:url(\'%s\')"' % hero["url"].replace("'", "%27"))
        page = page.replace("{{HERO_CREDIT}}", '<a class="cr" href="%s" target="_blank" rel="noopener">%s</a>' % (html.escape(hero["page"], quote=True), html.escape(hero["credit"])))
    page = page.replace("{{HERO_STYLE}}", "").replace("{{HERO_CREDIT}}", "")
    for slot in ("lead", "s1", "s2", "s3", "s4", "s5"):
        page = page.replace("{{IMG:%s}}" % slot, fig(photos.pop(0)) if photos else "")
    for lang in ("en", "ru", "de"):
        page = page.replace("{{LATEST_%s}}" % lang.upper(), render(result[lang], lang))
    open("index.html", "w", encoding="utf-8").write(page)
    print("Wrote index.html:", {k: len(v) for k, v in result.items()})

if __name__ == "__main__":
    main()
