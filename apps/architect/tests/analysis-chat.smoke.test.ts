/**
 * MS6-W0 安全网：AnalysisChat(2,383 行) 挂载冒烟。
 * 关键交互：busy 态文案（busyLabel 覆盖 > 静态默认「知识库检索中…」）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createApp } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { createI18n } from 'vue-i18n'

vi.mock('@/services/api-client', () => ({ // eslint-disable-line
  apiGet: vi.fn(async () => null),
  apiPost: vi.fn(async () => null),
  apiPut: vi.fn(async () => null),
}))

import AnalysisChat from '@/components/requirements/AnalysisChat.vue'

;(globalThis as any).ResizeObserver =
  (globalThis as any).ResizeObserver ||
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  }

const tick = () => new Promise((r) => setTimeout(r, 10))

function mountChat(props: Record<string, unknown> = {}) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const i18n = createI18n({
    legacy: false,
    locale: 'zh',
    missingWarn: false,
    fallbackWarn: false,
    messages: { zh: { requirement: { chat: { thinking: '知识库检索中…' } } } },
  })
  const el = document.createElement('div')
  document.body.appendChild(el)
  const app = createApp(AnalysisChat, { turns: [], busy: false, ...props })
  app.use(pinia)
  app.use(i18n)
  const vm = app.mount(el)
  return { app, el, vm }
}

describe('AnalysisChat 挂载冒烟(MS6-W0)', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
    vi.clearAllMocks()
  })

  it('空 turns 挂载不崩溃', async () => {
    const { app, el } = mountChat()
    await tick()
    expect(el.children.length).toBeGreaterThan(0)
    app.unmount()
  })

  it('busy=true 渲染自定义 busyLabel', async () => {
    const { el, app } = mountChat({ busy: true, busyLabel: '正在调用工具 kb.asset.search…' })
    await tick()
    expect(el.textContent).toContain('正在调用工具 kb.asset.search…')
    app.unmount()
  })

  it('busy=true 无 busyLabel 回落静态默认文案', async () => {
    const { el, app } = mountChat({ busy: true })
    await tick()
    expect(el.textContent).toContain('知识库检索中')
    app.unmount()
  })

  it('带 turns 渲染消息数量', async () => {
    const turns = [
      { role: 'user', content: '分析这个项目' },
      { role: 'assistant', content: '好的' },
    ] as any[]
    const { el, app } = mountChat({ turns })
    await tick()
    expect(el.textContent).toContain('分析这个项目')
    app.unmount()
  })
})
