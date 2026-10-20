"""Fetching, parsing, deduping and full-text extraction."""

import calendar
import html
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

import feedparser
import trafilatura

from templates import Source

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
FAST_WINDOW = timedelta(hours=48)
SLOW_WINDOW = timedelta(days=7)
MAX_PER_SOURCE = 5
IMG_SRC = re.compile(r"""<img[^>]+src=["'](https://[^"']+)""", re.I)
OG_IMAGE = re.compile(
    r"""<meta[^>]+(?:property|name)=["'](?:og:image|twitter:image)["'][^>]*content=["'](https://[^"']+)"""
    r"""|<meta[^>]+content=["'](https://[^"']+)["'][^>]*(?:property|name)=["'](?:og:image|twitter:image)["']""",
    re.I,
)
JUNK_IMAGE = re.compile(r"pixel|tracking|1x1|spacer|feedburner|gravatar|avatar|logo|\.gif(\?|$)", re.I)
TRACKING_PARAMS = re.compile(r"^(utm_|ref$|ref_src$|source$|mc_cid$|mc_eid$|fbclid$|gclid$)")


@dataclass
class Article:
    id: str
    title: str
    url: str
    source: str
    topic: str
    teaser: str
    published: datetime | None
    image: str = ""
    full_text: str = field(default="", repr=False)


def http_get(url: str, timeout: int = 15) -> bytes:
    req = Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/html, */*",
    })
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query) if not TRACKING_PARAMS.match(k)]
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path.rstrip("/"), urlencode(query), ""))


def clean_text(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _usable_image(url: str | None) -> str:
    url = html.unescape(url or "").strip()
    return url if url.startswith("https://") and not JUNK_IMAGE.search(url) else ""


def _entry_image(entry, body: str) -> str:
    for media in (entry.get("media_content") or []) + (entry.get("media_thumbnail") or []):
        if url := _usable_image(media.get("url")):
            return url
    for link in entry.get("links") or []:
        if link.get("rel") == "enclosure" and link.get("type", "").startswith("image"):
            if url := _usable_image(link.get("href")):
                return url
    match = IMG_SRC.search(body or "")
    return _usable_image(match.group(1)) if match else ""


def _entry_date(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        parsed = entry.get(key)
        if parsed:
            return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)
    return None


# Shared across templates in one run so each feed and article page is fetched once
_feed_cache: dict[tuple[str, bool], tuple[list[dict], str | None]] = {}
_page_cache: dict[str, tuple[str, str]] = {}


def fetch_feed(url: str, slow: bool) -> tuple[list[dict], str | None]:
    """Returns (fresh items, error). Items carry no source/topic; callers attach those."""
    try:
        feed = feedparser.parse(http_get(url))
    except Exception as e:
        return [], f"{type(e).__name__}: {str(e)[:80]}"
    if not feed.entries:
        return [], "no entries" + (f" ({feed.bozo_exception})" if feed.bozo else "")

    now = datetime.now(timezone.utc)
    cutoff = now - (SLOW_WINDOW if slow else FAST_WINDOW)
    items = []
    for entry in feed.entries[:30]:
        title = clean_text(entry.get("title", ""))
        link = entry.get("link", "")
        if not title or not link:
            continue
        published = _entry_date(entry)
        if published and (published < cutoff or published > now + timedelta(hours=6)):
            continue
        body = entry.get("summary", "")
        if entry.get("content"):
            body = max((c.get("value", "") for c in entry.content), key=len) or body
        items.append({
            "title": title,
            "url": link,
            "teaser": clean_text(body),
            "published": published,
            "image": _entry_image(entry, body),
        })
    items.sort(key=lambda x: x["published"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return items[:MAX_PER_SOURCE], None


def fetch_sources(sources: list[Source]) -> list[tuple[Source, list[dict], str | None]]:
    missing = list({(s.url, s.slow) for s in sources} - _feed_cache.keys())
    with ThreadPoolExecutor(max_workers=12) as pool:
        for key, result in zip(missing, pool.map(lambda k: fetch_feed(*k), missing)):
            _feed_cache[key] = result
    return [(s, *_feed_cache[(s.url, s.slow)]) for s in sources]


def _similar(a: str, b: str) -> bool:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio() > 0.85


def collect_candidates(sources: list[Source], sent_urls: set[str]) -> tuple[list[Article], dict[str, str]]:
    """Returns (deduped candidate articles, {source name: error}) for one template's sources."""
    results = fetch_sources(sources)
    errors = {src.name: err for src, _, err in results if err}
    seen: set[str] = set()
    titles: list[str] = []
    articles: list[Article] = []
    for src, items, _ in results:
        for item in items:
            key = normalize_url(item["url"])
            if key in seen or key in sent_urls or any(_similar(item["title"], t) for t in titles):
                continue
            seen.add(key)
            titles.append(item["title"])
            articles.append(Article(id=f"a{len(articles)}", source=src.name, topic=src.topic, **item))
    return articles, errors


def _extract_page(url: str) -> tuple[str, str]:
    """Returns (article text, og:image url), empty strings on failure."""
    try:
        page = http_get(url, timeout=20)
        text = trafilatura.extract(page, include_comments=False) or ""
        match = OG_IMAGE.search(page[:200_000].decode("utf-8", errors="ignore"))
        return text, _usable_image(match and (match.group(1) or match.group(2)))
    except Exception:
        return "", ""


def load_full_text(articles: list[Article]) -> None:
    missing = list({a.url for a in articles} - _page_cache.keys())
    with ThreadPoolExecutor(max_workers=8) as pool:
        for url, result in zip(missing, pool.map(_extract_page, missing)):
            _page_cache[url] = result
    for a in articles:
        text, image = _page_cache[a.url]
        # Paywalled or JS-heavy pages extract poorly; fall back to the feed body
        a.full_text = text if len(text) > len(a.teaser) else a.teaser
        a.image = a.image or image
