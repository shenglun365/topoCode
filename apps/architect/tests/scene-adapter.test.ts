/** 批4-2：资产图谱→统一 JSON 适配测试 */
import { describe, expect, it } from 'vitest'
import { assetsToGraphFrames } from '@/components/assets/graph-view/sceneAdapter'
import type { SemanticGraphResult } from '@/services/semantic-asset-service'

const g: SemanticGraphResult = {
  nodes: [
    { id: 'sa-1', kind: 'process', name: '订单创建', scopeKey: 'comm-order' },
    { id: 'sa-2', kind: 'entity', name: 'Order', scopeKey: 'comm-order' },
    { id: 'sa-3', kind: 'process', name: '库存校验', scopeKey: '' },
  ],
  edges: [
    { from: 'sa-1', to: 'sa-2' },
    { from: 'sa-1', to: 'sa-dangling' },   // 悬挂边应被滤
  ],
  anchors: [],
  count: 3,
}

describe('assetsToGraphFrames', () => {
  it('canonical 映射 + 悬挂边过滤 + 组件容器圈定', () => {
    const gi = assetsToGraphFrames(g, {
      components: [{ id: 'order', name: '订单组件' }],
    })
    expect(gi.canonical.nodes.map((n) => n.key)).toEqual(['sa-1', 'sa-2', 'sa-3'])
    expect(gi.canonical.edges).toHaveLength(1)
    expect(gi.canonical.containers).toHaveLength(1)
    expect(gi.canonical.containers[0]).toMatchObject({ key: 'order', label: '订单组件' })
    expect(gi.canonical.containers[0].children).toEqual(['sa-1', 'sa-2'])
    // 单帧模式(无 changedIds)：视角帧=全量
    expect(gi.frames).toHaveLength(1)
    expect(gi.frames[0].nodes).toHaveLength(3)
  })

  it('changedIds 双帧：基线底座帧(非变化) → 视角帧(全量+modified)', () => {
    const gi = assetsToGraphFrames(g, { rev: 'workspace', changedIds: new Set(['sa-3']) })
    expect(gi.frames).toHaveLength(2)
    const [base, view] = gi.frames
    expect(base.label).toBe('基线')
    expect(base.nodes).toContain('sa-1')
    expect(base.nodes).not.toContain('sa-3')
    expect(view.nodes).toHaveLength(3)
    expect(view.modified).toEqual(['sa-3'])
    // 边随两端存活：基线帧无 sa-3 相关边
    expect(base.edges.length).toBeLessThanOrEqual(view.edges.length)
  })
})
