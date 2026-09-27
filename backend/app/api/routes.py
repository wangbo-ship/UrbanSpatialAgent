import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.agent.models import list_models_for_api
from app.agent.service import run_agent
from app.config import settings

router = APIRouter(prefix="/api")


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, description="用户问题")
    model_id: str | None = Field(None, description="模型 id，见 /api/models")
    force_rule: bool = Field(False, description="强制使用规则回退（调试用）")


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
