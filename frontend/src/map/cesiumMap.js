/**
 * Cesium 3D GIS 适配器：消费后端 map_actions（setView / addGeoJSON）。
 * 通过 index.html 全局脚本加载 window.Cesium（避免 Vite ESM 白屏）。
 * 有 VITE_CESIUM_ION_TOKEN 时启用世界地形 + OSM Buildings。
 */

function getCesium() {
  const Cesium = window.Cesium
  if (!Cesium) {
    throw new Error('Cesium 全局对象未加载，请确认 /cesium/Cesium.js 可访问')
  }
  return Cesium
}

function parseColor(input, alpha = 1) {
  const Cesium = getCesium()
  if (!input) return Cesium.Color.CYAN.withAlpha(alpha)
  try {
    const c = Cesium.Color.fromCssColorString(String(input))
    return c.withAlpha(alpha)
  } catch {
    return Cesium.Color.CYAN.withAlpha(alpha)
  }
}

async function createBaseImageryProvider(ionToken) {
  const Cesium = getCesium()
  // 1) 有 Ion Token：用官方影像（最稳）
  if (ionToken) {
    try {
      return await Cesium.IonImageryProvider.fromAssetId(2)
    } catch (e) {
      console.warn('Ion 影像不可用，尝试公开瓦片', e)
    }
  }

  // 2) Esri 世界影像（一般比 OSM 更少被拦）
  const candidates = [
    () =>
      Promise.resolve(
        new Cesium.UrlTemplateImageryProvider({
          url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
          credit: '© Esri',
          maximumLevel: 18,
        }),
      ),
    () =>
      Promise.resolve(
        new Cesium.UrlTemplateImageryProvider({
          url: 'https://basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png',
          credit: '© CARTO / OSM',
          maximumLevel: 18,
        }),
      ),
    // 3) OSM 最后尝试（国内常需代理，失败会解码报错）
    () =>
      Promise.resolve(
        new Cesium.UrlTemplateImageryProvider({
          url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
          credit: '© OpenStreetMap',
          maximumLevel: 18,
        }),
      ),
  ]

  for (const make of candidates) {
    try {
      return await make()
    } catch (e) {
      console.warn('底图候选失败，继续尝试下一个', e)
    }
  }

  // 4) 纯色底图：保证不因瓦片解码崩溃
  const canvas = document.createElement('canvas')
  canvas.width = 2
  canvas.height = 2
  const ctx = canvas.getContext('2d')
  ctx.fillStyle = '#1e293b'
  ctx.fillRect(0, 0, 2, 2)
  return new Cesium.SingleTileImageryProvider({
    url: canvas.toDataURL('image/png'),
    rectangle: Cesium.Rectangle.MAX_VALUE,
  })
}

