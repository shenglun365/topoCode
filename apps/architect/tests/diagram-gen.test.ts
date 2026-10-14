import { describe, expect, it } from 'vitest'
import { semanticGraphViewDiagrams } from '@/utils/diagram-gen'


describe('视图合成节点 clickMap(全节点可点+行级定位)', () => {
  const N = (id: string, kind: string, name: string, detail: Record<string, unknown> = {}): never =>
    ({ id, kind, name, detail }) as never
  const E: never[] = []

  it('活动图：决策分支/步骤/触发合成节点登记宿主+分支行号', () => {
    const nodes = [
      N('sa-d-1', 'decision', '构建回执', { branches: [{ condition: 'opts.backend?.render', then: 'A', line: 66 }, { condition: 'x', then: 'B', line: 80 }] }),
      N('sa-p-2', 'process', '帧序列转图谱', { steps: [{ order: 1, semantic: '解析帧序列' }, { order: 2, semantic: '生成节点', condition: 'ok' }], trigger: '输入帧' }),
    ]
    const { clickMap } = semanticGraphViewDiagrams('activity', nodes, E)
    const cond = clickMap.get('opts.backend?.render')
    expect(cond?.assetId).toBe('sa-d-1')
    expect(cond?.line).toBe(66)
    expect(clickMap.get('解析帧序列')?.assetId).toBe('sa-p-2')
    expect(clickMap.get('⚡ 输入帧')?.assetId).toBe('sa-p-2')
    // id 键(mermaid 剥壳寻址)与截断文本键(plantuml 兜底)并存
    expect([...clickMap.keys()].some((k) => /^n\d+$/.test(k))).toBe(true)
    expect(clickMap.get('帧序列转图谱')?.assetId ?? clickMap.get('生成节点')?.assetId).toBeTruthy()
  })

  it('状态图：子状态/决策分支合成 id 与文本键登记(分支带行号)', () => {
    const nodes = [
      N('sa-s-9', 'state', '渲染状态机', { states: [{ name: '空闲', initial: true }, { name: '渲染中' }], transitions: [{ from: '空闲', to: '渲染中', event: 'go' }] }),
      N('sa-d-8', 'decision', '分支决策', { branches: [{ condition: 'c1', then: 'T', line: 12 }] }),
    ]
    const { clickMap } = semanticGraphViewDiagrams('state', nodes, E)
    expect(clickMap.get('sa_s_9_s0')?.assetId).toBe('sa-s-9')
    expect(clickMap.get('空闲')?.assetId).toBe('sa-s-9')
    expect(clickMap.get('sa_d_8_b0')?.assetId).toBe('sa-d-8')
    expect(clickMap.get('sa_d_8_b0')?.line).toBe(12)
    expect(clickMap.get('c1')?.line).toBe(12)
  })

  it('其他视图不受影响：clickMap 为空(节点=资产由 clickIds 覆盖)', () => {
    const { clickMap } = semanticGraphViewDiagrams('er', [N('sa-e-1', 'entity', '订单', { fields: [{ name: 'id' }] })], E)
    expect(clickMap.size).toBe(0)
  })
})
