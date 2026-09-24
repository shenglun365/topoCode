/**
 * 图源归一化 —— 渲染前清理的单一实现（F2 修正）。
 *
 * 原先三份逐字近似拷贝：
 * - web-core services/render.ts（富版：实体/全角修复 + 错误报告，供 DiagramRebuildDialog）
 * - workbench composables/useDiagramRenderer.ts normalizeDiagramCode
 * - architect composables/useDiagramRenderer.ts normalizeMermaid
 * 此模块取三者 mermaid 清理规则的并集，作为渲染路径的规范版；
 * 富版（带 errors 报告）仍归 render.ts，二者语义不同（修复报告 vs 渲染前清理）。
 */

/** mermaid 源渲染前清理（规则并集） */
export function normalizeMermaidCode(code: string): string {
  return code
    // 节点名与 [ 间多余空格（mermaid 解析歧义源）
    .replace(/\b([A-Za-z_]\w*)\s+\[/g, '$1[')
    // subgraph 名与 [ 间空格
    .replace(/(\bsubgraph\s+\w+(?:\.\w+)*)\s+(\[)/g, '$1$2')
    // 节点标签内成对括号剥离
    .replace(/\[([^\]\[]*?)\(([^()]*)\)([^\]\[]*?)\]/g, '[$1$2$3]')
    // style 指令行移除
    .replace(/^\s*style\s+.*$/gm, '')
    // <br> → 空格
    .replace(/<br\s*\/?>/gi, ' ')
    // :::class 标记移除
    .replace(/:::\w+/g, '')
    // 行尾空白
    .replace(/[ \t]+$/gm, '')
}
