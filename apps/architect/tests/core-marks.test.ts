/**
 * 2610 核心资产守护 · 图谱高亮纯逻辑(coreMarks)单测。
 *
 * - 三层标记分桶 + 节点匹配(asset/component/file 直等);
 * - 文件层后缀对齐(工程根前缀差异容错);
 * - 未命中 → false; 空标记 → 全 false。
 *
 * Run: cd apps/architect && npx vitest run tests/core-marks.test.ts
 */
import { describe, expect, it } from 'vitest'
import { coreNodeMatcher, coreSets, type CoreMarkLike } from '../src/components/assets/coreMarks'

const MARKS: CoreMarkLike[] = [
  { targetType: 'asset', targetId: 'sa-e-i-entity' },
  { targetType: 'component', targetId: 'comp:core/engine' },
  { targetType: 'file', targetId: 'src/core/engine.ts' },
  { targetType: 'other', targetId: 'ignored' },
]

describe('coreSets', () => {
  it('按层分桶, 未知层忽略', () => {
    const s = coreSets(MARKS)
    expect([...s.assets]).toEqual(['sa-e-i-entity'])
    expect([...s.comps]).toEqual(['comp:core/engine'])
    expect([...s.files]).toEqual(['src/core/engine.ts'])
  })
  it('空标记 → 三个空桶', () => {
    const s = coreSets([])
    expect(s.assets.size).toBe(0)
    expect(s.comps.size).toBe(0)
    expect(s.files.size).toBe(0)
  })
})

describe('coreNodeMatcher', () => {
  const isCore = coreNodeMatcher(MARKS)

  it('asset 层直等命中', () => {
    expect(isCore('sa-e-i-entity')).toBe(true)
  })

  it('component 层直等命中', () => {
    expect(isCore('comp:core/engine')).toBe(true)
  })

  it('file 层直等命中', () => {
    expect(isCore('src/core/engine.ts')).toBe(true)
  })

  it('file 层后缀对齐(带工程根前缀/分隔符两侧)', () => {
    expect(isCore('/repo/root/src/core/engine.ts')).toBe(true)
    expect(isCore('C:\\repo\\src\\core\\engine.ts')).toBe(true)
  })

  it('非核心 id / 同名前缀陷阱不误报', () => {
    expect(isCore('sa-x-x-other')).toBe(false)
    expect(isCore('src/core/engine.ts.bak')).toBe(false)   // 后缀扩展不算
    expect(isCore('src/core/engine2.ts')).toBe(false)
    expect(isCore('comp:core/other')).toBe(false)
  })

  it('空标记 → 全 false', () => {
    const m = coreNodeMatcher([])
    expect(m('sa-e-i-entity')).toBe(false)
    expect(m('src/core/engine.ts')).toBe(false)
  })
})
