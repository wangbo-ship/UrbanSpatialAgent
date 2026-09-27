"""多模型配置加载。"""

from __future__ import annotations

import json
import os
from typing import Any

from app.config import settings


def load_models_config() -> dict[str, Any]:
    path = settings.data_dir / "models.json"
    return json.loads(path.read_text(encoding="utf-8"))


def list_models_for_api() -> dict[str, Any]:
    cfg = load_models_config()
    models = []
    for m in cfg.get("models", []):
        key_env = m.get("api_key_env")
        ready = True
        if key_env:
            ready = bool(os.getenv(key_env))
        elif m.get("provider") == "ollama":
            ready = True  # 前端/后端调用时再探测
        models.append(
            {
                "id": m["id"],
                "name": m["name"],
                "provider": m["provider"],
                "free": m.get("free", False),
                "note": m.get("note", ""),
                "ready": ready,
                "needs_key": bool(key_env),
                "api_key_env": key_env,
            }
        )
    return {
        "default_model_id": cfg.get("default_model_id"),
        "models": models,
    }


def get_model_by_id(model_id: str | None) -> dict[str, Any]:
    cfg = load_models_config()
    mid = model_id or cfg.get("default_model_id")
    chosen: dict[str, Any] | None = None
    for m in cfg.get("models", []):
        if m["id"] == mid:
            chosen = dict(m)
            break
    if chosen is None:
        if cfg.get("models"):
            chosen = dict(cfg["models"][0])
        else:
            raise ValueError("models.json 中没有可用模型")

    # 豆包接入点 ID 因人而异：可用环境变量覆盖 models.json 里的占位 ep-xxxxxxxx
    if chosen.get("id") == "doubao-ark":
        ep = os.getenv("DOUBAO_ENDPOINT_ID") or os.getenv("ARK_ENDPOINT_ID")
        if ep:
            chosen["model"] = ep
    return chosen
