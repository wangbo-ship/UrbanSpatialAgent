"""LangChain 工具封装 + Agent 执行 + 流式事件 + 无模型时的规则回退。"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from app.agent.models import get_model_by_id
from app.gis import tools as gis
from app.rag.retriever import search_knowledge


SYSTEM_PROMPT = """你是城市治理场景下的空间问答助手。
你必须通过工具完成空间计算，禁止编造坐标、数量、距离。
涉及规范口径、缓冲区建议、系统用法、FAQ 时，先调用 tool_search_knowledge 检索知识库，再依据检索片段回答并注明来源文件名。
可用图层：schools（学校）、hospitals（医院）、parks（公园）、events（投诉点/拟建点）。
地点可用名称或编号，例如：未来城校区、阳光相关名称、C2026001、P1。
回答用简洁中文，先给结论，再列关键数字；若工具失败要如实说明。
"""


@tool
def tool_resolve_place(name: str) -> str:
    """根据地名或编号查找坐标。"""
    return json.dumps(gis.resolve_place(name), ensure_ascii=False)


@tool
def tool_count_around_place(place_name: str, radius_m: float, layers: str) -> str:
    """统计某地点周边缓冲区内多个图层的要素数量。layers 用逗号分隔，如 schools,hospitals。"""
    layer_list = [x.strip() for x in layers.split(",") if x.strip()]
    result = gis.count_around_place(place_name, float(radius_m), layer_list)
    for block in result.get("results") or []:
        layer = block.get("layer")
        if layer == "schools":
            hits = [h for h in block.get("hits") or [] if h.get("category") == "school"]
            block["hits"] = hits
            block["count"] = len(hits)
        elif layer == "hospitals":
            hits = [h for h in block.get("hits") or [] if h.get("category") == "hospital"]
            block["hits"] = hits
            block["count"] = len(hits)
    if result.get("map_actions"):
        place = result.get("place") or {}
        result["map_actions"] = gis._map_actions_from_multi(
            place,
            result.get("buffer_geojson"),
            result.get("results") or [],
        )
    return json.dumps(result, ensure_ascii=False)


@tool
def tool_list_within_buffer(place_name: str, radius_m: float, layer_name: str) -> str:
    """列出某地点缓冲区内某图层的要素清单。"""
    result = gis.list_within_buffer(place_name, float(radius_m), layer_name)
    return json.dumps(result, ensure_ascii=False)


@tool
def tool_judge_within_buffer(target_name: str, layer_name: str, radius_m: float) -> str:
    """判断目标点是否落入图层任一点的缓冲范围内，并返回最近距离。"""
    result = gis.judge_within_buffer(target_name, layer_name, float(radius_m))
    return json.dumps(result, ensure_ascii=False)


@tool
def tool_search_knowledge(query: str, top_k: int = 3) -> str:
    """检索本地城市治理/缓冲规范/FAQ 知识库，返回相关原文片段。"""
    result = search_knowledge(query, top_k=int(top_k) if top_k else 3)
    return json.dumps(result, ensure_ascii=False)


TOOLS = [
    tool_resolve_place,
    tool_count_around_place,
    tool_list_within_buffer,
    tool_judge_within_buffer,
    tool_search_knowledge,
]
TOOL_MAP = {t.name: t for t in TOOLS}


def _extract_map_actions(tool_outputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for out in tool_outputs:
        data = out.get("result")
        if isinstance(data, dict) and data.get("map_actions"):
            actions = data["map_actions"]
    return actions


def _extract_knowledge_hits(tool_outputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for out in tool_outputs:
        if out.get("tool") != "tool_search_knowledge":
            continue
        data = out.get("result")
        if isinstance(data, dict):
            hits.extend(data.get("hits") or [])
    return hits


def _build_llm(model_cfg: dict[str, Any]) -> ChatOpenAI:
    key_env = model_cfg.get("api_key_env")
    api_key = os.getenv(key_env) if key_env else os.getenv("OLLAMA_API_KEY", "ollama")
    if key_env and not api_key:
        raise RuntimeError(f"缺少环境变量 {key_env}，请在 backend/.env 中配置")

    return ChatOpenAI(
        model=model_cfg["model"],
        api_key=api_key or "ollama",
        base_url=model_cfg["base_url"],
        temperature=0,
    )


def _summarize(result_obj: dict[str, Any]) -> dict[str, Any]:
    keys = ["found", "count", "within", "radius_m", "layer", "message", "query"]
    summary = {k: result_obj[k] for k in keys if k in result_obj}
    if "results" in result_obj:
        summary["results"] = [
            {"layer": r.get("layer"), "count": r.get("count")} for r in result_obj["results"]
        ]
    if "nearest" in result_obj and isinstance(result_obj["nearest"], dict):
        summary["nearest"] = {
            "name": result_obj["nearest"].get("name"),
            "distance_m": result_obj["nearest"].get("distance_m"),
        }
    if "hits" in result_obj:
        if result_obj.get("query") is not None:
            summary["hit_sources"] = [h.get("source") for h in result_obj.get("hits") or []]
        else:
            summary["hit_names"] = [h.get("name") for h in result_obj.get("hits") or []]
    return summary


def _invoke_tool(name: str, args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    tool = TOOL_MAP.get(name)
    if not tool:
        content = json.dumps({"error": f"未知工具: {name}"}, ensure_ascii=False)
        return content, {"error": f"未知工具: {name}"}
    content = tool.invoke(args)
    try:
        result_obj = json.loads(content)
    except json.JSONDecodeError:
        result_obj = {"raw": content}
    return content, result_obj


def run_with_llm(question: str, model_id: str | None = None) -> dict[str, Any]:
    model_cfg = get_model_by_id(model_id)
    llm = _build_llm(model_cfg).bind_tools(TOOLS)

    messages: list[Any] = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=question),
    ]
    trace: list[dict[str, Any]] = []
    tool_outputs: list[dict[str, Any]] = []

    for _ in range(6):
        ai: AIMessage = llm.invoke(messages)
        messages.append(ai)

        if not getattr(ai, "tool_calls", None):
            answer = ai.content if isinstance(ai.content, str) else str(ai.content)
            return {
                "answer": answer,
                "trace": trace,
                "map_actions": _extract_map_actions(tool_outputs),
                "knowledge_hits": _extract_knowledge_hits(tool_outputs),
                "model_id": model_cfg["id"],
                "mode": "llm",
            }

        for call in ai.tool_calls:
            name = call["name"]
            args = call.get("args") or {}
            content, result_obj = _invoke_tool(name, args)
            trace.append({"tool": name, "args": args, "result_summary": _summarize(result_obj)})
            tool_outputs.append({"tool": name, "result": result_obj})
            messages.append(
                ToolMessage(content=content, tool_call_id=call.get("id") or name)
            )

    return {
        "answer": "工具调用步数过多，已停止。请换一种问法或缩小问题范围。",
        "trace": trace,
        "map_actions": _extract_map_actions(tool_outputs),
        "knowledge_hits": _extract_knowledge_hits(tool_outputs),
        "model_id": model_cfg["id"],
        "mode": "llm",
    }


def run_rule_based(question: str) -> dict[str, Any]:
    """无可用 LLM 时的规则回退，保证 Demo 仍可演示 GIS / RAG。"""
    q = question.strip()
    trace: list[dict[str, Any]] = []
    radius_match = re.search(r"(\d+(?:\.\d+)?)\s*(公里|千米|km|米|m)", q, re.I)
    radius_m = 1000.0
    if radius_match:
        val = float(radius_match.group(1))
        unit = radius_match.group(2).lower()
        radius_m = val * 1000 if unit in {"公里", "千米", "km"} else val

    # RAG：规范 / FAQ / 知识库
    if any(k in q for k in ("规范", "知识库", "FAQ", "faq", "口径", "缓冲距离", "怎么用", "如何导出")):
        args = {"query": q, "top_k": 3}
        raw = TOOL_MAP["tool_search_knowledge"].invoke(args)
        result = json.loads(raw)
        trace.append(
            {"tool": "tool_search_knowledge", "args": args, "result_summary": _summarize(result)}
        )
        hits = result.get("hits") or []
        if not hits:
            answer = "知识库未检索到相关片段。（规则回退模式）"
        else:
            parts = []
            for h in hits:
                snippet = (h.get("text") or "").replace("\n", " ")
                if len(snippet) > 120:
                    snippet = snippet[:120] + "…"
                parts.append(f"《{h.get('source')}》：{snippet}")
            answer = "根据本地知识库（规则回退）：\n- " + "\n- ".join(parts)
        return {
            "answer": answer,
            "trace": trace,
            "map_actions": [],
            "knowledge_hits": hits,
            "model_id": "rule-fallback",
            "mode": "rule",
        }

    if "学校" in q and "医院" in q:
        place = "未来城校区"
        args = {"place_name": place, "radius_m": radius_m or 500, "layers": "schools,hospitals"}
        if "500" in q:
            args["radius_m"] = 500
        raw = TOOL_MAP["tool_count_around_place"].invoke(args)
        result = json.loads(raw)
        trace.append({"tool": "tool_count_around_place", "args": args, "result_summary": _summarize(result)})
        parts = []
        for block in result.get("results") or []:
            parts.append(f"{block.get('layer')} {block.get('count')} 个")
        answer = (
            f"以「{result.get('place', {}).get('name', place)}」为中心、"
            f"{args['radius_m']} 米缓冲："
            + "，".join(parts)
            + "。（当前为规则回退模式，未调用大模型）"
        )
        return {
            "answer": answer,
            "trace": trace,
            "map_actions": result.get("map_actions") or [],
            "knowledge_hits": [],
            "model_id": "rule-fallback",
            "mode": "rule",
        }

    if "公园" in q or "投诉" in q or "C2026001" in q:
        place = "C2026001"
        args = {"place_name": place, "radius_m": radius_m or 1000, "layer_name": "parks"}
        raw = TOOL_MAP["tool_list_within_buffer"].invoke(args)
        result = json.loads(raw)
        trace.append({"tool": "tool_list_within_buffer", "args": args, "result_summary": _summarize(result)})
        names = [h.get("name") for h in result.get("hits") or []]
        answer = (
            f"投诉点 {place} 周边 {args['radius_m']} 米内公园 {result.get('count', 0)} 个："
            + ("、".join(n for n in names if n) or "无")
            + "。（规则回退模式）"
        )
        return {
            "answer": answer,
            "trace": trace,
            "map_actions": result.get("map_actions") or [],
            "knowledge_hits": [],
            "model_id": "rule-fallback",
            "mode": "rule",
        }

    if "拟建" in q or "P1" in q or ("学校" in q and "300" in q):
        args = {"target_name": "P1", "layer_name": "schools", "radius_m": 300}
        raw = TOOL_MAP["tool_judge_within_buffer"].invoke(args)
        result = json.loads(raw)
        trace.append({"tool": "tool_judge_within_buffer", "args": args, "result_summary": _summarize(result)})
        nearest = result.get("nearest") or {}
        answer = (
            f"拟建点 P1 {'位于' if result.get('within') else '不在'}任一学校 300 米缓冲区内。"
            f"最近学校：{nearest.get('name')}，距离 {nearest.get('distance_m')} 米。（规则回退模式）"
        )
        return {
            "answer": answer,
            "trace": trace,
            "map_actions": result.get("map_actions") or [],
            "knowledge_hits": [],
            "model_id": "rule-fallback",
            "mode": "rule",
        }

    return {
        "answer": (
            "当前无法调用大模型，且问题未匹配内置 Demo 规则。"
            "请先启动 Ollama 或配置 API Key；也可点击左侧 Demo 剧本试用。"
        ),
        "trace": [],
        "map_actions": [],
        "knowledge_hits": [],
        "model_id": "rule-fallback",
        "mode": "rule",
    }


def run_agent(question: str, model_id: str | None = None, force_rule: bool = False) -> dict[str, Any]:
    if force_rule:
        return run_rule_based(question)
    try:
        return run_with_llm(question, model_id=model_id)
    except Exception as e:
        fallback = run_rule_based(question)
        fallback["answer"] = (
            f"大模型调用失败（{e}），已自动切换规则回退：\n\n" + fallback["answer"]
        )
        fallback["llm_error"] = str(e)
        return fallback


def _chunk_text(text: str, size: int = 24) -> Iterator[str]:
    text = text or ""
    for i in range(0, len(text), size):
        yield text[i : i + size]


def iter_agent_events(
    question: str,
    model_id: str | None = None,
    force_rule: bool = False,
) -> Iterator[dict[str, Any]]:
    """SSE 用事件流：status / tool / token / final / error。"""
    yield {"type": "status", "message": "开始分析…"}

    if force_rule:
        result = run_rule_based(question)
        for t in result.get("trace") or []:
            yield {"type": "tool", "tool": t.get("tool"), "args": t.get("args"), "result_summary": t.get("result_summary")}
        for piece in _chunk_text(result.get("answer") or ""):
            yield {"type": "token", "content": piece}
        yield {"type": "final", "data": result}
        return

    try:
        model_cfg = get_model_by_id(model_id)
        llm = _build_llm(model_cfg).bind_tools(TOOLS)
        messages: list[Any] = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=question),
        ]
        trace: list[dict[str, Any]] = []
        tool_outputs: list[dict[str, Any]] = []

        for _ in range(6):
            yield {"type": "status", "message": "模型思考中…"}
            ai: AIMessage = llm.invoke(messages)
            messages.append(ai)

            if not getattr(ai, "tool_calls", None):
                answer = ai.content if isinstance(ai.content, str) else str(ai.content)
                for piece in _chunk_text(answer):
                    yield {"type": "token", "content": piece}
                result = {
                    "answer": answer,
                    "trace": trace,
                    "map_actions": _extract_map_actions(tool_outputs),
                    "knowledge_hits": _extract_knowledge_hits(tool_outputs),
                    "model_id": model_cfg["id"],
                    "mode": "llm",
                }
                yield {"type": "final", "data": result}
                return

            for call in ai.tool_calls:
                name = call["name"]
                args = call.get("args") or {}
                yield {"type": "status", "message": f"调用工具 {name}…"}
                content, result_obj = _invoke_tool(name, args)
                item = {"tool": name, "args": args, "result_summary": _summarize(result_obj)}
                trace.append(item)
                tool_outputs.append({"tool": name, "result": result_obj})
                yield {"type": "tool", **item}
                messages.append(
                    ToolMessage(content=content, tool_call_id=call.get("id") or name)
                )

        result = {
            "answer": "工具调用步数过多，已停止。请换一种问法或缩小问题范围。",
            "trace": trace,
            "map_actions": _extract_map_actions(tool_outputs),
            "knowledge_hits": _extract_knowledge_hits(tool_outputs),
            "model_id": model_cfg["id"],
            "mode": "llm",
        }
        for piece in _chunk_text(result["answer"]):
            yield {"type": "token", "content": piece}
        yield {"type": "final", "data": result}
    except Exception as e:
        yield {"type": "status", "message": f"大模型失败，规则回退（{e}）"}
        result = run_rule_based(question)
        result["answer"] = f"大模型调用失败（{e}），已自动切换规则回退：\n\n" + result["answer"]
        result["llm_error"] = str(e)
        for t in result.get("trace") or []:
            yield {"type": "tool", "tool": t.get("tool"), "args": t.get("args"), "result_summary": t.get("result_summary")}
        for piece in _chunk_text(result.get("answer") or ""):
            yield {"type": "token", "content": piece}
        yield {"type": "final", "data": result}
