"""RSS fetch + parse (stdlib only - no new dependency for XML/RFC-822 parsing).

Reuses ``data.download.Downloader`` for the actual HTTP (retries, backoff, timeouts), exactly like
``data.adapters.binance_rest`` does for REST calls - the same pattern, a different content type.
"""

from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from email.utils import parsedate_to_datetime

from arven.core.time import to_ms
from arven.data.download import Downloader


@dataclass(frozen=True, slots=True)
class RawNewsItem:
    news_id: str  # sha256 of (source, url) - stable, content-independent
    source: str
    url: str
    title: str
    published_at_ms: int


def news_id(source: str, url: str) -> str:
    return hashlib.sha256(f"{source}|{url}".encode()).hexdigest()


def fetch_feed(downloader: Downloader, url: str) -> bytes:
    return downloader.fetch_bytes(url)


def parse_rss(xml_bytes: bytes, source: str) -> tuple[RawNewsItem, ...]:
    """Parse an RSS 2.0 ``<channel><item>...</item></channel>`` document. Items missing a required field
    (title, link, or a parseable pubDate) are skipped, not guessed - never silently inventing a timestamp
    for a feed item whose actual publish time is unknown."""
    root = ET.fromstring(xml_bytes)
    items: list[RawNewsItem] = []
    for item in root.iterfind(".//item"):
        title_el, link_el, pubdate_el = item.find("title"), item.find("link"), item.find("pubDate")
        if title_el is None or link_el is None or pubdate_el is None:
            continue
        title, link, pubdate = (title_el.text or "").strip(), (link_el.text or "").strip(), (pubdate_el.text or "").strip()
        if not title or not link or not pubdate:
            continue
        try:
            published_at_ms = to_ms(parsedate_to_datetime(pubdate))
        except (TypeError, ValueError):
            continue
        items.append(RawNewsItem(news_id(source, link), source, link, title, published_at_ms))
    return tuple(items)
