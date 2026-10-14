/**
 * 门禁: 全仓 .vue 模板不得引用未导入的组件(此为第 4 例同类事故的根治——
 * ProjectMainPanel/ReportMainPanel/AssetManagementWorkspace 均因"模板
 * 逐行迁移漏 import"导致 Failed to resolve component/整面板不渲染)。
 * 纯文本级扫描: 模板 PascalCase 标签 vs script 导入名/本地定义。
 * 覆盖 architect + workbench 两 app(web-core 无页面模板)。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'

const BUILTIN = new Set([
  'RouterView', 'RouterLink', 'Transition', 'TransitionGroup',
  'KeepAlive', 'Teleport', 'Suspense', 'Component',
])

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    const st = statSync(p)
    if (st.isDirectory()) walk(p, out)
    else if (p.endsWith('.vue')) out.push(p)
  }
  return out
}

function unresolvedComponents(file: string): string[] {
  const s = readFileSync(file, 'utf-8')
  const m = /<template>([\s\S]*)<\/template>\s*$/.exec(s)
  if (!m) return []
  const tags = new Set(
    [...m[1].matchAll(/<([A-Z][A-Za-z0-9]+)[\s/>]/g)].map((x) => x[1]))
  if (!tags.size) return []
  const script = s.slice(0, m.index)
  const avail = new Set<string>()
  for (const grp of script.matchAll(/import\s+\{([^}]+)\}/g))
    for (const raw of grp[1].split(','))
      avail.add(raw.trim().split(/\s+as\s+/).pop() || '')
  for (const n of script.matchAll(/import\s+([A-Z][A-Za-z0-9]+)\s+from/g))
    avail.add(n[1])
  for (const n of script.matchAll(/(?:const|function)\s+([A-Z][A-Za-z0-9]+)\s*=/g))
    avail.add(n[1])
  return [...tags].filter((t) => !avail.has(t) && !BUILTIN.has(t)).sort()
}

describe('门禁: .vue 模板组件必须已导入', () => {
  const repoRoot = resolve(__dirname, '../../..')
  const files = [
    ...walk(resolve(repoRoot, 'apps/architect/src')),
    ...walk(resolve(repoRoot, 'apps/workbench/src')),
  ]
  it('扫描覆盖两 app 的 .vue(防目录漂移)', () => {
    expect(files.length).toBeGreaterThan(50)
  })
  it('无未解析组件', () => {
    const bad: string[] = []
    for (const f of files) {
      const miss = unresolvedComponents(f)
      if (miss.length) bad.push(`${f}: ${miss.join(', ')}`)
    }
    expect(bad, bad.join('\n')).toEqual([])
  })
})
