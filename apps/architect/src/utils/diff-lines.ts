/**
 * 行级 diff（需求草稿批E：AI 产物 git diff 模式比对）。
 * LCS 动态规划，零依赖；草稿规模（数百行）O(n·m) 可接受。
 */
export interface DiffLine {
  type: 'ctx' | 'add' | 'del'
  text: string
  oldNo?: number
  newNo?: number
}

export function diffLines(oldText: string, newText: string): DiffLine[] {
  const a = (oldText || '').split('\n')
  const b = (newText || '').split('\n')
  const n = a.length
  const m = b.length
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0))
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1])
    }
  }
  const out: DiffLine[] = []
  let i = 0
  let j = 0
  let oldNo = 0
  let newNo = 0
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      out.push({ type: 'ctx', text: a[i], oldNo: ++oldNo, newNo: ++newNo })
      i++
      j++
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      out.push({ type: 'del', text: a[i], oldNo: ++oldNo })
      i++
    } else {
      out.push({ type: 'add', text: b[j], newNo: ++newNo })
      j++
    }
  }
  while (i < n) {
    out.push({ type: 'del', text: a[i], oldNo: ++oldNo })
    i++
  }
  while (j < m) {
    out.push({ type: 'add', text: b[j], newNo: ++newNo })
    j++
  }
  return out
}

/** diff 摘要（+n/-m 计数）。 */
export function diffStat(lines: DiffLine[]): { added: number; removed: number } {
  let added = 0
  let removed = 0
  for (const l of lines) {
    if (l.type === 'add') added++
    else if (l.type === 'del') removed++
  }
  return { added, removed }
}