export async function createCesiumMap(container, options = {}) {
  const Cesium = getCesium()
  const ionToken = import.meta.env.VITE_CESIUM_ION_TOKEN || ''
  if (ionToken) {
    Cesium.Ion.defaultAccessToken = ionToken
  }

  // 关键：必须关掉默认 Ion 底图。无 Token 时默认层会拉失败的“图片”，
  // 浏览器解码时报 InvalidStateError: The source image could not be decoded。
  // 再次确保资源根路径（InfoBox CSS 等依赖此变量）
  if (typeof window !== 'undefined' && !window.CESIUM_BASE_URL) {
    window.CESIUM_BASE_URL = '/cesium/'
  }

  const viewer = new Cesium.Viewer(container, {
    animation: false,
    timeline: false,
    baseLayerPicker: false,
    geocoder: false,
    homeButton: false,
    sceneModePicker: false,
    navigationHelpButton: false,
    fullscreenButton: true,
    // InfoBox 会 iframe 加载 Widgets/InfoBox/InfoBoxDescription.css；
    // 在 Vite 下若 BASE_URL 不对会 404，这里关闭，点选仍可用实体 label。
    infoBox: false,
    selectionIndicator: true,
    baseLayer: false,
    terrain: ionToken ? Cesium.Terrain.fromWorldTerrain() : undefined,
  })

  viewer.imageryLayers.removeAll()
  // 无瓦片时球体也不至于全黑
  viewer.scene.globe.baseColor = Cesium.Color.fromCssColorString('#1e293b')

  try {
    const imageryProvider = await createBaseImageryProvider(ionToken)
    const imageryLayer = viewer.imageryLayers.addImageryProvider(imageryProvider)
    imageryLayer.alpha = 1
  } catch (e) {
    console.warn('底图全部失败，仅显示纯色地球', e)
  }

  viewer.scene.globe.depthTestAgainstTerrain = Boolean(ionToken)
  viewer.scene.globe.enableLighting = false
  if (viewer.cesiumWidget?.creditContainer) {
    viewer.cesiumWidget.creditContainer.style.display = 'none'
  }

  let originLon = options.lon ?? 114.615
  let originLat = options.lat ?? 30.458
  /** @type {Cesium.CustomDataSource} */
  const baseSource = new Cesium.CustomDataSource('base')
  /** @type {Cesium.CustomDataSource} */
  const resultSource = new Cesium.CustomDataSource('result')
  await viewer.dataSources.add(baseSource)
  await viewer.dataSources.add(resultSource)

  let osmBuildings = null
  if (ionToken) {
    try {
      osmBuildings = await Cesium.createOsmBuildingsAsync()
      viewer.scene.primitives.add(osmBuildings)
    } catch (e) {
      console.warn('Cesium OSM Buildings 加载失败（可继续用球体+分析结果）', e)
    }
  }

  function setOrigin(lon, lat) {
    originLon = lon
    originLat = lat
  }

  function clearSource(source) {
    source.entities.removeAll()
  }

  function flyTo(lon, lat, zoom = 15) {
    const range = Math.max(400, 18000 - zoom * 1000)
    viewer.camera.flyTo({
      destination: Cesium.Cartesian3.fromDegrees(lon, lat, range),
      orientation: {
        heading: Cesium.Math.toRadians(20),
        pitch: Cesium.Math.toRadians(-45),
        roll: 0,
      },
      duration: 1.2,
    })
  }

  function addPointEntity(source, lon, lat, opts = {}) {
    const color = parseColor(opts.color, 0.95)
    const height = opts.height ?? 40
    const radius = opts.radius ?? 8
    source.entities.add({
      name: opts.label || '点',
      position: Cesium.Cartesian3.fromDegrees(lon, lat, height / 2),
      cylinder: {
        length: height,
        topRadius: radius,
        bottomRadius: radius * 1.1,
        material: color,
        outline: true,
        outlineColor: Cesium.Color.WHITE.withAlpha(0.35),
      },
      label: opts.label
        ? {
            text: String(opts.label),
            font: '12px sans-serif',
            fillColor: Cesium.Color.WHITE,
            outlineColor: Cesium.Color.BLACK,
            outlineWidth: 2,
            style: Cesium.LabelStyle.FILL_AND_OUTLINE,
            verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
            pixelOffset: new Cesium.Cartesian2(0, -18),
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
            show: true,
          }
        : undefined,
      description: opts.label || '',
    })
  }

  function addPolygonEntity(source, coordinates, opts = {}) {
    if (!coordinates?.length) return
    const outer = coordinates[0]
    if (!outer?.length) return
    const hierarchy = outer.map(([lon, lat]) => Cesium.Cartesian3.fromDegrees(lon, lat))
    const holes = (coordinates.slice(1) || []).map(
      (ring) =>
        new Cesium.PolygonHierarchy(
          ring.map(([lon, lat]) => Cesium.Cartesian3.fromDegrees(lon, lat)),
        ),
    )
    source.entities.add({
      name: opts.label || '面',
      polygon: {
        hierarchy: new Cesium.PolygonHierarchy(hierarchy, holes),
        material: parseColor(opts.color, opts.fillOpacity ?? 0.28),
        outline: true,
        outlineColor: parseColor(opts.color, 0.9),
        height: 2,
        extrudedHeight: opts.extrudedHeight ?? 12,
      },
    })
  }

  function addGeoJSON(source, geojson, style = {}) {
    if (!geojson) return
    const features =
      geojson.type === 'FeatureCollection'
        ? geojson.features || []
        : geojson.type === 'Feature'
          ? [geojson]
          : geojson.type
            ? [{ type: 'Feature', geometry: geojson, properties: {} }]
            : []

    for (const feature of features) {
      const geom = feature.geometry
      if (!geom) continue
      const props = feature.properties || {}
      const label = props.name || props.role || props.category || ''
      const color = style.color || '#22d3ee'

      if (geom.type === 'Point') {
        const [lon, lat] = geom.coordinates
        addPointEntity(source, lon, lat, {
          color,
          radius: Math.max(4, (style.radius || 8) * 0.8),
          height: props.role === 'target' ? 60 : 36,
          label,
        })
      } else if (geom.type === 'MultiPoint') {
        for (const c of geom.coordinates || []) {
          addPointEntity(source, c[0], c[1], { color, label })
        }
      } else if (geom.type === 'Polygon') {
        addPolygonEntity(source, geom.coordinates, {
          color,
          fillOpacity: style.fillOpacity ?? 0.25,
          label,
          extrudedHeight: 18,
        })
      } else if (geom.type === 'MultiPolygon') {
        for (const poly of geom.coordinates || []) {
          addPolygonEntity(source, poly, {
            color,
            fillOpacity: style.fillOpacity ?? 0.25,
            label,
            extrudedHeight: 18,
          })
        }
      }
    }
  }

  function applyMapActions(actions) {
    if (!Array.isArray(actions)) return
    clearSource(resultSource)
    for (const action of actions) {
      if (action.type === 'setView') {
        flyTo(action.lon, action.lat, action.zoom || 15)
      } else if (action.type === 'addGeoJSON') {
        addGeoJSON(resultSource, action.geojson, action.style || {})
      }
    }
  }

  function addBaseLayer(geojson, style) {
    addGeoJSON(baseSource, geojson, style)
  }

  function addCampusMarker(lon, lat, name) {
    addPointEntity(baseSource, lon, lat, {
      color: '#2563eb',
      radius: 10,
      height: 55,
      label: name || '校区中心',
    })
    flyTo(lon, lat, 15)
  }

  function onResize() {
    // Cesium Viewer 监听容器；强制触发一次
    if (viewer && !viewer.isDestroyed()) {
      viewer.resize()
    }
  }

  function dispose() {
    if (osmBuildings && !osmBuildings.isDestroyed()) {
      viewer.scene.primitives.remove(osmBuildings)
    }
    if (!viewer.isDestroyed()) {
      viewer.destroy()
    }
  }

  // 初次定位
  flyTo(originLon, originLat, 15)

  return {
    setOrigin,
    addCampusMarker,
    addBaseLayer,
    applyMapActions,
    focusOn: flyTo,
    dispose,
    onResize,
    viewer,
  }
}
