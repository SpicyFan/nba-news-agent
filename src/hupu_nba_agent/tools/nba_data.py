from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from .knowledge import KnowledgeBase

ESPN_BASE = "https://site.api.espn.com/apis"


class NbaDataTool:
    """Read-only NBA background lookup backed by local entities and ESPN public feeds."""

    def __init__(self, knowledge: KnowledgeBase, timeout: float = 30.0) -> None:
        self.knowledge = knowledge
        self.timeout = timeout
        self.headers = {"User-Agent": "hupu-nba-agent/0.1 (+editorial-mvp)"}

    def query(
        self,
        query: str,
        category: str = "auto",
        team_abbreviation: str = "",
    ) -> dict:
        category = category.lower().strip()
        local = self.knowledge.lookup_entity(query)
        result: dict[str, Any] = {
            "query": query,
            "category": category,
            "as_of": datetime.now(UTC).isoformat(),
            "local_reference": local["matches"],
            "provider": "ESPN public JSON feeds + local Hupu naming reference",
            "data": {},
            "notes": [],
        }

        try:
            if category in {"auto", "player", "stats"}:
                player = self._player(query)
                if player:
                    result["data"]["player"] = player
            if category in {"team", "schedule"} or team_abbreviation:
                abbreviation = team_abbreviation or self._team_abbreviation(local["matches"])
                if abbreviation:
                    result["data"]["team_schedule"] = self._team_schedule(abbreviation)
                else:
                    result["notes"].append("未解析到球队缩写，无法查询赛程。")
            if category in {"league", "scoreboard"}:
                result["data"]["scoreboard"] = self._scoreboard()
            if category == "contract":
                result["notes"].append(
                    "公开 JSON 源不提供可靠合同明细；必须再用 web_search 核对 NBA 官方、ESPN、"
                    "Spotrac 或记者原始报道，并保留截至日期。"
                )
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            result["notes"].append(
                f"实时数据查询失败（{type(exc).__name__}: {exc}）；必须使用 web_search 交叉核验。"
            )
        return result

    def _player(self, query: str) -> dict:
        search_url = f"{ESPN_BASE}/search/v2"
        with httpx.Client(
            timeout=self.timeout,
            headers=self.headers,
            follow_redirects=True,
        ) as client:
            response = client.get(search_url, params={"query": query, "limit": 10})
            response.raise_for_status()
            payload = response.json()
            group = next(
                (item for item in payload.get("results", []) if item.get("type") == "player"),
                None,
            )
            if not group or not group.get("contents"):
                return {}
            athlete = group["contents"][0]
            athlete_id = (athlete.get("uid", "").split("~a:")[-1] or "").strip()
            if not athlete_id.isdigit():
                return {"profile": athlete, "stats": {}}

            stats_url = (
                f"{ESPN_BASE}/common/v3/sports/basketball/nba/"
                f"athletes/{athlete_id}/stats"
            )
            stats_response = client.get(stats_url)
            stats_response.raise_for_status()
            stats_payload = stats_response.json()

        averages = next(
            (
                category
                for category in stats_payload.get("categories", [])
                if category.get("name") == "averages"
            ),
            {},
        )
        rows = averages.get("statistics", [])
        latest = rows[-1] if rows else {}
        names = averages.get("names", [])
        values = latest.get("stats", [])
        stats = dict(zip(names, values, strict=False))
        return {
            "id": athlete_id,
            "name": athlete.get("displayName", ""),
            "team": athlete.get("subtitle", ""),
            "profile_url": athlete.get("link", {}).get("web", ""),
            "image_url": athlete.get("image", {}).get("default", ""),
            "season": latest.get("season", {}).get("displayName", ""),
            "position": latest.get("position", ""),
            "stats": stats,
            "stats_source": f"https://www.espn.com/nba/player/stats/_/id/{athlete_id}",
        }

    def _team_schedule(self, abbreviation: str) -> dict:
        url = f"{ESPN_BASE}/site/v2/sports/basketball/nba/teams/{abbreviation.lower()}/schedule"
        with httpx.Client(
            timeout=self.timeout,
            headers=self.headers,
            follow_redirects=True,
        ) as client:
            response = client.get(url)
            response.raise_for_status()
            payload = response.json()
        events = payload.get("events", [])
        completed = [
            event
            for event in events
            if event.get("status", {}).get("type", {}).get("completed")
        ]
        upcoming = [
            event
            for event in events
            if not event.get("status", {}).get("type", {}).get("completed")
        ]
        return {
            "team": payload.get("team", {}).get("displayName", ""),
            "season": payload.get("season", {}).get("displayName", ""),
            "record": payload.get("team", {}).get("recordSummary", ""),
            "last_completed": [self._event_summary(event) for event in completed[-5:]],
            "next_games": [self._event_summary(event) for event in upcoming[:5]],
            "source_url": url,
        }

    def _scoreboard(self) -> dict:
        url = f"{ESPN_BASE}/site/v2/sports/basketball/nba/scoreboard"
        with httpx.Client(
            timeout=self.timeout,
            headers=self.headers,
            follow_redirects=True,
        ) as client:
            response = client.get(url)
            response.raise_for_status()
            payload = response.json()
        return {
            "season": payload.get("leagues", [{}])[0].get("season", {}).get("displayName", ""),
            "games": [self._event_summary(event) for event in payload.get("events", [])[:15]],
            "source_url": url,
        }

    @staticmethod
    def _event_summary(event: dict) -> dict:
        competition = (event.get("competitions") or [{}])[0]
        competitors = competition.get("competitors", [])
        teams = [
            {
                "team": item.get("team", {}).get("displayName", ""),
                "abbreviation": item.get("team", {}).get("abbreviation", ""),
                "score": item.get("score", ""),
                "home_away": item.get("homeAway", ""),
                "winner": item.get("winner", False),
                "records": [
                    record.get("summary", "")
                    for record in item.get("records", [])
                    if record.get("summary")
                ],
            }
            for item in competitors
        ]
        return {
            "name": event.get("name", ""),
            "date": event.get("date", ""),
            "status": event.get("status", {}).get("type", {}).get("description", ""),
            "teams": teams,
            "url": next(
                (
                    link.get("href", "")
                    for link in event.get("links", [])
                    if "summary" in link.get("rel", [])
                ),
                "",
            ),
        }

    @staticmethod
    def _team_abbreviation(matches: list[dict]) -> str:
        for match in matches:
            if match.get("type") == "teams" and match.get("abbreviation"):
                return str(match["abbreviation"])
        return ""
