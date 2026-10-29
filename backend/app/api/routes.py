import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.agent.models import list_models_for_api
from app.agent.service import iter_agent_events, run_agent
from app.config import settings
from app.rag.retriever import list_knowledge_docs, search_knowledge
from app.report.generator import build_report_markdown

router = APIRouter(prefix="/api")


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, description="用户问题")
    model_id: str | None = Field(None, description="模型 id，见 /api/models")
    force_rule: bool = Field(False, description="强制使用规则回退（调试用）")


class ReportRequest(BaseModel):
    question: str = Field(..., min_length=1)
    answer: str = Field(..., min_length=1)
    trace: list[dict] = Field(default_factory=list)
    mode: str | None = None
    model_id: str | None = None
    knowledge_hits: list[dict] = Field(default_factory=list)
    campus_name: str | None = None


@router.get("/health")
def health():
    return {"status": "ok", "app": settings.app_name}


@router.get("/config")
def get_config():
    path = settings.data_dir / "config.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="config.json not found")
    return json.loads(path.read_text(encoding="utf-8"))


@router.get("/demos")
def get_demos():
    path = settings.data_dir / "demos.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="demos.json not found")
    return json.loads(path.read_text(encoding="utf-8"))


@router.get("/models")
def get_models():
    return list_models_for_api()


@router.post("/chat")
def chat(body: ChatRequest):
    try:
        result = run_agent(
            body.question.strip(),
            model_id=body.model_id,
            force_rule=body.force_rule,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/chat/stream")
def chat_stream(body: ChatRequest):
    """SSE：逐条推送 status / tool / token / final。"""

    def event_gen():
        try:
            for ev in iter_agent_events(
                body.question.strip(),
                model_id=body.model_id,
                force_rule=body.force_rule,
            ):
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        except Exception as e:
            err = {"type": "error", "message": str(e)}
            yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/knowledge")
def knowledge_list():
    return list_knowledge_docs()


@router.get("/knowledge/search")
def knowledge_search(
    q: str = Query(..., min_length=1, description="检索问题"),
    top_k: int = Query(3, ge=1, le=10),
):
    return search_knowledge(q, top_k=top_k)


@router.post("/report")
def create_report(body: ReportRequest):
    cfg_path = settings.data_dir / "config.json"
    campus = body.campus_name
    if not campus and cfg_path.exists():
        campus = json.loads(cfg_path.read_text(encoding="utf-8")).get("campus_name")

    md = build_report_markdown(
        body.question,
        body.answer,
        trace=body.trace,
        mode=body.mode,
        model_id=body.model_id,
        knowledge_hits=body.knowledge_hits,
        campus_name=campus or "中国地质大学（武汉）未来城校区",
    )
    return {
        "filename": "研判报告.md",
        "markdown": md,
        "media_type": "text/markdown; charset=utf-8",
    }


@router.get("/layers/{layer_name}")
def get_layer(layer_name: str):
    safe = Path(layer_name).name
    path = settings.data_dir / "layers" / f"{safe}.geojson"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"layer not found: {safe}")
    return FileResponse(path, media_type="application/geo+json")


@router.get("/layers")
def list_layers():
    layers_dir = settings.data_dir / "layers"
    if not layers_dir.exists():
        return {"layers": []}
    names = sorted(p.stem for p in layers_dir.glob("*.geojson"))
    return {"layers": names}
