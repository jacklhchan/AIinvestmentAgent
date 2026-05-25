from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha1
from typing import Any
from xml.etree import ElementTree

import httpx

from .config import Settings
from .models import NewsIngestResult, NewsItem, utc_now
from .store import Store


class IrFeedIngestor:
    def __init__(self, settings: Settings, store: Store, client: httpx.Client | None = None):
        self.settings = settings
        self.store = store
        self.client = client

    def refresh_ir_feeds(self, feeds: dict[str, str] | None = None, *, limit_per_feed: int = 5) -> NewsIngestResult:
        feed_map = feeds if feeds is not None else parse_ir_feed_config(self.settings.ir_rss_feeds)
        errors: list[str] = []
        items: list[NewsItem] = []

        owns_client = self.client is None
        client = self.client or httpx.Client(timeout=min(8.0, self.settings.news_timeout_seconds + 3.0))
        try:
            for symbol, url in feed_map.items():
                try:
                    response = client.get(url)
                    response.raise_for_status()
                    items.extend(ir_items_from_feed(symbol, response.text, source_url=url, limit=limit_per_feed))
                except (httpx.HTTPError, ValueError, ElementTree.ParseError) as exc:
                    errors.append(f"ir {symbol}: {exc}")
        finally:
            if owns_client:
                client.close()

        stored: dict[str, NewsItem] = {}
        for item in items:
            if item.id in stored:
                continue
            self.store.upsert_news(item)
            stored[item.id] = item

        self.store.audit(
            "ir_feeds_refreshed",
            "news",
            "company-ir",
            {
                "symbols": list(feed_map.keys()),
                "stored_count": len(stored),
                "total_count": len(items),
                "errors": errors,
            },
        )

        return NewsIngestResult(
            symbols=list(feed_map.keys()),
            total_count=len(items),
            stored_count=len(stored),
            sources={"company-ir": len(stored)} if stored else {},
            errors=errors,
            items=list(stored.values()),
        )


def parse_ir_feed_config(raw: str) -> dict[str, str]:
    feeds: dict[str, str] = {}
    for entry in raw.replace("\n", ";").split(";"):
        if not entry.strip() or "=" not in entry:
            continue
        symbol, url = entry.split("=", 1)
        symbol = symbol.strip().upper()
        url = url.strip()
        if symbol and url:
            feeds[symbol] = url
    return feeds


def ir_items_from_feed(symbol: str, xml_text: str, *, source_url: str, limit: int) -> list[NewsItem]:
    root = ElementTree.fromstring(xml_text)
    if root.tag.endswith("feed"):
        return _atom_items(symbol, root, source_url=source_url, limit=limit)
    return _rss_items(symbol, root, source_url=source_url, limit=limit)


def _rss_items(symbol: str, root: ElementTree.Element, *, source_url: str, limit: int) -> list[NewsItem]:
    items: list[NewsItem] = []
    for node in root.findall("./channel/item")[:limit]:
        title = _xml_text(node, "title")
        link = _xml_text(node, "link") or source_url
        pub_date = _xml_text(node, "pubDate")
        if not title:
            continue
        items.append(_news_item(symbol, title, link, pub_date))
    return items


def _atom_items(symbol: str, root: ElementTree.Element, *, source_url: str, limit: int) -> list[NewsItem]:
    namespace = ""
    if root.tag.startswith("{"):
        namespace = root.tag.split("}", 1)[0] + "}"
    items: list[NewsItem] = []
    for node in root.findall(f"./{namespace}entry")[:limit]:
        title = _xml_text(node, f"{namespace}title")
        updated = _xml_text(node, f"{namespace}updated") or _xml_text(node, f"{namespace}published")
        link = source_url
        link_node = node.find(f"{namespace}link")
        if link_node is not None:
            link = str(link_node.attrib.get("href") or link)
        if not title:
            continue
        items.append(_news_item(symbol, title, link, updated))
    return items


def _news_item(symbol: str, title: str, link: str, date_value: str) -> NewsItem:
    return NewsItem(
        id=_stable_ir_id(symbol, link or title),
        symbol=symbol.strip().upper(),
        title=title,
        source="company-ir",
        url=link or None,
        published_at=_parse_date(date_value),
        tags=["primary-source", "company-ir"],
        summary="Primary-source company investor-relations feed item.",
    )


def _parse_date(value: str):
    if not value:
        return utc_now()
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return utc_now()
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _xml_text(node: ElementTree.Element, tag: str) -> str:
    child = node.find(tag)
    return (child.text or "").strip() if child is not None else ""


def _stable_ir_id(symbol: str, value: str) -> str:
    digest = sha1(f"ir:{symbol.upper()}:{value}".encode("utf-8")).hexdigest()[:16]
    return f"news_company-ir_{digest}"
