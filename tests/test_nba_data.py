from pathlib import Path

from hupu_nba_agent.tools.knowledge import KnowledgeBase
from hupu_nba_agent.tools.nba_data import NbaDataTool


def test_contract_query_requires_web_verification() -> None:
    tool = NbaDataTool(KnowledgeBase(Path("knowledge")))
    result = tool.query("LeBron James", category="contract")
    assert any("web_search" in note for note in result["notes"])
    assert result["local_reference"]


def test_team_abbreviation_resolves_locally(monkeypatch) -> None:  # noqa: ANN001
    tool = NbaDataTool(KnowledgeBase(Path("knowledge")))
    monkeypatch.setattr(
        tool,
        "_team_schedule",
        lambda abbreviation: {"team": "Los Angeles Lakers", "abbreviation": abbreviation},
    )
    result = tool.query("湖人", category="schedule")
    assert result["data"]["team_schedule"]["abbreviation"] == "LAL"

