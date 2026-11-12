from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .agent import HupuNbaAgent
from .models import GenerateRequest, WorkflowMode
from .tools import ContentAuditor


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hupu-nba-agent",
        description="将英文 NBA 新闻源转换为虎扑规范中文稿。",
    )
    parser.add_argument(
        "source",
        nargs="?",
        help="新闻 URL、X 帖子 URL 或正文；省略时从 stdin 读取",
    )
    parser.add_argument(
        "--mode",
        choices=[mode.value for mode in WorkflowMode],
        default=WorkflowMode.NEWS.value,
    )
    parser.add_argument("--editor-note", default="", help="本次编辑补充要求")
    parser.add_argument("--no-web-search", action="store_true", help="禁用 OpenAI 网页搜索")
    parser.add_argument("--json", action="store_true", help="输出完整 JSON")
    parser.add_argument("--audit-file", type=Path, help="只审核一个 NewsDraft JSON 文件")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.audit_file:
        payload = json.loads(args.audit_file.read_text(encoding="utf-8"))
        draft = payload.get("draft", payload)
        evidence = payload.get("evidence", [])
        report = ContentAuditor().audit(draft, evidence, str(payload.get("mode", "news")))
        print(json.dumps(report, ensure_ascii=False, indent=2))
        raise SystemExit(0 if report["passed"] else 2)

    source = args.source or sys.stdin.read()
    if not source.strip():
        raise SystemExit("请提供新闻 URL、X 帖子 URL 或正文。")
    request = GenerateRequest(
        source=source,
        mode=WorkflowMode(args.mode),
        editor_note=args.editor_note,
        use_web_search=not args.no_web_search,
    )
    response = HupuNbaAgent().run(request)
    if args.json:
        print(response.model_dump_json(indent=2))
        return
    draft = response.result.draft
    print(draft.title)
    print()
    print(draft.full_text)
    print()
    print(f"来源：{draft.source_name} {draft.source_url}")
    audit_status = "通过" if response.result.audit.passed else "未通过"
    print(f"审核：{response.result.audit.score} 分 / {audit_status}")
    if draft.alternate_titles:
        print("\n备选标题：")
        for index, title in enumerate(draft.alternate_titles, 1):
            print(f"{index}. {title}")


if __name__ == "__main__":
    main()
