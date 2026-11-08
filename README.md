# UrbanSpatialAgent

城市治理 · 空间问答与研判助手（个人项目）

## 目录

- `frontend/` — Vue 3 + Vite + **Cesium / Three.js 双视图**（对话流式 + 落图 + 报告导出）
- `backend/` — FastAPI + LangChain Agent + GIS + RAG + 报告
- `data/` — GeoJSON、配置、模型列表、`knowledge/` 知识库
- `报告文档/` — 设计文档与接口文档

## 能力概览

- 自然语言空间问答（Agent + GIS）
- 本地 RAG（`data/knowledge/`）
- SSE 流式对话
- 研判报告 Markdown 导出
- Demo D1–D4（含规范检索）
- **右下角切换**：Three 柱体演示 ↔ Cesium 3D GIS（同一套 `map_actions`）

### Cesium 可选增强

复制 `frontend/.env.example` 为 `frontend/.env`，填写免费 [Cesium Ion Token](https://cesium.com/ion/tokens)：

```env
VITE_CESIUM_ION_TOKEN=你的token
```

有 Token 时启用世界地形 + OSM Buildings；无 Token 仍可用地球 + 公开影像叠加分析结果。

**默认先开 Three 柱体视图**（保证能进页）；再点右下角切到 Cesium。  
Cesium 通过 `index.html` 全局脚本加载（`/cesium/Cesium.js`），不要用 Vite 直接 `import 'cesium'`，否则易白屏。

常见问题：

- `InvalidStateError: source image could not be decoded`：Ion/瓦片失败 → 已关默认 Ion 底图并做影像回退；可开 VPN 或配 Ion Token。  
- 白屏 / `mersenne-twister` export：请硬刷新；确认 `index.html` 已引入 `/cesium/Cesium.js`。  
- 前端若提示端口占用，以终端显示的 `localhost:5174` 等为准。

## 本地启动

### 后端

```powershell
cd backend
.\.venv\Scripts\uvicorn.exe app.main:app --reload --port 8000
```

（若尚未建虚拟环境 / 装依赖：`python -m venv .venv` 后 `pip install -r requirements.txt`）

### 前端

```powershell
cd frontend
npm install
npm run dev
```

浏览器打开 http://localhost:5173

## 模型（可选，推荐先 Ollama）

前端右上角可切换模型。未装模型或 Key 时，系统会**规则回退**，Demo 仍可跑通 GIS。

### 方案 A：Ollama 本地免费（推荐）

1. 安装 https://ollama.com  
2. 终端执行：`ollama pull qwen2.5:7b`（或 `ollama pull llama3.2`）  
3. 保持 Ollama 运行，前端选择对应模型即可  

### 方案 B：云端 API Key

复制 `backend/.env.example` 为 `backend/.env`，填写例如：

```env
DEEPSEEK_API_KEY=sk-xxxx
# 或
SILICONFLOW_API_KEY=sk-xxxx
```

模型说明见 `data/models.json`。
