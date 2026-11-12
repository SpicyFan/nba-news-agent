import httpx
import pytest

from hupu_nba_agent.tools.source_parser import SourceParser


def test_plain_text_is_preserved() -> None:
    result = SourceParser().parse("Shams reports that a player has agreed to a deal.")
    assert result["source_type"] == "text"
    assert "agreed to a deal" in result["content"]


def test_localhost_is_blocked() -> None:
    with pytest.raises(ValueError, match="本机"):
        SourceParser().parse("http://localhost:8000/private")


def test_article_metadata_and_paragraph_extraction(monkeypatch: pytest.MonkeyPatch) -> None:
    html = """
    <html><head>
      <meta property="og:title" content="NBA story">
      <meta property="og:site_name" content="Example Sports">
      <meta name="author" content="Reporter Name">
    </head><body><article>
      <p>This is a sufficiently long first paragraph about an NBA transaction.</p>
      <p>This is another sufficiently long paragraph with the confirmed details.</p>
    </article></body></html>
    """

    def fake_get(self, url, **kwargs):  # noqa: ANN001
        request = httpx.Request("GET", url)
        return httpx.Response(
            200,
            request=request,
            text=html,
            headers={"content-type": "text/html; charset=utf-8"},
        )

    monkeypatch.setattr(SourceParser, "_validate_public_url", lambda self_or_url, url=None: None)
    monkeypatch.setattr(httpx.Client, "get", fake_get)
    result = SourceParser().parse("https://example.com/nba")
    assert result["title"] == "NBA story"
    assert result["author"] == "Reporter Name"
    assert "confirmed details" in result["content"]

