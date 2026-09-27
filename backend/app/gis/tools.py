"""GIS 工具：基于样例 GeoJSON 做缓冲、相交统计、距离判定。数字由本模块计算。"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from pyproj import Transformer
from shapely.geometry import Point, mapping, shape
from shapely.ops import transform

from app.config import settings

# 经纬度 <-> 近似米制投影（Web Mercator），仅用于样例尺度缓冲
_TO_M = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
_TO_LL = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)


def _layers_dir() -> Path:
    return settings.data_dir / "layers"


def _load_layer(layer_name: str) -> dict[str, Any]:
    safe = Path(layer_name).name
    path = _layers_dir() / f"{safe}.geojson"
    if not path.exists():
        raise FileNotFoundError(f"图层不存在: {safe}")
    return json.loads(path.read_text(encoding="utf-8"))


def _load_config() -> dict[str, Any]:
    path = settings.data_dir / "config.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _project_to_m(geom):
    return transform(lambda x, y, z=None: _TO_M.transform(x, y), geom)


def _project_to_ll(geom):
    return transform(lambda x, y, z=None: _TO_LL.transform(x, y), geom)


def _haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def resolve_place(name: str) -> dict[str, Any]:
    """按名称在各图层 properties.name / id 中查找，找不到则尝试校区中心别名。"""
    needle = (name or "").strip()
    cfg = _load_config()
    aliases = {
        "未来城校区",
        "地大未来城",
        "中国地质大学（武汉）未来城校区",
        "中国地质大学未来城校区",
        cfg.get("campus_name", ""),
    }
    if needle in aliases or "未来城" in needle or "地大" in needle:
        lon, lat = cfg["campus_center"]
        return {
            "found": True,
            "name": cfg.get("campus_name", needle),
            "lon": lon,
            "lat": lat,
            "source": "config.campus_center",
        }

    for layer_path in sorted(_layers_dir().glob("*.geojson")):
        data = json.loads(layer_path.read_text(encoding="utf-8"))
        for feat in data.get("features", []):
            props = feat.get("properties") or {}
            candidates = [
                str(props.get("name", "")),
                str(props.get("id", "")),
            ]
            if needle and any(needle == c or needle in c for c in candidates if c):
                geom = feat.get("geometry") or {}
                if geom.get("type") == "Point":
                    lon, lat = geom["coordinates"][:2]
                    return {
                        "found": True,
                        "name": props.get("name") or props.get("id") or needle,
                        "lon": lon,
                        "lat": lat,
                        "source": layer_path.stem,
                        "properties": props,
                    }
    return {"found": False, "name": needle, "message": f"未找到地点: {needle}"}


def buffer_and_count(
    lon: float,
    lat: float,
    radius_m: float,
    layer_name: str,
    category: str | None = None,
) -> dict[str, Any]:
    """以点为中心做缓冲，统计图层中落入的点，并返回缓冲 GeoJSON 与命中要素。"""
    layer = _load_layer(layer_name)
    center = Point(lon, lat)
    center_m = _project_to_m(center)
    buf_m = center_m.buffer(float(radius_m))
    buf_ll = _project_to_ll(buf_m)

    hits: list[dict[str, Any]] = []
    for feat in layer.get("features", []):
        props = feat.get("properties") or {}
        if category and props.get("category") != category:
            continue
        geom = feat.get("geometry")
        if not geom:
            continue
        g = shape(geom)
        g_m = _project_to_m(g)
        if buf_m.intersects(g_m):
            item = {
                "name": props.get("name") or props.get("id"),
                "category": props.get("category"),
                "properties": props,
            }
            if g.geom_type == "Point":
                item["lon"], item["lat"] = g.x, g.y
                item["distance_m"] = round(_haversine_m(lon, lat, g.x, g.y), 1)
            hits.append(item)

    return {
        "center": {"lon": lon, "lat": lat},
        "radius_m": radius_m,
        "layer": layer_name,
        "category": category,
        "count": len(hits),
        "hits": hits,
        "buffer_geojson": mapping(buf_ll),
    }


def count_around_place(
    place_name: str,
    radius_m: float,
    layer_names: list[str],
) -> dict[str, Any]:
    """定位地点后，对多个图层分别缓冲计数。"""
    place = resolve_place(place_name)
    if not place.get("found"):
        return place

    results = []
    buffers = []
    for layer in layer_names:
        try:
            one = buffer_and_count(place["lon"], place["lat"], radius_m, layer)
            results.append(
                {
                    "layer": layer,
                    "count": one["count"],
                    "hits": one["hits"],
                }
            )
            buffers.append(one["buffer_geojson"])
        except FileNotFoundError as e:
            results.append({"layer": layer, "error": str(e)})

    return {
        "found": True,
        "place": place,
        "radius_m": radius_m,
        "results": results,
        "buffer_geojson": buffers[0] if buffers else None,
        "map_actions": _map_actions_from_multi(place, buffers[0] if buffers else None, results),
    }


def _map_actions_from_multi(place: dict, buffer_geojson, results: list) -> list[dict]:
    actions: list[dict] = [
        {
            "type": "setView",
            "lat": place["lat"],
            "lon": place["lon"],
            "zoom": 15,
        }
    ]
    if buffer_geojson:
        actions.append({"type": "addGeoJSON", "id": "buffer", "geojson": {
            "type": "Feature",
            "properties": {"role": "buffer"},
            "geometry": buffer_geojson,
        }, "style": {"color": "#2563eb", "weight": 2, "fillOpacity": 0.12}})

    features = []
    for block in results:
        for h in block.get("hits") or []:
            if "lon" in h and "lat" in h:
                features.append({
                    "type": "Feature",
                    "properties": {"name": h.get("name"), "category": h.get("category"), "layer": block.get("layer")},
                    "geometry": {"type": "Point", "coordinates": [h["lon"], h["lat"]]},
                })
    if features:
        actions.append({
            "type": "addGeoJSON",
            "id": "hits",
            "geojson": {"type": "FeatureCollection", "features": features},
            "style": {"color": "#0f766e", "radius": 8},
        })
    return actions


def list_within_buffer(
    place_name: str,
    radius_m: float,
    layer_name: str,
) -> dict[str, Any]:
    place = resolve_place(place_name)
    if not place.get("found"):
        # 尝试当事件 id
        place = resolve_place(place_name)
        if not place.get("found"):
            return place

    one = buffer_and_count(place["lon"], place["lat"], radius_m, layer_name)
    return {
        "found": True,
        "place": place,
        "radius_m": radius_m,
        "layer": layer_name,
        "count": one["count"],
        "hits": one["hits"],
        "buffer_geojson": one["buffer_geojson"],
        "map_actions": _map_actions_from_multi(
            place,
            one["buffer_geojson"],
            [{"layer": layer_name, "hits": one["hits"]}],
        ),
    }


def judge_within_buffer(
    target_name: str,
    layer_name: str,
    radius_m: float,
) -> dict[str, Any]:
    """判断目标点是否落入图层任一点的 radius_m 缓冲内，并给最近距离。"""
    target = resolve_place(target_name)
    if not target.get("found"):
        return target

    layer = _load_layer(layer_name)
    nearest = None
    inside_any = False
    related = []

    for feat in layer.get("features", []):
        props = feat.get("properties") or {}
        geom = feat.get("geometry") or {}
        if geom.get("type") != "Point":
            continue
        lon, lat = geom["coordinates"][:2]
        dist = _haversine_m(target["lon"], target["lat"], lon, lat)
        item = {
            "name": props.get("name"),
            "category": props.get("category"),
            "distance_m": round(dist, 1),
            "within": dist <= radius_m,
            "lon": lon,
            "lat": lat,
        }
        related.append(item)
        if item["within"]:
            inside_any = True
        if nearest is None or dist < nearest["distance_m"]:
            nearest = item

    related.sort(key=lambda x: x["distance_m"])
    buffer_around_nearest = None
    if nearest:
        buffer_around_nearest = buffer_and_count(
            nearest["lon"], nearest["lat"], radius_m, layer_name
        )["buffer_geojson"]

    map_actions = [
        {"type": "setView", "lat": target["lat"], "lon": target["lon"], "zoom": 15},
        {
            "type": "addGeoJSON",
            "id": "target",
            "geojson": {
                "type": "Feature",
                "properties": {"name": target.get("name"), "role": "target"},
                "geometry": {"type": "Point", "coordinates": [target["lon"], target["lat"]]},
            },
            "style": {"color": "#b91c1c", "radius": 9},
        },
    ]
    if buffer_around_nearest and nearest:
        map_actions.append({
            "type": "addGeoJSON",
            "id": "school_buffer",
            "geojson": {
                "type": "Feature",
                "properties": {"role": "buffer", "around": nearest.get("name")},
                "geometry": buffer_around_nearest,
            },
            "style": {"color": "#ca8a04", "weight": 2, "fillOpacity": 0.1},
        })

    return {
        "found": True,
        "target": target,
        "layer": layer_name,
        "radius_m": radius_m,
        "within": inside_any,
        "nearest": nearest,
        "related": related[:5],
        "map_actions": map_actions,
    }
