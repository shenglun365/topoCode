/**
 * ChatSession 挂载冒烟（MS7-W2：M12"chat 前端零测试"豁免收窄为最小冒烟）。
 * W2/W3 拆分与上提的结构守卫：服务面全桩下挂载不崩溃。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createApp } from 'vue'
import { createI18n } from 'vue-i18n'

vi.mock('@topo/web-core/services/api', () =>
  new Proxy({}, { get: (_t, p) => (p === '__esModule' ? false : vi.fn(async () => ({}))) }) as any)
vi.mock('@topo/web-core/services/chat-stream', () => ({
  consumeChatSse: vi.fn(async () => ({})),
}))
vi.mock('@topo/web-core/services/render', () => ({
  renderMarkdown: vi.fn((s: string) => s),
  renderDocMarkdown: vi.fn((s: string) => s),
  codeFullscreen: { value: false },
}))
vi.mock('@topo/web-core/services/parseContent', () => ({
  parseDocContent: vi.fn(() => []),
}))
vi.mock('@topo/web-core/services/diagramStateStore', () => ({
  diagramStateStore: { value: {} },
}))

import ChatSession from '@/pages/ChatSession.vue'

// jsdom 缺失 API 桩
;(globalThis as any).BroadcastChannel =
  (globalThis as any).BroadcastChannel ||
  class {
    postMessage() {}
    close() {}
    addEventListener() {}
    removeEventListener() {}
  }
;(globalThis as any).matchMedia =
  (globalThis as any).matchMedia ||
  ((q: string) => ({ matches: false, media: q, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }))
;(globalThis as any).ResizeObserver =
  (globalThis as any).ResizeObserver ||
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  }

const tick = () => new Promise((r) => setTimeout(r, 10))

function mountPage() {
  const i18n = createI18n({
    legacy: false,
    locale: 'zh',
    missingWarn: false,
    fallbackWarn: false,
    messages: { zh: {} },
  })
  const el = document.createElement('div')
  document.body.appendChild(el)
  const app = createApp(ChatSession)
  app.use(i18n)
  const vm = app.mount(el)
  return { app, el, vm }
}

describe('ChatSession 挂载冒烟(MS7-W2, M12 豁免收窄)', () => {
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

  it('重复挂载稳定(模拟会话切换重进)', async () => {
    for (let i = 0; i < 2; i++) {
      const { app, el } = mountPage()
      await tick()
      await tick()
      expect(el.children.length).toBeGreaterThan(0)
      app.unmount()
    }
  })
})
