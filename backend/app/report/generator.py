"""研判报告：把一次问答结果整理为 Markdown，供下载。"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def build_report_markdown(
    question: str,
    answer: str,
    *,
    trace: list[dict[str, Any]] | None = None,
    mode: str | None = None,
    model_id: str | None = None,
    knowledge_hits: list[dict[str, Any]] | None = None,
    campus_name: str = "中国地质大学（武汉）未来城校区",
) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines: list[str] = [
        "# 城市治理空间研判报告",
        "",
        f"- **生成时间**：{now}",
        f"- **研究区域**：{campus_name}",
        f"- **运行模式**：{mode or '-'}",
        f"- **模型**：{model_id or '-'}",
        "",
        "## 1. 问题背景",
        "",
        question.strip() or "（未提供问题）",
        "",
        "## 2. 分析结论",
        "",
        (answer or "").strip() or "（无结论）",
        "",
    ]

    if trace:
        lines.extend(["## 3. 工具调用轨迹", ""])
        for i, t in enumerate(trace, 1):
            tool = t.get("tool", "?")
            summary = t.get("result_summary") or t.get("args") or {}
            lines.append(f"{i}. `{tool}` — `{summary}`")
        lines.append("")
    else:
        lines.extend(["## 3. 工具调用轨迹", "", "（本次无工具轨迹）", ""])

    if knowledge_hits:
        lines.extend(["## 4. 知识库引用", ""])
        for h in knowledge_hits:
            src = h.get("source", "")
            text = (h.get("text") or "").strip().replace("\n", " ")
            if len(text) > 180:
                text = text[:180] + "…"
            lines.append(f"- **{src}**（score={h.get('score', '-')}）：{text}")
        lines.append("")
    else:
        lines.extend(
            [
                "## 4. 知识库引用",
                "",
                "（本次未附带检索片段；若问题涉及规范口径，可在对话中询问「缓冲规范/FAQ」以触发 RAG。）",
                "",
            ]
        )

    lines.extend(
        [
            "## 5. 说明",
            "",
            "- 空间数量与距离由 GIS 工具计算，不由大模型编造。",
            "- 知识库内容为演示样例，正式业务请替换为权威文件。",
            "",
        ]
    )
    return "\n".join(lines)
