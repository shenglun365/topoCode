/**
 * 组件图谱域冒烟+纯函数特征：
 * - compGraphMermaid: parentId → subgraph 层级分组(父含子 cluster, 悬挂兜底平铺)、
 *   dependsOn 边映射、变更加色 class；fileGraphMermaid: imports 边+变更徽标。
 * - CompGraphWorkspace 挂载冒烟(service mock, jsdom 不崩溃)。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createApp } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { createI18n } from 'vue-i18n'
import { compGraphMermaid, fileGraphMermaid } from '@/components/assets/comp-graph/mermaid'

const RICH = { items: [], total: 0, list: [], data: [], entries: [], files: [], results: [], nodes: [], edges: [], stats: {}, summary: {}, plan: null, counts: {}, status: {}, overview: {}, scope: [], ok: true }
const anyFn = () => vi.fn(async () => ({ ...RICH }))
vi.mock('@/services/semantic-asset-service', () => ({
  semanticAssetService: new Proxy({}, { get: () => anyFn() }),
}))

describe('compGraphMermaid 层级渲染', () => {
  const nodes = [
    { id: 'c0', name: 'Root Comp', fileCount: 3, level: 'L1', parentId: '', change: { added: 0, modified: 1, deleted: 0 } },
    { id: 'c1', name: 'Kid A', fileCount: 2, level: 'L0', parentId: 'c0', change: { added: 0, modified: 0, deleted: 0 } },
    { id: 'c2', name: 'Kid B', fileCount: 1, level: 'L0', parentId: 'c0', change: { added: 2, modified: 0, deleted: 0 } },
    { id: 'c3', name: 'Orphan', fileCount: 1, level: 'L0', parentId: 'ghost', change: { added: 0, modified: 0, deleted: 0 } },
  ]

  it('父组件收子组件为 subgraph, 悬挂子平铺', () => {
    const { code, idMap } = compGraphMermaid(nodes as never, [])
    expect(code).toContain('subgraph sg')
    expect(code).toContain('"Root Comp"')
    const sgBlock = code.slice(code.indexOf('subgraph'), code.indexOf('end'))
    expect(sgBlock).toContain('Kid A')
    expect(sgBlock).toContain('Kid B')
    // 父节点本体也在 cluster 内
    expect(sgBlock).toContain('Root Comp')
    // 悬挂子(ghost 父不存在)平铺在 cluster 外
    const afterEnd = code.slice(code.indexOf('end'))
    expect(afterEnd).toContain('Orphan')
    expect(Object.keys(idMap)).toHaveLength(4)
  })

  it('dependsOn 边映射到编码 id, 变更 class 附着', () => {
    const { code } = compGraphMermaid(nodes as never, [{ from: 'c0', to: 'c1' }, { from: 'c0', to: 'nope' }])
    expect(code).toMatch(/n\d+ --> n\d+/)
    expect(code).not.toMatch(/nope/)
    expect(code).toContain('n0:::modified')
    expect(code).toContain('n2:::added')
    expect(code).toContain('n1:::comp')
        expect(code).toContain('classDef comp fill:#2a2b3d,stroke:#cba6f7')
    expect(code).toContain('classDef added fill:#24382e,stroke:#a6e3a1')
  })
})

describe('fileGraphMermaid', () => {
  it('imports 边+变更徽标+无变更无 class', () => {
    const nodes = [
      { id: 'a.py', name: 'a.py', change: 'added' },
      { id: 'b.py', name: 'b.py', change: '' },
    ] as never[]
    const { code } = fileGraphMermaid(nodes, [{ from: 'a.py', to: 'b.py' }])
    expect(code).toContain('graph LR')
    expect(code).toContain('[新增]')
    expect(code).toContain('-->')
    expect(code).toContain('n0:::added')
    expect(code).toContain('n1:::file')     // 无变更挂基础配色
    expect(code).not.toContain('n1:::added') && expect(code).not.toContain(':::file,')
  })
})

describe('CompGraphWorkspace 挂载冒烟', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
    vi.clearAllMocks()
  })
  ;(globalThis as any).ResizeObserver =
    (globalThis as any).ResizeObserver ||
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    }

  const tick = () => new Promise((r) => setTimeout(r, 10))

  async function mountWs(props: Record<string, unknown> = {}) {
    const { default: CompGraphWorkspace } = await import('@/components/assets/comp-graph/CompGraphWorkspace.vue')
    const pinia = createPinia()
    setActivePinia(pinia)
    const i18n = createI18n({ legacy: false, locale: 'zh', missingWarn: false, fallbackWarn: false, messages: { zh: {} } })
    const el = document.createElement('div')
    document.body.appendChild(el)
    const app = createApp(CompGraphWorkspace, props)
    app.use(pinia)
    app.use(i18n)
    const vm = app.mount(el)
    return { app, el, vm }
  }

  it('空数据挂载不崩溃且渲染标题', async () => {
    const { app, el } = await mountWs({ compareData: null })
    await tick()
    await tick()
    expect(el.textContent).toContain('compGraph.title')
    app.unmount()
  })
})
