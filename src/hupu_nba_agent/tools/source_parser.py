from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import asdict, dataclass
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

URL_RE = re.compile(r"https?://[^\s<>\"]+", re.IGNORECASE)
X_HOSTS = {"x.com", "www.x.com", "twitter.com", "www.twitter.com"}


@dataclass
class ParsedSource:
    source_type: str
    url: str = ""
    title: str = ""
    author: str = ""
    published_at: str = ""
    site_name: str = ""
    content: str = ""
    notes: list[str] | None = None

    def to_dict(self) -> dict:
        result = asdict(self)
        result["notes"] = self.notes or []
        return result


class SourceParser:
    """Parse pasted text, article URLs, and X/Twitter URLs into clean source material."""

    def __init__(self, timeout: float = 30.0, max_chars: int = 45_000) -> None:
        self.timeout = timeout
        self.max_chars = max_chars
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 Chrome/124 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.7",
        }

    def parse(self, raw_input: str) -> dict:
        text = raw_input.strip()
        match = URL_RE.search(text)
        if not match:
            return ParsedSource(source_type="text", content=text[: self.max_chars]).to_dict()

        url = match.group(0).rstrip(").,，。")
        host = (urlparse(url).hostname or "").lower()
        if host in X_HOSTS:
            return self._parse_x(url)
        return self._parse_article(url)

    def _parse_x(self, url: str) -> dict:
        self._validate_public_url(url)
        notes: list[str] = []
        oembed_url = "https://publish.twitter.com/oembed"
        try:
            with httpx.Client(
                timeout=self.timeout, follow_redirects=False, headers=self.headers
            ) as client:
                response = client.get(oembed_url, params={"url": url, "omit_script": "true"})
                response.raise_for_status()
                payload = response.json()
            html = payload.get("html", "")
            soup = BeautifulSoup(html, "html.parser")
            content = " ".join(soup.stripped_strings)
            return ParsedSource(
                source_type="x_post",
                url=url,
                author=payload.get("author_name", ""),
                site_name="X",
                content=content[: self.max_chars],
                notes=notes,
            ).to_dict()
        except (httpx.HTTPError, ValueError) as exc:
            notes.append(
                f"X 正文抓取失败（{type(exc).__name__}），应使用网页搜索交叉核验该链接。"
            )
            return ParsedSource(
                source_type="x_post",
                url=url,
                site_name="X",
                content="",
                notes=notes,
            ).to_dict()

    def _parse_article(self, url: str) -> dict:
        self._validate_public_url(url)
        notes: list[str] = []
        try:
            with httpx.Client(
                timeout=self.timeout, follow_redirects=False, headers=self.headers
            ) as client:
                response = self._get_public(client, url)
                response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if "html" not in content_type and "text" not in content_type:
                raise ValueError(f"不支持的内容类型：{content_type or 'unknown'}")
            soup = BeautifulSoup(response.text, "html.parser")
            for node in soup(["script", "style", "nav", "footer", "aside", "form", "noscript"]):
                node.decompose()

            title = self._meta(soup, "og:title") or self._text(soup.title)
            author = (
                self._meta(soup, "author")
                or self._meta(soup, "article:author")
                or self._named_meta(soup, "author")
            )
            published_at = (
                self._meta(soup, "article:published_time")
                or self._named_meta(soup, "date")
                or self._named_meta(soup, "pubdate")
            )
            site_name = self._meta(soup, "og:site_name")

            container = soup.find("article") or soup.find("main") or soup.body
            paragraphs = []
            if container:
                for p in container.find_all("p"):
                    paragraph = " ".join(p.stripped_strings)
                    if len(paragraph) >= 35:
                        paragraphs.append(paragraph)
            content = "\n\n".join(paragraphs)
            if not content and container:
                content = " ".join(container.stripped_strings)
                notes.append("页面未识别到文章段落，已回退到主内容区文本。")

            return ParsedSource(
                source_type="url",
                url=str(response.url),
                title=title,
                author=author,
                published_at=published_at,
                site_name=site_name,
                content=content[: self.max_chars],
                notes=notes,
            ).to_dict()
        except (httpx.HTTPError, ValueError) as exc:
            notes.append(
                f"网页抓取失败（{type(exc).__name__}: {exc}），应使用网页搜索读取和核验。"
            )
            return ParsedSource(
                source_type="url",
                url=url,
                content="",
                notes=notes,
            ).to_dict()

    @staticmethod
    def _meta(soup: BeautifulSoup, prop: str) -> str:
        node = soup.find("meta", attrs={"property": prop})
        return str(node.get("content", "")).strip() if node else ""

    @staticmethod
    def _named_meta(soup: BeautifulSoup, name: str) -> str:
        node = soup.find("meta", attrs={"name": name})
        return str(node.get("content", "")).strip() if node else ""

    @staticmethod
    def _text(node: object) -> str:
        return " ".join(getattr(node, "stripped_strings", [])) if node else ""

    @classmethod
    def _get_public(
        cls,
        client: httpx.Client,
        url: str,
        max_redirects: int = 5,
    ) -> httpx.Response:
        current = url
        for _ in range(max_redirects + 1):
            cls._validate_public_url(current)
            response = client.get(current)
            if not response.is_redirect:
                return response
            location = response.headers.get("location")
            if not location:
                return response
            current = urljoin(current, location)
        raise ValueError(f"重定向次数超过上限：{max_redirects}")

    @staticmethod
    def _validate_public_url(url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("仅支持公开的 HTTP/HTTPS URL。")
        host = parsed.hostname.lower()
        if host in {"localhost", "localhost.localdomain"}:
            raise ValueError("不允许访问本机地址。")
        try:
            addresses = {item[4][0] for item in socket.getaddrinfo(host, parsed.port or 443)}
        except socket.gaierror as exc:
            raise ValueError(f"域名无法解析：{host}") from exc
        for address in addresses:
            ip = ipaddress.ip_address(address)
            if not ip.is_global:
                raise ValueError("不允许访问私有、回环或保留地址。")
