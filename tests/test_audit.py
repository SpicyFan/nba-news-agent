import json
from pathlib import Path

from hupu_nba_agent.tools.audit import ContentAuditor


def test_valid_draft_passes() -> None:
    payload = json.loads(
        Path("tests/fixtures/valid_draft.json").read_text(encoding="utf-8")
    )
    report = ContentAuditor().audit(payload["draft"], payload["evidence"])
    assert report["passed"] is True
    assert report["score"] >= 85


def test_subjective_name_separator_and_missing_evidence_fail() -> None:
    draft = {
        "title": "震惊！我认为勒布朗·詹姆斯历史最强",
        "lead": "我觉得他目前场均得到30分。",
        "body_paragraphs": ["这是一段正文。"],
        "background_paragraphs": ["这是背景。"],
        "source_url": "https://example.com/story",
    }
    report = ContentAuditor().audit(draft, [])
    codes = {issue["code"] for issue in report["issues"]}
    assert report["passed"] is False
    assert "subjective_language" in codes
    assert "name_separator" in codes
    assert "dynamic_data_unverified" in codes


def test_body_url_is_rejected() -> None:
    draft = {
        "title": "测试标题",
        "lead": "北京时间今日，球队公布一项消息。",
        "body_paragraphs": ["详情见 https://example.com/story 。"],
        "background_paragraphs": ["球队稍后将更新进展。"],
        "source_url": "https://example.com/story",
    }
    report = ContentAuditor().audit(draft, [])
    assert "body_url" in {issue["code"] for issue in report["issues"]}


def test_longform_requires_ten_alternate_titles() -> None:
    payload = json.loads(
        Path("tests/fixtures/valid_draft.json").read_text(encoding="utf-8")
    )
    report = ContentAuditor().audit(payload["draft"], payload["evidence"], "longform")
    assert report["passed"] is False
    assert "longform_title_count" in {issue["code"] for issue in report["issues"]}
