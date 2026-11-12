from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urlparse

from hupu_nba_agent.models import AuditIssue, AuditReport

SUBJECTIVE_TERMS = (
    "我觉得",
    "我认为",
    "在我看来",
    "毫无疑问",
    "显然是",
    "可笑",
    "垃圾",
)
CLICKBAIT_TERMS = ("震惊", "炸裂", "完爆", "史诗级", "历史最强", "天塌了")
DYNAMIC_TERMS = (
    "目前",
    "至今",
    "过去",
    "最近",
    "接下来",
    "剩余",
    "连胜",
    "连败",
    "场均",
    "战绩",
    "合同",
    "命中率",
)
ALLOWED_LATIN = {
    "NBA",
    "MVP",
    "FMVP",
    "DPOY",
    "NCAA",
    "CBA",
    "FIBA",
    "ESPN",
    "X",
    "G",
}
LATIN_RE = re.compile(r"(?<![A-Za-z])[A-Za-z][A-Za-z0-9.'-]*(?![A-Za-z])")
URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
TABLE_RE = re.compile(r"^\s*\|.+\|\s*$", re.MULTILINE)
NUMERIC_RE = re.compile(r"\d")


class ContentAuditor:
    """Deterministic pre-publish checks derived from the supplied Hupu SOP."""

    def audit(
        self,
        draft: dict,
        evidence: list[dict] | None = None,
        mode: str = "news",
    ) -> dict:
        evidence = evidence or []
        title = str(draft.get("title", "")).strip()
        lead = str(draft.get("lead", "")).strip()
        body = self._as_list(draft.get("body_paragraphs", []))
        background = self._as_list(draft.get("background_paragraphs", []))
        paragraphs = [lead, *body, *background]
        full_text = "\n\n".join(item for item in paragraphs if item)
        source_url = str(draft.get("source_url", "")).strip()
        alternate_titles = self._as_list(draft.get("alternate_titles", []))
        combined_text = f"{title}\n{full_text}"
        issues: list[AuditIssue] = []

        self._require(title, "title_missing", "缺少标题。", issues)
        self._require(lead, "lead_missing", "缺少导语/开头。", issues)
        self._require(body, "body_missing", "缺少正文详细内容。", issues)
        self._require(background, "background_missing", "缺少相关背景信息。", issues)
        self._require(source_url, "source_missing", "缺少原始新闻源链接。", issues)

        if source_url and not self._valid_url(source_url):
            issues.append(
                AuditIssue(
                    severity="error",
                    code="source_invalid",
                    message="新闻源链接不是有效的 HTTP/HTTPS URL。",
                    suggestion="填写可直接访问的原始报道、官方公告或记者原帖 URL。",
                )
            )

        if len([item for item in paragraphs if item]) < 3:
            issues.append(
                AuditIssue(
                    severity="error",
                    code="three_part_structure",
                    message="正文不足三段，未满足“开头 + 详细内容 + 背景”的三段式。",
                    suggestion="补齐独立的导语、主体和背景段落。",
                )
            )

        for term in SUBJECTIVE_TERMS:
            if term in combined_text:
                issues.append(
                    AuditIssue(
                        severity="error",
                        code="subjective_language",
                        message=f"出现主观表达“{term}”。",
                        suggestion="改为中性、可归因的事实表达。",
                    )
                )
        for term in CLICKBAIT_TERMS:
            if term in title:
                issues.append(
                    AuditIssue(
                        severity="warning",
                        code="clickbait_title",
                        message=f"标题疑似夸张或带节奏：“{term}”。",
                        suggestion="直接陈述最重要的事实。",
                    )
                )

        if "·" in full_text or "・" in full_text or "·" in title or "・" in title:
            issues.append(
                AuditIssue(
                    severity="error",
                    code="name_separator",
                    message="人名中可能使用了间隔号。",
                    suggestion="虎扑人名统一使用半角连字符“-”。",
                )
            )

        if TABLE_RE.search(full_text):
            issues.append(
                AuditIssue(
                    severity="error",
                    code="table_forbidden",
                    message="正文出现表格格式。",
                    suggestion="改为自然段表达。",
                )
            )
        if URL_RE.search(full_text):
            issues.append(
                AuditIssue(
                    severity="error",
                    code="body_url",
                    message="正文包含链接。",
                    suggestion="链接只保留在 source_url 或证据字段，不放入成稿正文。",
                )
            )

        latin = sorted(
            {
                token
                for token in LATIN_RE.findall(combined_text)
                if token.upper() not in ALLOWED_LATIN
            }
        )
        if latin:
            issues.append(
                AuditIssue(
                    severity="warning",
                    code="untranslated_english",
                    message=f"正文可能存在未翻译英文：{', '.join(latin[:8])}。",
                    suggestion="核对是否应改为虎扑通用中文译名或篮球术语。",
                )
            )

        if any(term in full_text for term in DYNAMIC_TERMS) and not evidence:
            issues.append(
                AuditIssue(
                    severity="error",
                    code="dynamic_data_unverified",
                    message="正文含动态数据或时间关系，但没有提供核验依据。",
                    suggestion="查询最新数据并在 evidence 中记录来源 URL 和截至日期。",
                )
            )
        elif NUMERIC_RE.search(full_text) and not evidence:
            issues.append(
                AuditIssue(
                    severity="warning",
                    code="numeric_claim_unverified",
                    message="正文包含数字，但 evidence 为空。",
                    suggestion="为比分、场均、合同等数字补充可追溯证据。",
                )
            )

        if full_text.count("“") != full_text.count("”"):
            issues.append(
                AuditIssue(
                    severity="error",
                    code="quote_unbalanced",
                    message="中文引号数量不匹配。",
                    suggestion="检查采访原话的起止引号。",
                )
            )
        if re.search(r"(?:湖人|勇士|凯尔特人|尼克斯|快船|热火|篮网)队", combined_text):
            issues.append(
                AuditIssue(
                    severity="warning",
                    code="team_short_name",
                    message="球队简称后使用了“队”。",
                    suggestion="简称写“湖人”，全名写“洛杉矶湖人队”。",
                )
            )
        if mode == "longform" and len(alternate_titles) != 10:
            issues.append(
                AuditIssue(
                    severity="error",
                    code="longform_title_count",
                    message=f"长文模式需要 10 个备选标题，当前为 {len(alternate_titles)} 个。",
                    suggestion="补齐或精简为恰好 10 个不夸大的中文标题。",
                )
            )

        deductions = sum(15 if issue.severity == "error" else 5 for issue in issues)
        score = max(0, 100 - deductions)
        report = AuditReport(
            passed=not any(issue.severity == "error" for issue in issues) and score >= 85,
            score=score,
            issues=issues,
            checked_at=datetime.now(),
        )
        return report.model_dump(mode="json")

    @staticmethod
    def _as_list(value: object) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if value:
            return [str(value).strip()]
        return []

    @staticmethod
    def _require(value: object, code: str, message: str, issues: list[AuditIssue]) -> None:
        if not value:
            issues.append(
                AuditIssue(
                    severity="error",
                    code=code,
                    message=message,
                    suggestion="按虎扑 SOP 补齐后重新审核。",
                )
            )

    @staticmethod
    def _valid_url(value: str) -> bool:
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
