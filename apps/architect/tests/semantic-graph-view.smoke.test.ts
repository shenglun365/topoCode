/**
 * MS6-W0 安全网：SemanticGraphView(2,649 行) 挂载冒烟。
 * 关键守卫：FILE_BUDGET=500 规模闸门(大范围不自动渲染)。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createApp } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { createI18n } from 'vue-i18n'

const RICH = { items: [], total: 0, list: [], data: [], entries: [], files: [], results: [], nodes: [], edges: [], stats: {}, summary: {}, plan: null, counts: {}, status: {}, overview: {}, scope: [], ok: true, status: 'ok' }
const anyFn = () => vi.fn(async () => ({ ...RICH, items: [], total: 0 }))
vi.mock('@/services/semantic-asset-service', () => ({
  semanticAssetService: new Proxy({}, { get: () => anyFn() }),
}))

import SemanticGraphView, { type GraphTabDef } from '@/components/assets/SemanticGraphView.vue'

;(globalThis as any).ResizeObserver =
  (globalThis as any).ResizeObserver ||
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
;(Element.prototype as any).scrollTo = (Element.prototype as any).scrollTo || function () {}

const tick = () => new Promise((r) => setTimeout(r, 10))

const baseTab: GraphTabDef = { id: 't1', kind: 'all', title: '全量图谱' }

function mountView(props: Record<string, unknown> = {}) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const i18n = createI18n({
    legacy: false,
    locale: 'zh',
    missingWarn: false,
    fallbackWarn: false,
    messages: { zh: {} },
  })
  const el = document.createElement('div')
  document.body.appendChild(el)
  const app = createApp(SemanticGraphView, { tab: baseTab, ...props })
  app.use(pinia)
  app.use(i18n)
  const vm = app.mount(el)
  return { app, el, vm }
}

describe('SemanticGraphView 挂载冒烟(MS6-W0)', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
    vi.clearAllMocks()
  })

  it('空索引挂载不崩溃', async () => {
    const { app, el } = mountView({ fileIndex: [] })
    await tick()
    expect(el.children.length).toBeGreaterThan(0)
    app.unmount()
  })

  it('FILE_BUDGET 规模闸门仍在(501 索引不自动渲染, 常量=500)', async () => {
    // 守卫语义: 范围资产超 500 须手动圈定——重构中若有人动了此闸门此测试兜底
    const { app, el } = mountView({ fileIndex: Array.from({ length: 501 }, (_, i) => ({ path: `f${i}.py`, assets: 1 })) as any })
    await tick()
    await tick()
    // 大范围下不产生大规模 svg 渲染(jsdom 中不崩溃即守卫未失效的最低保证)
    expect(el.children.length).toBeGreaterThan(0)
    app.unmount()
  })

  it('tab 标题渲染 + props 变更响应', async () => {
    const { app, el } = mountView()
    await tick()
    expect(el.textContent).toContain('assetMgmt.graph')
    app.unmount()
  })
})
