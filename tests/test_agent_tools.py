from pathlib import Path
from types import SimpleNamespace

from hupu_nba_agent.agent import HupuNbaAgent
from hupu_nba_agent.config import Settings
from hupu_nba_agent.models import (
    AuditReport,
    EvidenceItem,
    GenerateRequest,
    NewsDraft,
    NewsPackage,
    SourceAnalysis,
)


def test_tool_definitions_include_all_mvp_tools() -> None:
    tools = HupuNbaAgent._tool_definitions(use_web_search=True)
    names = {tool.get("name") for tool in tools if tool["type"] == "function"}
    assert names == {
        "parse_source_input",
        "search_hupu_knowledge",
        "lookup_nba_reference",
        "query_nba_data",
        "audit_draft",
    }
    assert any(tool["type"] == "web_search" for tool in tools)


def test_tool_definitions_can_disable_web_search() -> None:
    tools = HupuNbaAgent._tool_definitions(use_web_search=False)
    assert all(tool["type"] != "web_search" for tool in tools)


class FakeResponse:
    def __init__(self, response_id, output, parsed=None):  # noqa: ANN001
        self.id = response_id
        self.output = output
        self.output_parsed = parsed
        self.output_text = parsed.model_dump_json() if parsed else ""

    def model_dump(self, mode="json"):  # noqa: ARG002
        return {"id": self.id, "output": []}


class FakeResponses:
    def __init__(self, queue):  # noqa: ANN001
        self.queue = list(queue)
        self.inputs = []

    def parse(self, **kwargs):  # noqa: ANN003
        self.inputs.append(kwargs["input"].copy())
        return self.queue.pop(0)


def test_single_agent_executes_function_output_then_returns_package() -> None:
    call = SimpleNamespace(
        type="function_call",
        name="parse_source_input",
        arguments='{"raw_input":"Shams reports a signing."}',
        call_id="call_1",
    )
    package = NewsPackage(
        source_analysis=SourceAnalysis(
            source_type="text",
            source_name="ESPN",
            reporter="沙姆斯-查拉尼亚",
            core_facts=["测试球员签约。"],
        ),
        evidence=[
            EvidenceItem(
                claim="签约消息",
                value="已签约",
                as_of="2026-07-23",
                source_name="ESPN",
                source_url="https://example.com/source",
            )
        ],
        draft=NewsDraft(
            title="记者：测试球队与测试球员完成签约",
            lead="北京时间今日，据记者报道，测试球队与测试球员完成签约。",
            body_paragraphs=["报道确认了双方完成签约这一事实。"],
            background_paragraphs=["球队尚未公布更多协议细节。"],
            source_name="ESPN",
            source_url="https://example.com/source",
        ),
        audit=AuditReport(passed=True, score=100),
    )
    fake_responses = FakeResponses(
        [
            FakeResponse("resp_1", [call]),
            FakeResponse("resp_2", [], parsed=package),
        ]
    )
    fake_client = SimpleNamespace(responses=fake_responses)
    settings = Settings(
        OPENAI_API_KEY="test",
        NBA_AGENT_WEB_SEARCH=False,
        knowledge_dir=Path("knowledge"),
    )
    result = HupuNbaAgent(settings=settings, client=fake_client).run(
        GenerateRequest(source="Shams reports a signing.", use_web_search=False)
    )
    assert result.result.audit.passed is True
    assert result.tool_trace[0].tool == "parse_source_input"
    second_input = fake_responses.inputs[1]
    assert any(
        isinstance(item, dict) and item.get("type") == "function_call_output"
        for item in second_input
    )
