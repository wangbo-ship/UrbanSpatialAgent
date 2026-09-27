<template>
  <div class="layout">
    <header class="topbar">
      <div class="brand">
        <h1>空间问答与研判助手</h1>
        <p>{{ campusName }}</p>
      </div>
      <div class="header-right">
        <label class="model-select">
          <span>模型</span>
          <select v-model="selectedModelId">
            <option v-for="m in models" :key="m.id" :value="m.id">
              {{ m.name }}{{ m.free ? ' · 免费' : '' }}
            </option>
          </select>
        </label>
        <div class="status" :class="{ ok: apiOk, err: apiOk === false }">
          {{ apiStatusText }}
        </div>
      </div>
    </header>

    <main class="main">
      <aside class="panel chat-panel">
        <div class="panel-head">
          <h2>对话</h2>
          <p class="hint">可切换模型；未配置模型时会自动规则回退，Demo 仍可演示。</p>
        </div>

        <div class="demos-row">
          <button
            v-for="d in demos"
            :key="d.id"
            type="button"
            class="demo-btn"
            :disabled="sending"
            @click="runDemo(d)"
          >
            {{ d.title }}
          </button>
        </div>

        <div ref="msgBox" class="messages">
          <div v-if="messages.length === 0" class="empty">
            试试左侧 Demo，或直接输入空间问题。
          </div>
          <div
            v-for="(msg, idx) in messages"
            :key="idx"
            class="msg"
            :class="msg.role"
          >
            <div class="msg-role">{{ msg.role === 'user' ? '你' : '助手' }}</div>
            <div class="msg-body">{{ msg.content }}</div>
            <div v-if="msg.meta" class="msg-meta">{{ msg.meta }}</div>
            <ul v-if="msg.trace && msg.trace.length" class="trace">
              <li v-for="(t, i) in msg.trace" :key="i">
                <code>{{ t.tool }}</code>
                <span>{{ formatTrace(t) }}</span>
              </li>
            </ul>
          </div>
        </div>

        <form class="composer" @submit.prevent="sendQuestion">
          <textarea
            v-model="input"
            rows="3"
            placeholder="例如：未来城校区周边 500 米内有多少所学校和医院？"
            :disabled="sending"
            @keydown.enter.exact.prevent="sendQuestion"
          />
          <button type="submit" :disabled="sending || !input.trim()">
            {{ sending ? '分析中…' : '发送' }}
          </button>
        </form>
      </aside>

      <section class="map-wrap">
        <div ref="mapEl" class="map"></div>
      </section>
    </main>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

const mapEl = ref(null)
const msgBox = ref(null)
const campusName = ref('中国地质大学（武汉）未来城校区')
const demos = ref([])
const models = ref([])
const selectedModelId = ref('')
const apiOk = ref(null)
const input = ref('')
const sending = ref(false)
const messages = ref([])

let map = null
let baseLayers = []
let resultLayers = []
let campusCenter = [30.458, 114.615]

const apiStatusText = computed(() => {
  if (apiOk.value === null) return '检测后端…'
  if (apiOk.value) return '后端已连接'
  return '后端未连接'
})

async function fetchJson(url, options) {
  const res = await fetch(url, options)
  if (!res.ok) {
    let detail = String(res.status)
    try {
      const err = await res.json()
      detail = err.detail || detail
    } catch {
      /* ignore */
    }
    throw new Error(detail)
  }
  return res.json()
}

function formatTrace(t) {
  try {
    return JSON.stringify(t.result_summary || t.args || {})
  } catch {
    return ''
  }
}

function clearResultLayers() {
  for (const layer of resultLayers) {
    map.removeLayer(layer)
  }
  resultLayers = []
}

function applyMapActions(actions) {
  if (!map || !Array.isArray(actions)) return
  clearResultLayers()
  for (const action of actions) {
    if (action.type === 'setView') {
      map.setView([action.lat, action.lon], action.zoom || 15)
    } else if (action.type === 'addGeoJSON') {
      const style = action.style || {}
      const layer = L.geoJSON(action.geojson, {
        style() {
          return {
            color: style.color || '#2563eb',
            weight: style.weight || 2,
            fillColor: style.fillColor || style.color || '#3b82f6',
            fillOpacity: style.fillOpacity ?? 0.12,
          }
        },
        pointToLayer(_f, latlng) {
          return L.circleMarker(latlng, {
            radius: style.radius || 8,
            color: style.color || '#0f766e',
            weight: 2,
            fillColor: style.fillColor || style.color || '#14b8a6',
            fillOpacity: 0.9,
          })
        },
        onEachFeature(feature, lyr) {
          const p = feature.properties || {}
          const title = p.name || p.role || ''
          if (title) lyr.bindPopup(String(title))
        },
      }).addTo(map)
      resultLayers.push(layer)
    }
  }
}

