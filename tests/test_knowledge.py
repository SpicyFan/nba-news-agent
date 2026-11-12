from pathlib import Path

from hupu_nba_agent.tools.knowledge import KnowledgeBase


def kb() -> KnowledgeBase:
    return KnowledgeBase(Path("knowledge"))


def test_search_returns_sop_section() -> None:
    result = kb().search("标题 三段式 客观", top_k=3)
    assert result["results"]
    assert any(item["source"] == "hupu_sop.md" for item in result["results"])


def test_team_name_lookup() -> None:
    result = kb().lookup_entity("Los Angeles Lakers", "teams")
    assert result["matches"][0]["chinese"] == "洛杉矶湖人队"
    assert result["matches"][0]["short"] == "湖人"


def test_player_name_lookup() -> None:
    result = kb().lookup_entity("Shai Gilgeous-Alexander", "players")
    assert result["matches"][0]["chinese"] == "谢伊-吉尔杰斯-亚历山大"

