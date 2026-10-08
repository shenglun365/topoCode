/**
 * W5 AdvicePanel 冒烟——渲染/建议语义文案/发送禁用态/事实条。
 * service 层 mock(不吃后端); 断言"建议视角"基调文案(DoD: 无强制步骤的可视表达)。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('../src/services/unit-test-service', () => ({
  unitTestService: { sendMessage: vi.fn(), listTests: vi.fn(), listSessions: vi.fn() },
  unitTestAdviceService: {
    listAdvice: vi.fn().mockResolvedValue({
      items: [{
        symbol: 'm.Report', kind: 'class', file: 'src/report.py', line: 8,
        fan_in: 3, weight: 9,
        evidence: { neighborhood: '## src/report.py\n- [class] m.Report (:8)', truncated: false, baseline_stale: false },
      }],
      projectId: 'p1', approval: { mode: 'none' },
    }),
    getFacts: vi.fn().mockResolvedValue({
      projectId: 'p1', scannedCount: 4, claimedCount: 2,
      claimedOnly: ['tests/x.test.ts'], scannedOnly: [], scanAt: 1,
    }),
  },
}))

import AdvicePanel from '../src/components/unit-test/AdvicePanel.vue'
import { unitTestAdviceService } from '../src/services/unit-test-service'

const i18n = createI18n({
  legacy: false, locale: 'zh-CN', missingWarn: false, fallbackWarn: false,
  messages: { 'zh-CN': { common: { refresh: '刷新' }, unitTest: { advice: {
    tabTitle: '测试建议', advisory: '建议视角 · 仅供参考',
    factsBar: '事实层: 扫描 {scanned} 个测试文件 · 回执主张 {claimed} 个',
    claimedOnly: '{n} 个回执主张未落盘(待核验)', fanIn: '权重',
    stale: '基线可能过期', staleHint: '滞后', send: '发到会话',
    sendPrompt: '请为以下符号补充单元测试', needSession: '请先打开一个单测会话',
    covered: '覆盖良好',
    reason: { no_project: '未绑定项目', no_baseline: '无基线', no_graph: '图空' },
  } } } },
})

beforeEach(() => { setActivePinia(createPinia()) })

describe('AdvicePanel (W5)', () => {
  it('渲染建议卡 + 建议语义文案 + 事实条', async () => {
    const w = mount(AdvicePanel, { global: { plugins: [i18n, createPinia()] } })
    await flushPromises()
    expect(w.text()).toContain('建议视角 · 仅供参考')       // 基调: 非工单语义
    expect(w.text()).toContain('m.Report')
    expect(w.text()).toContain('fan-in 3')
    expect(w.text()).toContain('扫描 4 个测试文件')
    expect(w.text()).toContain('1 个回执主张未落盘')
    expect(unitTestAdviceService.listAdvice).toHaveBeenCalled()
  })

  it('无会话时发送禁用(title 提示)', async () => {
    const w = mount(AdvicePanel, { global: { plugins: [i18n, createPinia()] } })
    await flushPromises()
    const btn = w.findAll('button').find((b) => b.text().includes('发到会话'))
    expect(btn?.attributes('disabled')).toBeDefined()
    expect(btn?.attributes('title')).toBe('请先打开一个单测会话')
  })

  it('展开证据视图(邻域大纲)', async () => {
    const w = mount(AdvicePanel, { global: { plugins: [i18n, createPinia()] } })
    await flushPromises()
    expect(w.find('pre').exists()).toBe(false)
    await w.findAll('button').at(-1)!.trigger('click')      // 尾部展开钮
    expect(w.find('pre').text()).toContain('m.Report')
  })
})
