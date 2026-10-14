/**
 * MS6-W0 安全网：ReportHome(1,443 行) 挂载冒烟。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createApp } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { createI18n } from 'vue-i18n'

const RICH = { items: [], total: 0, list: [], data: [], entries: [], files: [], results: [], tasks: [], ok: true }
vi.mock('@/services/ipc', () => ({
  ipc: new Proxy({}, { get: () => vi.fn(async () => ({ ...RICH })) }),
}))
vi.mock('@/services/display-dispatcher', () => ({
  displayDispatcher: new Proxy({}, { get: () => vi.fn() }),
}))
vi.mock('@/services/llmClient', () => ({
  isLLMConfigured: vi.fn(() => false),
}))
vi.mock('@/services/control-dispatcher', () => ({
  controlDispatcher: new Proxy({}, { get: () => vi.fn() }),
}))
vi.mock('@/services/sound', () => ({
  playSuccessSound: vi.fn(),
  playFailureSound: vi.fn(),
}))

import ReportHome from '@/components/report/ReportHome.vue'

;(globalThis as any).ResizeObserver =
  (globalThis as any).ResizeObserver ||
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
;(Element.prototype as any).scrollTo = (Element.prototype as any).scrollTo || function () {}

const tick = () => new Promise((r) => setTimeout(r, 10))

function mountReport(props: Record<string, unknown> = {}) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const i18n = createI18n({ legacy: false, locale: 'zh', missingWarn: false, fallbackWarn: false, messages: { zh: {} } })
  const el = document.createElement('div')
  document.body.appendChild(el)
  const app = createApp(ReportHome, { taskId: 't-smoke', tabId: 'tab-smoke', ...props })
  app.use(pinia)
  app.use(i18n)
  const vm = app.mount(el)
  return { app, el, vm }
}

describe('ReportHome 挂载冒烟(MS6-W0)', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
    vi.clearAllMocks()
  })

  it('ipc 全桩下挂载不崩溃且可卸载', async () => {
    const { app, el } = mountReport()
    await tick()
    await tick()
    expect(el.children.length).toBeGreaterThan(0)
    app.unmount()
  })

  it('重复挂载稳定(模拟报告页签切换)', async () => {
    for (let i = 0; i < 2; i++) {
      const { app, el } = mountReport()
      await tick()
      await tick()
      expect(el.children.length).toBeGreaterThan(0)
      app.unmount()
    }
  })

  it('空态渲染无异常文本溢出(根节点存在)', async () => {
    const { el, app } = mountReport()
    await tick()
    expect(el.firstElementChild).toBeTruthy()
    app.unmount()
  })
})
