/**
 * MS6-W0 安全网：AssetManagementWorkspace(3,296 行) 挂载冒烟。
 * MS6 重构判据：结构拆分前后挂载/渲染/服务接线行为零变。
 * 挂载方式：Vue 原生 createApp(零新依赖)；服务面全量 Proxy 桩。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createApp } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { createI18n } from 'vue-i18n'

vi.mock('vue-router', async (importOriginal) => ({
  ...(await importOriginal<any>()),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), currentRoute: { value: { params: {} } } }),
}))

const RICH = { items: [], total: 0, list: [], data: [], entries: [], files: [], results: [], nodes: [], edges: [], stats: {}, summary: {}, plan: null, counts: {}, status: {}, overview: {}, scope: [], ok: true, status: 'ok' }
const anyFn = () => vi.fn(async () => ({ ...RICH, items: [], total: 0 }))
vi.mock('@/services/api-client', () => ({ // eslint-disable-line
  apiGet: vi.fn(async () => null),
  apiPost: vi.fn(async () => null),
  apiPut: vi.fn(async () => null),
}))
vi.mock('@/services/semantic-asset-service', () => ({
  semanticAssetService: new Proxy({}, { get: () => anyFn() }),
}))
vi.mock('@/services/git-service', () => ({
  gitService: new Proxy({}, { get: () => anyFn() }),
}))
vi.mock('@/services/kb-assets', () => ({
  kbAssetService: new Proxy({}, { get: () => anyFn() }),
}))
vi.mock('@/services/requirement-service', () => ({
  requirementService: new Proxy({}, { get: () => anyFn() }),
}))

import AssetManagementWorkspace from '@/pages/AssetManagementWorkspace.vue'

// jsdom 缺失的浏览器 API 桩
;(globalThis as any).ResizeObserver =
  (globalThis as any).ResizeObserver ||
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
;(Element.prototype as any).scrollTo = (Element.prototype as any).scrollTo || function () {}

const tick = () => new Promise((r) => setTimeout(r, 10))

function mountPage() {
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
  const app = createApp(AssetManagementWorkspace)
  app.use(pinia)
  app.use(i18n)
  const vm = app.mount(el)
  return { app, el, vm }
}

describe('AssetManagementWorkspace 挂载冒烟(MS6-W0)', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
    vi.clearAllMocks()
  })

  it('全服务桩下挂载不崩溃且可卸载', async () => {
    const { app, el } = mountPage()
    await tick()
    await tick()
    expect(el.children.length).toBeGreaterThan(0)
    app.unmount()
  })

  it('渲染页头标题结构(h2 存在)', async () => {
    const { app, el } = mountPage()
    await tick()
    expect(el.querySelector('h2')).toBeTruthy()
    app.unmount()
  })

  it('重复挂载稳定(模拟切换页签重进)', async () => {
    for (let i = 0; i < 2; i++) {
      const { app, el } = mountPage()
      await tick()
      await tick()
      expect(el.children.length).toBeGreaterThan(0)
      app.unmount()
    }
  })
})
