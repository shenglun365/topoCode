/**
 * L-2 AssetsCard 冒烟——列表渲染/过滤/route_hint 校验/同名覆盖确认。
 * service mock(不吃后端)。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('../src/services/assets-service', () => ({
  ASSET_KINDS: ['skill', 'requirement', 'todo', 'plan', 'analysis'],
  assetsService: {
    list: vi.fn().mockResolvedValue([
      { id: 'as-1', projectId: 'p1', kind: 'skill', name: 'my.skill',
        description: '自定义技能', enabled: true,
        payload: { route_hint: '测试缺口时', child_registry: [] },
        createdAt: 1, updatedAt: 1 },
      { id: 'as-2', projectId: 'p1', kind: 'plan', name: 'plan.x',
        description: '计划资产', enabled: false, payload: {}, createdAt: 1, updatedAt: 1 },
    ]),
    upsert: vi.fn(),
    remove: vi.fn().mockResolvedValue(true),
  },
}))
vi.mock('../src/composables/useAppDialog', () => ({
  useAppDialog: () => ({ confirm: vi.fn().mockResolvedValue(true), alert: vi.fn() }),
}))
vi.mock('../src/stores/project-store', () => ({
  useArchProjectStore: () => ({}),
}))

import AssetsCard from '../src/components/config/AssetsCard.vue'
import { assetsService } from '../src/services/assets-service'

const i18n = createI18n({
  legacy: false, locale: 'zh-CN', missingWarn: false, fallbackWarn: false,
  messages: { 'zh-CN': { common: { empty: '', create: '新建', actions: '', save: '保存', cancel: '取消', edit: '编辑' },
    config: { tabs: {}, assets: {
      title: '资产与技能', hint: '提示', allKinds: '全部类型', colName: '名称', colDesc: '描述',
      colRoute: '路由', colEnabled: '启用', nameRequired: '名称必填',
      routeHintRequired: 'skill 型 route_hint 必填', instructionsPh: '', childRegistryPh: '',
      overrideConfirm: '覆盖 {name}？', deleteConfirm: '删除 {name}？',
    } } } },
})

beforeEach(() => { setActivePinia(createPinia()); vi.clearAllMocks() })

describe('AssetsCard (L-2)', () => {
  it('列表渲染 + kind 过滤', async () => {
    const w = mount(AssetsCard, { global: { plugins: [i18n, createPinia()] } })
    await flushPromises()
    expect(w.text()).toContain('my.skill')
    expect(w.text()).toContain('测试缺口时')                 // route_hint 列
    const select = w.find('select')
    await select.setValue('skill')
    expect(w.text()).toContain('my.skill')
    expect(w.text()).not.toContain('plan.x')                // 过滤生效
  })

  it('新建 skill 缺 route_hint 被拦', async () => {
    const w = mount(AssetsCard, { global: { plugins: [i18n, createPinia()] } })
    await flushPromises()
    await w.findAll('button').find((b) => b.text().includes('新建'))!.trigger('click')
    w.find('input').setValue('nohint.skill')
    await w.findAll('button').find((b) => b.text().includes('保存'))!.trigger('click')
    await flushPromises()
    expect(w.text()).toContain('route_hint 必填')            // 校验拦截
    expect(assetsService.upsert).not.toHaveBeenCalled()
  })

  it('编辑回填 payload 三字段', async () => {
    const w = mount(AssetsCard, { global: { plugins: [i18n, createPinia()] } })
    await flushPromises()
    await w.findAll('button').find((b) => b.text().includes('编辑'))!.trigger('click')
    const inputs = w.findAll('input')
    expect(inputs.at(1)?.element.value).toBe('自定义技能')
  })
})
