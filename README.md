# UrbanSpatialAgent

城市治理 · 空间问答与研判助手（个人项目）

## 目录

- `frontend/` — Vue 3 + Vite + Leaflet（对话流式 + 地图 + 模型切换 + 报告导出）
- `backend/` — FastAPI + LangChain Agent + GIS + RAG + 报告
- `data/` — GeoJSON、配置、模型列表、`knowledge/` 知识库
- `报告文档/` — 设计文档与接口文档

## 能力概览

- 自然语言空间问答（Agent + GIS）
- 本地 RAG（`data/knowledge/`）
- SSE 流式对话
- 研判报告 Markdown 导出
- Demo D1–D4（含规范检索）

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
