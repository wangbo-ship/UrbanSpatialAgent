"""简易 RAG：本地 Markdown 切分 + 关键词打分检索（不依赖向量库/嵌入 API）。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.config import settings

_CHUNK_SIZE = 280
_CHUNK_OVERLAP = 40


def _knowledge_dir() -> Path:
    return settings.data_dir / "knowledge"


def _tokenize_tokens(text: str) -> set[str]:
    """中文按连续汉字切词片段 + 英文单词，用于朴素重合打分。"""
    parts = re.findall(r"[\u4e00-\u9fff]{2,}|\w+", (text or "").lower())
    tokens: set[str] = set()
    for p in parts:
        tokens.add(p)
        if re.fullmatch(r"[\u4e00-\u9fff]+", p) and len(p) >= 3:
            for i in range(len(p) - 1):
                tokens.add(p[i : i + 2])
    return tokens


def _chunk_text(text: str, source: str) -> list[dict[str, Any]]:
    text = re.sub(r"\r\n?", "\n", text).strip()
    if not text:
        return []
    # 优先按二级标题切开
    sections = re.split(r"\n(?=##\s)", text)
    chunks: list[dict[str, Any]] = []
    idx = 0
    for sec in sections:
        sec = sec.strip()
        if not sec:
            continue
        if len(sec) <= _CHUNK_SIZE:
            chunks.append({"id": f"{source}#{idx}", "source": source, "text": sec})
            idx += 1
            continue
        start = 0
        while start < len(sec):
            end = min(len(sec), start + _CHUNK_SIZE)
            piece = sec[start:end].strip()
            if piece:
                chunks.append({"id": f"{source}#{idx}", "source": source, "text": piece})
                idx += 1
            if end >= len(sec):
                break
            start = max(end - _CHUNK_OVERLAP, start + 1)
    return chunks


_CORPUS: list[dict[str, Any]] | None = None


def load_corpus(force: bool = False) -> list[dict[str, Any]]:
    global _CORPUS
    if _CORPUS is not None and not force:
        return _CORPUS
    root = _knowledge_dir()
    corpus: list[dict[str, Any]] = []
    if root.exists():
        for path in sorted(root.glob("*.md")):
            corpus.extend(_chunk_text(path.read_text(encoding="utf-8"), path.name))
    _CORPUS = corpus
    return corpus


def search_knowledge(query: str, top_k: int = 3) -> dict[str, Any]:
    q = (query or "").strip()
    corpus = load_corpus()
    if not q:
        return {"query": q, "hits": [], "message": "查询为空"}
    if not corpus:
        return {"query": q, "hits": [], "message": "知识库为空，请检查 data/knowledge/"}

    q_tokens = _tokenize_tokens(q)
    scored: list[tuple[float, dict[str, Any]]] = []
    for chunk in corpus:
        c_tokens = _tokenize_tokens(chunk["text"])
        if not c_tokens:
            continue
        overlap = q_tokens & c_tokens
        if not overlap:
            continue
        score = len(overlap) / (len(q_tokens) ** 0.5 + 1e-6)
        # 标题命中加权
        if chunk["text"].lstrip().startswith("#") and overlap:
            score *= 1.2
        scored.append((score, chunk))

    scored.sort(key=lambda x: x[0], reverse=True)
    hits = []
    for score, chunk in scored[: max(1, top_k)]:
        hits.append(
            {
                "id": chunk["id"],
                "source": chunk["source"],
                "score": round(float(score), 4),
                "text": chunk["text"],
            }
        )
    return {
        "query": q,
        "hits": hits,
        "count": len(hits),
        "message": "ok" if hits else "未检索到相关片段",
    }


def list_knowledge_docs() -> dict[str, Any]:
    root = _knowledge_dir()
    if not root.exists():
        return {"docs": []}
    docs = []
    for path in sorted(root.glob("*.md")):
        docs.append({"name": path.name, "chars": path.stat().st_size})
    return {"docs": docs, "chunk_count": len(load_corpus())}
