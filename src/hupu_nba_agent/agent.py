from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI
from pydantic import ValidationError

from .config import Settings
from .models import (
    AgentResponse,
    GenerateRequest,
    NewsPackage,
    ToolTrace,
)
from .prompts import system_instructions, user_prompt
from .tools import ContentAuditor, KnowledgeBase, NbaDataTool, SourceParser

HTTP_RE = re.compile(r"https?://[^\s\"'<>]+")


class HupuNbaAgent:
    """One model, one continuous tool loop, one deterministic publish gate."""

    def __init__(
        self,
        settings: Settings | None = None,
        client: OpenAI | None = None,
    ) -> None:
        self.settings = settings or Settings()
        self.settings.require_api_key()
        client_kwargs: dict[str, Any] = {
            "api_key": self.settings.openai_api_key,
            "timeout": self.settings.request_timeout,
        }
        if self.settings.openai_base_url:
            client_kwargs["base_url"] = self.settings.openai_base_url
        self.client = client or OpenAI(**client_kwargs)
        self.knowledge = KnowledgeBase(self.settings.knowledge_dir)
        self.source_parser = SourceParser(timeout=self.settings.request_timeout)
        self.nba_data = NbaDataTool(self.knowledge, timeout=self.settings.request_timeout)
        self.auditor = ContentAuditor()

    def run(self, request: GenerateRequest) -> AgentResponse:
        use_web = (
            self.settings.web_search
            if request.use_web_search is None
            else request.use_web_search
        )
        tools = self._tool_definitions(use_web)
        instructions = system_instructions(request.mode)
        input_items: list[Any] = [
            {
                "role": "user",
                "content": user_prompt(request.source, request.mode, request.editor_note),
            }
        ]
        trace: list[ToolTrace] = []
        consulted_urls: set[str] = set()
        last_package: NewsPackage | None = None
        last_response_id = ""

        for round_number in range(1, self.settings.max_tool_rounds + 1):
            response = self.client.responses.parse(
                model=self.settings.openai_model,
                reasoning={"effort": self.settings.openai_reasoning_effort},
                instructions=instructions,
                input=input_items,
                tools=tools,
                tool_choice="auto",
                include=["web_search_call.action.sources"] if use_web else [],
                text_format=NewsPackage,
                store=False,
            )
            last_response_id = response.id
            dumped = response.model_dump(mode="json")
            consulted_urls.update(self._collect_urls(dumped))
            input_items.extend(response.output)

            calls = [item for item in response.output if item.type == "function_call"]
            if calls:
                for call in calls:
                    try:
                        arguments = json.loads(call.arguments or "{}")
                        output = self._dispatch(call.name, arguments)
                        ok = True
                        summary = self._summary(output)
                    except Exception as exc:  # noqa: BLE001 - tool errors become model-visible
                        arguments = self._safe_arguments(call.arguments)
                        output = {
                            "ok": False,
                            "error": type(exc).__name__,
                            "message": str(exc),
                        }
                        ok = False
                        summary = f"{type(exc).__name__}: {exc}"
                    trace.append(
                        ToolTrace(
                            round=round_number,
                            tool=call.name,
                            arguments=arguments,
                            ok=ok,
                            summary=summary,
                        )
                    )
                    input_items.append(
                        {
                            "type": "function_call_output",
                            "call_id": call.call_id,
                            "output": json.dumps(output, ensure_ascii=False),
                        }
                    )
                continue

            try:
                package = response.output_parsed or NewsPackage.model_validate_json(
                    response.output_text
                )
            except (ValidationError, ValueError) as exc:
                input_items.append(
                    {
                        "role": "user",
                        "content": (
                            "结构化输出无法解析。请修正所有必填字段并重新输出。"
                            f"解析错误：{exc}"
                        ),
                    }
                )
                continue

            final_audit = self.auditor.audit(
                package.draft.model_dump(mode="json"),
                [item.model_dump(mode="json") for item in package.evidence],
                request.mode.value,
            )
            package.audit = package.audit.model_validate(final_audit)
            last_package = package
            consulted_urls.update(item.source_url for item in package.evidence if item.source_url)
            if package.draft.source_url:
                consulted_urls.add(package.draft.source_url)

            if package.audit.passed:
                return AgentResponse(
                    result=package,
                    tool_trace=trace,
                    model=self.settings.openai_model,
                    response_id=response.id,
                    consulted_urls=sorted(consulted_urls),
                )

            input_items.append(
                {
                    "role": "user",
                    "content": (
                        "最终确定性发布审核未通过。请根据以下报告修正文稿，重新调用 audit_draft，"
                        "然后输出完整结构化结果：\n"
                        f"{json.dumps(final_audit, ensure_ascii=False)}"
                    ),
                }
            )

        if last_package is not None:
            if "自动工具轮次已耗尽，禁止直接发布。" not in last_package.editorial_notes:
                last_package.editorial_notes.append("自动工具轮次已耗尽，禁止直接发布。")
            return AgentResponse(
                result=last_package,
                tool_trace=trace,
                model=self.settings.openai_model,
                response_id=last_response_id,
                consulted_urls=sorted(consulted_urls),
            )
        raise RuntimeError(
            f"Agent 在 {self.settings.max_tool_rounds} 轮内未生成可解析的新闻稿。"
        )

    def _dispatch(self, name: str, arguments: dict[str, Any]) -> dict:
        if name == "parse_source_input":
            return self.source_parser.parse(arguments["raw_input"])
        if name == "search_hupu_knowledge":
            return self.knowledge.search(arguments["query"], arguments["top_k"])
        if name == "lookup_nba_reference":
            return self.knowledge.lookup_entity(
                arguments["query"],
                arguments["entity_type"],
            )
        if name == "query_nba_data":
            return self.nba_data.query(
                arguments["query"],
                arguments["category"],
                arguments["team_abbreviation"],
            )
        if name == "audit_draft":
            return self.auditor.audit(
                arguments["draft"],
                arguments["evidence"],
                arguments["mode"],
            )
        raise KeyError(f"未知工具：{name}")

    @staticmethod
    def _tool_definitions(use_web_search: bool) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        if use_web_search:
            tools.append({"type": "web_search", "search_context_size": "medium"})
        tools.extend(
            [
                {
                    "type": "function",
                    "name": "parse_source_input",
                    "description": (
                        "解析用户提供的文章 URL、X 帖子 URL 或全文。返回 source_type、url、"
                        "title、author、published_at、site_name、content、notes。抓取失败时 content"
                        " 可能为空且 notes 说明原因，此时用 web_search 回退。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "raw_input": {
                                "type": "string",
                                "description": "用户原始输入，必须原样传入。",
                            }
                        },
                        "required": ["raw_input"],
                        "additionalProperties": False,
                    },
                    "strict": True,
                },
                {
                    "type": "function",
                    "name": "search_hupu_knowledge",
                    "description": (
                        "检索本地虎扑 SOP、标题规范、正文模板、翻译规则和示例。返回带来源文件名、"
                        "标题、文本和相关性分数的片段。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "top_k": {"type": "integer", "minimum": 1, "maximum": 8},
                        },
                        "required": ["query", "top_k"],
                        "additionalProperties": False,
                    },
                    "strict": True,
                },
                {
                    "type": "function",
                    "name": "lookup_nba_reference",
                    "description": (
                        "查询本地球员中文名、球队规范名、记者和篮球术语。返回 matches；空数组表示"
                        "本地 MVP 词库未收录，需用可靠来源确认后在 editorial_notes 标记待扩充。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "entity_type": {
                                "type": "string",
                                "enum": [
                                    "auto",
                                    "players",
                                    "teams",
                                    "reporters",
                                    "terms",
                                ],
                            },
                        },
                        "required": ["query", "entity_type"],
                        "additionalProperties": False,
                    },
                    "strict": True,
                },
                {
                    "type": "function",
                    "name": "query_nba_data",
                    "description": (
                        "查询 NBA 球员基础资料/赛季场均、球队近期赛果和未来赛程。category 可为"
                        " auto/player/stats/team/schedule/scoreboard/league/contract。合同类只返回"
                        "核验提示，必须再用 web_search。实时结果含 as_of 和来源。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "category": {
                                "type": "string",
                                "enum": [
                                    "auto",
                                    "player",
                                    "stats",
                                    "team",
                                    "schedule",
                                    "scoreboard",
                                    "league",
                                    "contract",
                                ],
                            },
                            "team_abbreviation": {
                                "type": "string",
                                "description": "ESPN 三字母球队缩写；未知时传空字符串。",
                            },
                        },
                        "required": ["query", "category", "team_abbreviation"],
                        "additionalProperties": False,
                    },
                    "strict": True,
                },
                {
                    "type": "function",
                    "name": "audit_draft",
                    "description": (
                        "确定性发布前审核。检查三段式、主观/夸张表达、姓名连接符、链接、表格、"
                        "动态数据证据、引号和球队简称。返回 passed、score、issues、checked_at。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "draft": {
                                "type": "object",
                                "properties": {
                                    "title": {"type": "string"},
                                    "lead": {"type": "string"},
                                    "body_paragraphs": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "background_paragraphs": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "source_url": {"type": "string"},
                                    "alternate_titles": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                },
                                "required": [
                                    "title",
                                    "lead",
                                    "body_paragraphs",
                                    "background_paragraphs",
                                    "source_url",
                                    "alternate_titles",
                                ],
                                "additionalProperties": False,
                            },
                            "evidence": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "claim": {"type": "string"},
                                        "value": {"type": "string"},
                                        "as_of": {"type": "string"},
                                        "source_name": {"type": "string"},
                                        "source_url": {"type": "string"},
                                    },
                                    "required": [
                                        "claim",
                                        "value",
                                        "as_of",
                                        "source_name",
                                        "source_url",
                                    ],
                                    "additionalProperties": False,
                                },
                            },
                            "mode": {
                                "type": "string",
                                "enum": ["news", "longform"],
                            },
                        },
                        "required": ["draft", "evidence", "mode"],
                        "additionalProperties": False,
                    },
                    "strict": True,
                },
            ]
        )
        return tools

    @staticmethod
    def _collect_urls(value: Any) -> set[str]:
        if isinstance(value, str):
            return {match.rstrip(").,，。") for match in HTTP_RE.findall(value)}
        if isinstance(value, dict):
            found: set[str] = set()
            for child in value.values():
                found.update(HupuNbaAgent._collect_urls(child))
            return found
        if isinstance(value, list):
            found = set()
            for child in value:
                found.update(HupuNbaAgent._collect_urls(child))
            return found
        return set()

    @staticmethod
    def _summary(output: dict) -> str:
        encoded = json.dumps(output, ensure_ascii=False)
        return encoded[:240] + ("…" if len(encoded) > 240 else "")

    @staticmethod
    def _safe_arguments(raw: str) -> dict[str, Any]:
        try:
            parsed = json.loads(raw or "{}")
            return parsed if isinstance(parsed, dict) else {"raw": parsed}
        except ValueError:
            return {"raw": raw}
