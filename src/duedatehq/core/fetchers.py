from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


@dataclass(frozen=True, slots=True)
class FetchedDocument:
    raw_text: str
    source_url: str
    fetched_at: datetime


class Fetcher(Protocol):
    def fetch(self) -> FetchedDocument: ...


@dataclass(slots=True)
class FileFetcher:
    path: Path
    source_url: str
    fetched_at: datetime | None = None

    def fetch(self) -> FetchedDocument:
        return FetchedDocument(
            raw_text=self.path.read_text(encoding="utf-8"),
            source_url=self.source_url,
            fetched_at=self.fetched_at or datetime.now(timezone.utc),
        )


@dataclass(slots=True)
class HttpTextFetcher:
    url: str
    fetched_at: datetime | None = None
    user_agent: str = "DueDateHQ/0.1"

    def fetch(self) -> FetchedDocument:
        request = Request(self.url, headers={"User-Agent": self.user_agent})
        with urlopen(request, timeout=30) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            raw_text = response.read().decode(charset, errors="replace")
        return FetchedDocument(
            raw_text=raw_text,
            source_url=self.url,
            fetched_at=self.fetched_at or datetime.now(timezone.utc),
        )


@dataclass(slots=True)
class RssEntryFetcher:
    url: str
    entry_title_contains: str | None = None
    fetched_at: datetime | None = None
    user_agent: str = "DueDateHQ/0.1"

    def fetch(self) -> FetchedDocument:
        request = Request(self.url, headers={"User-Agent": self.user_agent})
        with urlopen(request, timeout=30) as response:
            raw_xml = response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")
        root = ET.fromstring(raw_xml)
        channel = root.find("channel")
        if channel is None:
            raise ValueError("RSS channel not found")
        items = channel.findall("item")
        if not items:
            raise ValueError("RSS feed has no items")
        selected = items[0]
        if self.entry_title_contains:
            lowered = self.entry_title_contains.lower()
            for item in items:
                title = (item.findtext("title") or "").lower()
                if lowered in title:
                    selected = item
                    break
        title = selected.findtext("title") or ""
        description = selected.findtext("description") or ""
        link = selected.findtext("link") or self.url
        raw_text = f"{title}\n\n{description}".strip()
        return FetchedDocument(
            raw_text=raw_text,
            source_url=link,
            fetched_at=self.fetched_at or datetime.now(timezone.utc),
        )