async function initMap() {
  let zoom = 15
  try {
    const cfg = await fetchJson('/api/config')
    if (Array.isArray(cfg.campus_center) && cfg.campus_center.length === 2) {
      campusCenter = [cfg.campus_center[1], cfg.campus_center[0]]
    }
    if (cfg.default_zoom) zoom = cfg.default_zoom
    if (cfg.campus_name) campusName.value = cfg.campus_name
    apiOk.value = true
  } catch {
    apiOk.value = false
  }

  map = L.map(mapEl.value).setView(campusCenter, zoom)
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap',
  }).addTo(map)

  const campusMarker = L.circleMarker(campusCenter, {
    radius: 10,
    color: '#1d4ed8',
    weight: 2,
    fillColor: '#2563eb',
    fillOpacity: 0.9,
  })
    .addTo(map)
    .bindPopup(campusName.value)
  baseLayers.push(campusMarker)

  try {
    const layerList = await fetchJson('/api/layers')
    for (const name of layerList.layers || []) {
      const geo = await fetchJson(`/api/layers/${name}`)
      const layer = L.geoJSON(geo, {
        pointToLayer(_f, latlng) {
          return L.circleMarker(latlng, {
            radius: 6,
            color: '#64748b',
            weight: 1,
            fillColor: '#94a3b8',
            fillOpacity: 0.8,
          })
        },
        onEachFeature(feature, lyr) {
          const p = feature.properties || {}
          lyr.bindPopup(`${p.name || name}<br/>${p.category || ''}`)
        },
      }).addTo(map)
      baseLayers.push(layer)
    }
  } catch {
    /* ignore */
  }

  try {
    const demoData = await fetchJson('/api/demos')
    demos.value = demoData.demos || []
  } catch {
    demos.value = []
  }

  try {
    const modelData = await fetchJson('/api/models')
    models.value = modelData.models || []
    selectedModelId.value =
      modelData.default_model_id || models.value[0]?.id || ''
  } catch {
    models.value = []
  }
}

async function sendQuestion() {
  const question = input.value.trim()
  if (!question || sending.value) return

  messages.value.push({ role: 'user', content: question })
  input.value = ''
  sending.value = true
  await nextTick()
  if (msgBox.value) msgBox.value.scrollTop = msgBox.value.scrollHeight

  try {
    const data = await fetchJson('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question,
        model_id: selectedModelId.value || null,
      }),
    })
    messages.value.push({
      role: 'assistant',
      content: data.answer || '',
      meta: `模式: ${data.mode || '-'} · 模型: ${data.model_id || '-'}`,
      trace: data.trace || [],
    })
    applyMapActions(data.map_actions || [])
  } catch (e) {
    messages.value.push({
      role: 'assistant',
      content: `请求失败：${e.message || e}`,
    })
  } finally {
    sending.value = false
    await nextTick()
    if (msgBox.value) msgBox.value.scrollTop = msgBox.value.scrollHeight
  }
}

function runDemo(d) {
  input.value = d.question
  sendQuestion()
}

onMounted(() => {
  initMap()
})

onUnmounted(() => {
  if (map) {
    map.remove()
    map = null
  }
})
</script>

<style scoped>
.layout {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 20px;
  background: #0f172a;
  color: #f8fafc;
}

.brand h1 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}

.brand p {
  margin: 4px 0 0;
  font-size: 13px;
  opacity: 0.8;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.model-select {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.model-select select {
  max-width: 260px;
  padding: 6px 8px;
  border-radius: 6px;
  border: 1px solid #334155;
  background: #1e293b;
  color: #f8fafc;
}

.status {
  font-size: 13px;
  padding: 6px 10px;
  border-radius: 6px;
  background: #334155;
  white-space: nowrap;
}

.status.ok {
  background: #14532d;
}

.status.err {
  background: #7f1d1d;
}

.main {
  display: grid;
  grid-template-columns: minmax(340px, 420px) 1fr;
  flex: 1;
  min-height: 0;
}

.panel {
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: #fff;
  border-right: 1px solid #e2e8f0;
}

.panel-head {
  padding: 14px 16px 0;
}

.panel-head h2 {
  margin: 0;
  font-size: 15px;
}

.hint {
  margin: 6px 0 0;
  font-size: 12px;
  line-height: 1.5;
  color: #64748b;
}

.demos-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 12px 16px;
}

.demo-btn {
  border: 1px solid #cbd5e1;
  background: #f8fafc;
  border-radius: 999px;
  padding: 6px 10px;
  font-size: 12px;
  cursor: pointer;
}

.demo-btn:hover:not(:disabled) {
  background: #e2e8f0;
}

.demo-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.messages {
  flex: 1;
  overflow: auto;
  padding: 0 16px 12px;
}

.empty {
  color: #94a3b8;
  font-size: 13px;
  padding: 24px 0;
  text-align: center;
}

.msg {
  margin-bottom: 12px;
  padding: 10px 12px;
  border-radius: 10px;
  background: #f1f5f9;
}

.msg.user {
  background: #e0e7ff;
}

.msg-role {
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 4px;
  color: #475569;
}

.msg-body {
  font-size: 14px;
  line-height: 1.55;
  white-space: pre-wrap;
}

.msg-meta {
  margin-top: 6px;
  font-size: 11px;
  color: #64748b;
}

.trace {
  margin: 8px 0 0;
  padding-left: 16px;
  font-size: 12px;
  color: #334155;
}

.trace code {
  font-size: 11px;
  background: #e2e8f0;
  padding: 1px 4px;
  border-radius: 4px;
  margin-right: 6px;
}

.composer {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 8px;
  padding: 12px 16px 16px;
  border-top: 1px solid #e2e8f0;
}

.composer textarea {
  resize: none;
  padding: 10px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  font: inherit;
}

.composer button {
  align-self: end;
  padding: 10px 14px;
  border: none;
  border-radius: 8px;
  background: #2563eb;
  color: #fff;
  cursor: pointer;
}

.composer button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.map-wrap {
  min-height: 0;
}

.map {
  width: 100%;
  height: 100%;
}

@media (max-width: 900px) {
  .main {
    grid-template-columns: 1fr;
    grid-template-rows: minmax(280px, 45vh) 1fr;
  }

  .panel {
    border-right: none;
    border-bottom: 1px solid #e2e8f0;
  }

  .header-right {
    flex-direction: column;
    align-items: flex-end;
  }
}
</style>
