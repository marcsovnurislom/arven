"""RSS parsing: real-shaped RSS 2.0 fixtures, missing-field handling, stable news_id."""

from __future__ import annotations

from arven.core.time import from_ms
from arven.news.rss import news_id, parse_rss

RSS_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Feed</title>
{items}
</channel></rss>"""

ITEM = """<item>
  <title>{title}</title>
  <link>{link}</link>
  <pubDate>{pubdate}</pubDate>
  <description><![CDATA[<p>body</p>]]></description>
</item>"""


def feed(*items: str) -> bytes:
    return RSS_TEMPLATE.format(items="\n".join(items)).encode()


def test_parses_title_link_and_pubdate():
    xml = feed(ITEM.format(title="Bitcoin hits new high", link="https://x.com/a", pubdate="Sun, 04 Oct 2026 22:31:12 +0000"))
    items = parse_rss(xml, "coindesk")
    assert len(items) == 1
    it = items[0]
    assert it.title == "Bitcoin hits new high" and it.url == "https://x.com/a" and it.source == "coindesk"
    assert from_ms(it.published_at_ms).isoformat() == "2026-10-04T22:31:12+00:00"


def test_news_id_is_stable_and_source_url_dependent():
    a = news_id("coindesk", "https://x.com/a")
    assert a == news_id("coindesk", "https://x.com/a")
    assert a != news_id("cointelegraph", "https://x.com/a")  # same URL, different source -> different id
    assert a != news_id("coindesk", "https://x.com/b")


def test_an_item_missing_a_required_field_is_skipped_not_guessed():
    missing_title = """<item><link>https://x.com/a</link><pubDate>Sun, 04 Oct 2026 22:31:12 +0000</pubDate></item>"""
    missing_pubdate = ITEM.format(title="t", link="https://x.com/b", pubdate="")
    good = ITEM.format(title="good", link="https://x.com/c", pubdate="Sun, 04 Oct 2026 22:31:12 +0000")
    items = parse_rss(feed(missing_title, missing_pubdate, good), "coindesk")
    assert [i.title for i in items] == ["good"]


def test_an_unparseable_pubdate_is_skipped_not_guessed():
    bad = ITEM.format(title="bad date", link="https://x.com/d", pubdate="not-a-date")
    good = ITEM.format(title="good", link="https://x.com/e", pubdate="Sun, 04 Oct 2026 22:31:12 +0000")
    items = parse_rss(feed(bad, good), "coindesk")
    assert [i.title for i in items] == ["good"]


def test_different_timezone_offsets_convert_correctly_to_utc():
    # 18:00 -0400 == 22:00 UTC
    xml = feed(ITEM.format(title="t", link="https://x.com/f", pubdate="Mon, 05 Oct 2026 18:00:00 -0400"))
    it = parse_rss(xml, "coindesk")[0]
    assert from_ms(it.published_at_ms).isoformat() == "2026-10-05T22:00:00+00:00"


def test_empty_feed_returns_no_items():
    assert parse_rss(feed(), "coindesk") == ()
