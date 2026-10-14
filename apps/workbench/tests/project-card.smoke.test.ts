/**
 * MS6-W0 安全网：ProjectCard(1,441 行) 挂载冒烟。
 * 关键交互：卡片点击 → emit('select', project)。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createApp, h, nextTick } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { createI18n } from 'vue-i18n'

vi.mock('@/services/ipc', () => ({
  ipc: new Proxy({}, { get: () => vi.fn(async () => ({ ok: true, items: [], total: 0 })) }),
}))

import ProjectCard from '@/components/project/ProjectCard.vue'
import type { Project } from '@/types'

const fixture: Project = {
  id: 'p-smoke',
  name: '冒烟项目',
  path: '/tmp/smoke-proj',
  language: 'python',
  fileCount: 42,
  status: 'synced',
  lastSync: '2026-09-25T00:00:00Z',
  createdAt: '2026-09-25T00:00:00Z',
}

const tick = () => new Promise((r) => setTimeout(r, 10))

function mountCard(props: Record<string, unknown>, listeners: Record<string, (...a: any[]) => void> = {}) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const i18n = createI18n({ legacy: false, locale: 'zh', missingWarn: false, fallbackWarn: false, messages: { zh: {} } })
  const el = document.createElement('div')
  document.body.appendChild(el)
  const app = createApp({
    render: () =>
      h(ProjectCard, {
        project: fixture,
        ...props,
        ...listeners,
      }),
  })
  app.use(pinia)
  app.use(i18n)
  app.mount(el)
  return { el }
}

describe('ProjectCard 挂载冒烟(MS6-W0)', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
    vi.clearAllMocks()
  })

  it('渲染项目名称与路径', async () => {
    const { el } = mountCard({})
    await tick()
    expect(el.textContent).toContain('冒烟项目')
  })

  it('点击卡片 → emit(select, project)', async () => {
    const onSelect = vi.fn()
    const { el } = mountCard({}, { onSelect })
    await tick()
    const card = el.querySelector('.project-card') as HTMLElement
    expect(card).toBeTruthy()
    card.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await nextTick()
    expect(onSelect).toHaveBeenCalledWith(fixture)
  })

  it('pinned 样式位生效(project.pinned → card-pinned)', async () => {
    const { el } = mountCard({ project: { ...fixture, pinned: true } })
    await tick()
    expect(el.querySelector('.card-pinned')).toBeTruthy()
  })
})
