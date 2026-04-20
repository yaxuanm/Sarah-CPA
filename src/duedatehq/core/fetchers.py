from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from typing import Protocol
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

from .sources import source_for_selector


@dataclass(frozen=True, slots=True)
class FetchedDocument:
    raw_text: str
    source_url: str
    fetched_at: datetime
    content_type: str = "text/plain"


class Fetcher(Protocol):
    def fetch(self) -> FetchedDocument: ...


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self.parts.append(text)

    def get_text(self) -> str:
        return "\n".join(self.parts)


@dataclass(slots=True)
class FileFetcher:
    path: Path
    source_url: str
    fetched_at: datetime | None = None

    def fetch(self) -> FetchedDocument:
        content = self.path.read_text(encoding="utf-8")
        return FetchedDocument(
            raw_text=content,
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
            content_type = response.headers.get_content_type()
        return FetchedDocument(
            raw_text=raw_text,
            source_url=self.url,
            fetched_at=self.fetched_at or datetime.now(timezone.utc),
            content_type=content_type,
        )


@dataclass(slots=True)
class HtmlFetcher:
    url: str
    fetched_at: datetime | None = None

    def fetch(self) -> FetchedDocument:
        document = HttpTextFetcher(self.url, self.fetched_at).fetch()
        parser = _HTMLTextExtractor()
        parser.feed(document.raw_text)
        return FetchedDocument(
            raw_text=parser.get_text(),
            source_url=document.source_url,
            fetched_at=document.fetched_at,
            content_type="text/html",
        )


@dataclass(slots=True)
class PdfFetcher:
    url: str
    fetched_at: datetime | None = None
    user_agent: str = "DueDateHQ/0.1"

    def fetch(self) -> FetchedDocument:
        try:
            import pypdf
        except ImportError as exc:
            raise RuntimeError("PDF fetching requires pypdf. Install the optional fetch/pdf dependencies.") from exc
        request = Request(self.url, headers={"User-Agent": self.user_agent})
        with urlopen(request, timeout=30) as response:
            payload = response.read()
        reader = pypdf.PdfReader(BytesIO(payload))
        pages = [page.extract_text() or "" for page in reader.pages]
        return FetchedDocument(
            raw_text="\n".join(pages).strip(),
            source_url=self.url,
            fetched_at=self.fetched_at or datetime.now(timezone.utc),
            content_type="application/pdf",
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
            content_type="application/rss+xml",
        )


def fetcher_for_source(
    *,
    source: str | None = None,
    state: str | None = None,
    fetched_at: datetime | None = None,
) -> Fetcher:
    definition = source_for_selector(source=source, state=state)
    if definition.fetch_format == "rss":
        return RssEntryFetcher(url=definition.default_url, fetched_at=fetched_at)
    if definition.fetch_format == "pdf":
        return PdfFetcher(url=definition.default_url, fetched_at=fetched_at)
    return HtmlFetcher(url=definition.default_url, fetched_at=fetched_at)
