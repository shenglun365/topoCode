/** node-click 插件寻址单测：mermaid v11 各图型 id 形态(含中文类名) + plantuml data-entity-uid 主路径 + 文本兜底。 */
import { describe, expect, it } from 'vitest'
import { createNodeClickPlugin } from '../../src/plugins/node-click'

function setup(engineName: 'mermaid' | 'plantuml', inner: string): { svg: SVGSVGElement; clicks: { nodeId: string; label: string }[] } {
  const doc = new DOMParser().parseFromString(
    `<svg xmlns="http://www.w3.org/2000/svg" id="svgroot">${inner}</svg>`, 'image/svg+xml')
  const svg = doc.documentElement as unknown as SVGSVGElement
  const clicks: { nodeId: string; label: string }[] = []
  const plugin = createNodeClickPlugin()
  plugin.onAfterRender?.({
    svg, engineName, diagramType: 'test', container: { getBoundingClientRect: () => ({ left: 0, top: 0 }) } as HTMLElement,
    shared: { dragDistance: 0 }, onNodeClick: (e) => clicks.push({ nodeId: e.nodeId, label: e.label }),
  } as never)
  return { svg, clicks }
}

function clickOn(el: Element) {
  el.dispatchEvent(new MouseEvent('click', { bubbles: true }))
}

describe('node-click 寻址', () => {
  it('mermaid flowchart 三段 id → nodeId=源 id', () => {
    const { svg, clicks } = setup('mermaid', '<g id="svgroot-flowchart-n0-1"><rect/><text>订单服务</text></g>')
    clickOn(svg.querySelector('rect')!)
    expect(clicks[0]?.nodeId).toBe('n0')
  })

  it('mermaid class 中文类名(classId-名称-N) → nodeId=中文名(实探真值形态)', () => {
    const { svg, clicks } = setup('mermaid', '<g id="svgroot-classId-订单服务-0"><rect/><text>订单服务</text></g>')
    clickOn(svg.querySelector('rect')!)
    expect(clicks[0]?.nodeId).toBe('订单服务')
  })

  it('mermaid er/state 实测形态(entity-x-0 / state-x-0)命中', () => {
    const a = setup('mermaid', '<g id="svgroot-entity-sa_d_i_e_1-0"><rect/><text>sa_d_i_e_1</text></g>')
    clickOn(a.svg.querySelector('rect')!)
    expect(a.clicks[0]?.nodeId).toBe('sa_d_i_e_1')
    const b = setup('mermaid', '<g id="svgroot-state-sa_1-0"><rect/><text>sa_1</text></g>')
    clickOn(b.svg.querySelector('rect')!)
    expect(b.clicks[0]?.nodeId).toBe('sa_1')
  })

  it('plantuml data-entity-uid 主路径(FE 注入后)命中资产 id', () => {
    const { svg, clicks } = setup('plantuml',
      '<g data-entity-uid="sa-d-i-e-1" data-qualified-name="订单服务"><rect/><text>订单服务</text></g>')
    clickOn(svg.querySelector('rect')!)
    expect(clicks[0]?.nodeId).toBe('sa-d-i-e-1')
    expect(clicks[0]?.label).toBe('订单服务')
  })

  it('无寻址元素 → 文本兜底 txt: 前缀(降级路径)', () => {
    const { svg, clicks } = setup('plantuml', '<g><rect/><text>状态同步</text></g>')
    clickOn(svg.querySelector('rect')!)
    expect(clicks[0]?.nodeId).toBe('txt:状态同步')
  })

  it('非节点 id(actor 生命线)不误报为节点', () => {
    const { svg, clicks } = setup('mermaid', '<line id="actor0"/>')
    clickOn(svg.querySelector('line')!)
    expect(clicks).toHaveLength(0)   // line 无文本祖先 → 无兜底可报
  })
})
