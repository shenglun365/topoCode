/** PIXI.js Canvas Composable - 主线程 WebGL 渲染 */

import { ref, watch, type Ref, onMounted, onUnmounted } from 'vue'

export interface PixiNode {
  id: string
  x: number
  y: number
  label?: string
  color?: string
  radius?: number
}

export interface PixiEdge {
  source: string
  target: string
  color?: string
  width?: number
}

export interface UsePixiOptions {
  width?: number
  height?: number
  antialias?: boolean
  autoDensity?: boolean
  backgroundColor?: number
}

export function usePixiCanvas(
  canvasRef: Ref<HTMLCanvasElement | null>,
  options: UsePixiOptions = {}
) {
  let app: any = null
  let container: any = null
  const nodeMap = new Map<string, any>()
  const edgeGraphics = new Map<string, any>()

  const isReady = ref(false)
  const fps = ref(0)
  const nodeCount = ref(0)

  // 初始化 PIXI Application
  async function init() {
    if (!canvasRef.value) return

    try {
      const { Application, Container, Graphics, Text, TextStyle } = await import('pixi.js')

      app = new Application({
        view: canvasRef.value,
        width: options.width || 800,
        height: options.height || 500,
        antialias: options.antialias !== false,
        autoDensity: options.autoDensity !== false,
        backgroundColor: options.backgroundColor ?? 0x1e1e2e,
        resolution: window.devicePixelRatio || 1,
        autoStart: true,
      })

      await app.init()

      container = new Container()
      app.stage.addChild(container)

      // FPS 监控
      let frameCount = 0
      let lastTime = performance.now()

      app.ticker.add(() => {
        frameCount++
        const now = performance.now()
        if (now - lastTime >= 1000) {
          fps.value = frameCount
          frameCount = 0
          lastTime = now
        }
      })

      isReady.value = true
    } catch (e) {
      console.error('[usePixiCanvas] Init failed:', e)
    }
  }

  // 渲染节点和边
  function renderGraph(nodes: PixiNode[], edges: PixiEdge[]) {
    if (!container) return

    // 清除旧内容
    container.removeChildren()
    nodeMap.clear()
    edgeGraphics.clear()

    // 创建边层 (在节点下方)
    const edgeLayer = new (container.constructor || Container)()
    container.addChild(edgeLayer)

    // 渲染边
    for (const edge of edges) {
      const sourceNode = nodes.find(n => n.id === edge.source)
      const targetNode = nodes.find(n => n.id === edge.target)
      if (!sourceNode || !targetNode) continue

      const graphics = new Graphics()
      graphics.moveTo(sourceNode.x, sourceNode.y)
      graphics.lineTo(targetNode.x, targetNode.y)
      graphics.stroke({
        width: edge.width || 2,
        color: edge.color || 0x45475a,
        alpha: 0.4,
      })
      edgeLayer.addChild(graphics)
      edgeGraphics.set(`${edge.source}-${edge.target}`, graphics)
    }

    // 渲染节点
    const nodeLayer = new (container.constructor || Container)()
    container.addChild(nodeLayer)

    const textStyle = new TextStyle({
      fontFamily: 'var(--font-mono, Consolas)',
      fontSize: 11,
      fill: 0xcdd6f4,
      fontWeight: '600',
    })

    for (const node of nodes) {
      const group = new (container.constructor || Container)()
      group.position.set(node.x, node.y)

      // 外圈光晕
      const glow = new Graphics()
      glow.circle(0, 0, (node.radius || 18) + 6)
      glow.fill({ color: node.color || 0x89b4fa, alpha: 0.1 })
      group.addChild(glow)

      // 内圈
      const circle = new Graphics()
      circle.circle(0, 0, node.radius || 18)
      circle.fill({ color: node.color || 0x89b4fa, alpha: 0.2 })
      circle.stroke({ width: 2, color: node.color || 0x89b4fa })
      group.addChild(circle)

      // 标签
      if (node.label) {
        const text = new Text({ text: node.label, style: textStyle })
        text.anchor.set(0.5, 0.5)
        text.position.set(0, 0)
        group.addChild(text)
      }

      // 交互
      group.eventMode = 'static'
      group.cursor = 'pointer'
      group.on('pointerover', () => {
        circle.stroke({ width: 3, color: node.color || 0x89b4fa })
        glow.fill({ color: node.color || 0x89b4fa, alpha: 0.2 })
      })
      group.on('pointerout', () => {
        circle.stroke({ width: 2, color: node.color || 0x89b4fa })
        glow.fill({ color: node.color || 0x89b4fa, alpha: 0.1 })
      })

      nodeLayer.addChild(group)
      nodeMap.set(node.id, group)
    }

    nodeCount.value = nodes.length
  }

  // 添加动画粒子
  function addFlowAnimation(edgeId: string, color: number = 0x89b4fa, speed: number = 2) {
    if (!container) return

    const edge = [...edgeGraphics.values()].find((_, i) => {
      const keys = [...edgeGraphics.keys()]
      return keys[i] === edgeId
    })

    if (!edge) return

    const particle = new Graphics()
    particle.circle(0, 0, 3)
    particle.fill({ color })
    container.addChild(particle)

    let t = 0
    const sourceNode = nodeMap.get(edgeId.split('-')[0])
    const targetNode = nodeMap.get(edgeId.split('-')[1])

    if (!sourceNode || !targetNode) return

    app.ticker.add(() => {
      t += speed * 0.01
      if (t > 1) t = 0

      particle.position.set(
        sourceNode.position.x + (targetNode.position.x - sourceNode.position.x) * t,
        sourceNode.position.y + (targetNode.position.y - sourceNode.position.y) * t,
      )
    })
  }

  // 调整大小
  function resize(width: number, height: number) {
    if (!app) return
    app.renderer.resize(width, height)
  }

  // 导出 PNG
  async function exportPng(filename: string = 'graph.png'): Promise<void> {
    if (!app) return

    const renderer = app.renderer
    const texture = await renderer.generateTexture(app.stage)
    const canvas = renderer.generateCanvas(texture)

    canvas.toBlob((blob) => {
      if (!blob) return
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      a.click()
      URL.revokeObjectURL(url)
    })
  }

  // 销毁
  function destroy() {
    if (app) {
      app.destroy(true, { children: true, texture: true })
      app = null
    }
    container = null
    nodeMap.clear()
    edgeGraphics.clear()
    isReady.value = false
  }

  onMounted(() => {
    init()
  })

  onUnmounted(() => {
    destroy()
  })

  return {
    isReady,
    fps,
    nodeCount,
    renderGraph,
    addFlowAnimation,
    resize,
    exportPng,
    destroy,
  }
}
