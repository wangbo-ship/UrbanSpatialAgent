/**
 * Three.js 地图适配器：消费后端 map_actions（setView / addGeoJSON）。
 * 以校区中心为原点，经纬度近似转为本地米制坐标（X 东、Z 南、Y 上）。
 */
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'

function hexColor(input, fallback = 0x2563eb) {
  if (!input) return fallback
  if (typeof input === 'number') return input
  const s = String(input).replace('#', '')
  const n = Number.parseInt(s.length === 3 ? s.split('').map((c) => c + c).join('') : s, 16)
  return Number.isFinite(n) ? n : fallback
}

export function createThreeMap(container) {
  const scene = new THREE.Scene()
  scene.background = new THREE.Color(0x0b1220)
  scene.fog = new THREE.Fog(0x0b1220, 1200, 4200)

  const renderer = new THREE.WebGLRenderer({ antialias: true })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
  renderer.setSize(container.clientWidth, container.clientHeight)
  container.appendChild(renderer.domElement)

  const camera = new THREE.PerspectiveCamera(
    50,
    container.clientWidth / Math.max(container.clientHeight, 1),
    1,
    20000,
  )
  camera.position.set(0, 650, 900)

  const controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = true
  controls.target.set(0, 0, 0)
  controls.maxPolarAngle = Math.PI * 0.49
  controls.minDistance = 80
  controls.maxDistance = 3500

  scene.add(new THREE.AmbientLight(0xffffff, 0.55))
  const dir = new THREE.DirectionalLight(0xffffff, 0.85)
  dir.position.set(400, 800, 200)
  scene.add(dir)

  // 地面
  const ground = new THREE.Mesh(
    new THREE.PlaneGeometry(4000, 4000),
    new THREE.MeshStandardMaterial({
      color: 0x1e293b,
      roughness: 0.95,
      metalness: 0.05,
    }),
  )
  ground.rotation.x = -Math.PI / 2
  ground.receiveShadow = true
  scene.add(ground)

  const grid = new THREE.GridHelper(4000, 40, 0x334155, 0x1f2937)
  grid.position.y = 0.5
  scene.add(grid)

  // 坐标轴示意（小）
  const axes = new THREE.AxesHelper(120)
  axes.position.y = 1
  scene.add(axes)

  let originLon = 114.615
  let originLat = 30.458
  const baseGroup = new THREE.Group()
  const resultGroup = new THREE.Group()
  scene.add(baseGroup)
  scene.add(resultGroup)

  const labelEl = document.createElement('div')
  labelEl.className = 'three-map-label'
  labelEl.style.cssText =
    'position:absolute;left:12px;bottom:12px;z-index:2;padding:8px 10px;border-radius:8px;background:rgba(15,23,42,.82);color:#e2e8f0;font-size:12px;pointer-events:none;max-width:60%;line-height:1.45;'
  labelEl.textContent = '三维场景 · 拖拽旋转 / 滚轮缩放'
  container.style.position = 'relative'
  container.appendChild(labelEl)

  let animId = 0
  const clock = new THREE.Clock()

  function lonLatToLocal(lon, lat) {
    const x = (lon - originLon) * 111320 * Math.cos((originLat * Math.PI) / 180)
    const z = (originLat - lat) * 110540
    return { x, z }
  }

  function setOrigin(lon, lat) {
    originLon = lon
    originLat = lat
  }

  function clearGroup(group) {
    while (group.children.length) {
      const obj = group.children[0]
      obj.traverse((child) => {
        if (child.geometry) child.geometry.dispose()
        if (child.material) {
          if (Array.isArray(child.material)) child.material.forEach((m) => m.dispose())
          else child.material.dispose()
        }
      })
      group.remove(obj)
    }
  }

  function addPointMarker(group, lon, lat, opts = {}) {
    const { x, z } = lonLatToLocal(lon, lat)
    const color = hexColor(opts.color, 0x38bdf8)
    const height = opts.height ?? 28
    const radius = opts.radius ?? 6
    const mesh = new THREE.Mesh(
      new THREE.CylinderGeometry(radius, radius * 1.15, height, 16),
      new THREE.MeshStandardMaterial({
        color,
        emissive: color,
        emissiveIntensity: 0.18,
        roughness: 0.45,
      }),
    )
    mesh.position.set(x, height / 2, z)
    mesh.userData.label = opts.label || ''
    group.add(mesh)

    // 顶部小球更醒目
    const cap = new THREE.Mesh(
      new THREE.SphereGeometry(radius * 1.2, 12, 12),
      new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 0.35 }),
    )
    cap.position.set(x, height + radius, z)
    cap.userData.label = opts.label || ''
    group.add(cap)
    return mesh
  }

  function ringToShape(ring) {
    const shape = new THREE.Shape()
    ring.forEach((coord, i) => {
      const [lon, lat] = coord
      const { x, z } = lonLatToLocal(lon, lat)
      if (i === 0) shape.moveTo(x, z)
      else shape.lineTo(x, z)
    })
    return shape
  }

  function addPolygon(group, coordinates, opts = {}) {
    if (!coordinates?.length) return
    const outer = coordinates[0]
    if (!outer?.length) return
    const shape = ringToShape(outer)
    for (let i = 1; i < coordinates.length; i++) {
      const hole = ringToShape(coordinates[i])
      shape.holes.push(hole)
    }
    const color = hexColor(opts.color, 0x2563eb)
    const opacity = opts.fillOpacity ?? 0.28
    const geom = new THREE.ExtrudeGeometry(shape, {
      depth: opts.depth ?? 8,
      bevelEnabled: false,
    })
    // Extrude 在 XY，转到 XZ 地面
    const mesh = new THREE.Mesh(
      geom,
      new THREE.MeshStandardMaterial({
        color,
        transparent: true,
        opacity,
        side: THREE.DoubleSide,
        roughness: 0.7,
      }),
    )
    mesh.rotation.x = Math.PI / 2
    mesh.position.y = 1
    mesh.userData.label = opts.label || 'buffer'
    group.add(mesh)

    // 描边折线
    const pts = outer.map(([lon, lat]) => {
      const p = lonLatToLocal(lon, lat)
      return new THREE.Vector3(p.x, 10, p.z)
    })
    if (pts.length > 1) {
      const line = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints(pts),
        new THREE.LineBasicMaterial({ color }),
      )
      group.add(line)
    }
  }

  function addGeoJSON(group, geojson, style = {}) {
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
      const color = style.color || '#0ea5e9'

      if (geom.type === 'Point') {
        const [lon, lat] = geom.coordinates
        addPointMarker(group, lon, lat, {
          color,
          radius: Math.max(4, (style.radius || 8) * 0.7),
          height: props.role === 'target' ? 48 : 26,
          label,
        })
      } else if (geom.type === 'MultiPoint') {
        for (const c of geom.coordinates || []) {
          addPointMarker(group, c[0], c[1], { color, label })
        }
      } else if (geom.type === 'Polygon') {
        addPolygon(group, geom.coordinates, {
          color,
          fillOpacity: style.fillOpacity ?? 0.25,
          label,
        })
      } else if (geom.type === 'MultiPolygon') {
        for (const poly of geom.coordinates || []) {
          addPolygon(group, poly, {
            color,
            fillOpacity: style.fillOpacity ?? 0.25,
            label,
          })
        }
      }
    }
  }

  function focusOn(lon, lat, zoom = 15) {
    const { x, z } = lonLatToLocal(lon, lat)
    controls.target.set(x, 0, z)
    const dist = Math.max(180, 2200 - zoom * 110)
    camera.position.set(x + dist * 0.55, dist * 0.55, z + dist * 0.75)
    controls.update()
  }

  function applyMapActions(actions) {
    if (!Array.isArray(actions)) return
    clearGroup(resultGroup)
    for (const action of actions) {
      if (action.type === 'setView') {
        focusOn(action.lon, action.lat, action.zoom || 15)
        labelEl.textContent = `视角已定位 · (${action.lat?.toFixed?.(5)}, ${action.lon?.toFixed?.(5)})`
      } else if (action.type === 'addGeoJSON') {
        addGeoJSON(resultGroup, action.geojson, action.style || {})
        const role =
          action.geojson?.properties?.role ||
          action.geojson?.features?.[0]?.properties?.role ||
          action.id ||
          '图层'
        labelEl.textContent = `已叠加分析结果：${role}`
      }
    }
  }

  function addBaseLayer(geojson, style) {
    addGeoJSON(baseGroup, geojson, style)
  }

  function addCampusMarker(lon, lat, name) {
    addPointMarker(baseGroup, lon, lat, {
      color: '#2563eb',
      radius: 9,
      height: 40,
      label: name || '校区中心',
    })
    focusOn(lon, lat, 15)
    labelEl.textContent = name ? `三维场景 · ${name}` : labelEl.textContent
  }

  const raycaster = new THREE.Raycaster()
  const pointer = new THREE.Vector2()
  function onPointerDown(event) {
    const rect = renderer.domElement.getBoundingClientRect()
    pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1
    pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1
    raycaster.setFromCamera(pointer, camera)
    const hits = raycaster.intersectObjects([...baseGroup.children, ...resultGroup.children], true)
    if (hits.length && hits[0].object.userData.label) {
      labelEl.textContent = hits[0].object.userData.label
    }
  }
  renderer.domElement.addEventListener('pointerdown', onPointerDown)

  function onResize() {
    if (!container) return
    const w = container.clientWidth
    const h = Math.max(container.clientHeight, 1)
    camera.aspect = w / h
    camera.updateProjectionMatrix()
    renderer.setSize(w, h)
  }
  window.addEventListener('resize', onResize)

  function tick() {
    animId = requestAnimationFrame(tick)
    controls.update(clock.getDelta())
    renderer.render(scene, camera)
  }
  tick()

  function dispose() {
    cancelAnimationFrame(animId)
    window.removeEventListener('resize', onResize)
    renderer.domElement.removeEventListener('pointerdown', onPointerDown)
    clearGroup(baseGroup)
    clearGroup(resultGroup)
    controls.dispose()
    renderer.dispose()
    if (renderer.domElement.parentNode) {
      renderer.domElement.parentNode.removeChild(renderer.domElement)
    }
    if (labelEl.parentNode) labelEl.parentNode.removeChild(labelEl)
  }

  return {
    setOrigin,
    addCampusMarker,
    addBaseLayer,
    applyMapActions,
    focusOn,
    dispose,
    onResize,
  }
}
