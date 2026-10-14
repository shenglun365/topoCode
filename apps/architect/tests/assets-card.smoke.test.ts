/**
 * 技能管理卡冒烟(2610 技能管理面)——分组渲染/编辑校验/启停。
 * service mock(不吃后端)。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

vi.mock('../src/services/assets-service', () => ({
  assetsService: {
    skillsGroups: vi.fn().mockResolvedValue([
      { category: 'requirement-analysis', skills: [
        { name: 'req.assess', description: '四维评估', route_hint: '',
          child_registry: [], source: 'builtin', enabled: true, assetId: '' },
      ] },
      { category: 'quality', skills: [
        { name: 'test.strategy', description: '测试策略', route_hint: '测试缺口时',
          child_registry: [], source: 'builtin', enabled: true, assetId: '' },
      ] },
      { category: 'custom', skills: [
        { name: 'my.skill', description: '自定义技能', route_hint: '测试缺口时',
          child_registry: [], source: 'asset', enabled: true, assetId: 'as-1' },
        { name: 'off.skill', description: '已停用', route_hint: 'x',
          child_registry: [], source: 'asset', enabled: false, assetId: 'as-2' },
      ] },
    ]),
    upsert: vi.fn().mockResolvedValue({}),
    remove: vi.fn().mockResolvedValue(true),
  },
}))
vi.mock('../src/composables/useAppDialog', () => ({
  useAppDialog: () => ({ confirm: vi.fn().mockResolvedValue(true), alert: vi.fn() }),
}))
vi.mock('../src/services/project-service', () => ({
  currentProjectParams: () => ({ root: '/r', project: 'p1' }),
}))

import AssetsCard from '../src/components/config/AssetsCard.vue'
import { assetsService } from '../src/services/assets-service'

const i18n = createI18n({
  legacy: false, locale: 'zh-CN', missingWarn: false, fallbackWarn: false,
  messages: { 'zh-CN': { common: { empty: '', create: '新建', actions: '', save: '保存', cancel: '取消', edit: '编辑' },
    config: { skills: {
      title: '技能管理', hint: '提示', srcAsset: '自定义', srcBuiltin: '内置',
      when: '何时选我', readonly: '只读', nameRequired: '名称必填',
      routeHintRequired: 'route_hint 必填', colDesc: '描述',
      instructionsPh: '', childRegistryPh: '',
      overrideConfirm: '覆盖 {name}？', deleteConfirm: '删除 {name}？',
    } } } },
})

beforeEach(() => { vi.clearAllMocks() })

describe('SkillsCard (技能管理)', () => {
  it('分类分组渲染 + 内置只读 + 自定义可管理', async () => {
    const w = mount(AssetsCard, { global: { plugins: [i18n] } })
    await flushPromises()
    expect(w.text()).toContain('需求分析')                  // category 标签
    expect(w.text()).toContain('req.assess')
    expect(w.text()).toContain('自定义技能')
    // 内置行: 无编辑/删除按钮
    const builtinRow = w.findAll('div').find((d) => d.text().includes('req.assess'))!
    expect(builtinRow.text()).toContain('只读')
    // 自定义行: 有编辑
    const editBtns = w.findAll('button').filter((b) => b.text().includes('编辑'))
    expect(editBtns.length).toBe(2)                        // my.skill + off.skill
    expect(assetsService.skillsGroups).toHaveBeenCalledWith('p1')
  })

  it('新建缺 route_hint 被拦', async () => {
    const w = mount(AssetsCard, { global: { plugins: [i18n] } })
    await flushPromises()
    await w.findAll('button').find((b) => b.text().includes('新建'))!.trigger('click')
    w.findAll('input')[0].setValue('nohint.skill')
    await w.findAll('button').find((b) => b.text().includes('保存'))!.trigger('click')
    await flushPromises()
    expect(w.text()).toContain('route_hint 必填')
    expect(assetsService.upsert).not.toHaveBeenCalled()
  })

  it('禁用行启用切换调 upsert', async () => {
    const w = mount(AssetsCard, { global: { plugins: [i18n] } })
    await flushPromises()
    // 图标按钮顺序: my.skill(启停,删) → off.skill(启停,删); off.skill 启停=倒数第2
    const iconBtns = w.findAll('button').filter((b) =>
      b.element.querySelector('svg') && b.text().trim() === '')
    expect(iconBtns.length).toBeGreaterThanOrEqual(4)
    await iconBtns[iconBtns.length - 2].trigger('click')
    await flushPromises()
    expect(assetsService.upsert).toHaveBeenCalled()
    expect(assetsService.upsert.mock.calls[0][0].enabled).toBe(true)
  })
})
