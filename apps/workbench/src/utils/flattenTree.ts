/** 通用树形结构扁平化工具 */

export interface TreeNode {
  id: string
  children?: TreeNode[]
  [key: string]: unknown
}

export function flattenTree<T extends TreeNode>(nodes: T[]): T[] {
  const result: T[] = []
  function walk(list: T[]) {
    for (const node of list) {
      const { children, ...rest } = node
      result.push(rest as T)
      if (children?.length) {
        walk(children as T[])
      }
    }
  }
  walk(nodes)
  return result
}

export function flattenTreeWithDepth<T extends TreeNode>(
  nodes: T[],
  depth = 0,
): Array<T & { depth: number }> {
  const result: Array<T & { depth: number }> = []
  for (const node of nodes) {
    const { children, ...rest } = node
    result.push({ ...(rest as T), depth })
    if (children?.length) {
      result.push(...flattenTreeWithDepth(children as T[], depth + 1))
    }
  }
  return result
}
