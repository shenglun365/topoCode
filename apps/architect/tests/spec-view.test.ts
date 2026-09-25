/**
 * 规约视图单源(cv-248)特征: 宽形态归一(两族字段名, 表驱动) + 分节 MD 组装
 * + 正文载荷识别; 「载荷形态决定渲染形态」的渲染面守门。
 *
 * Run: cd apps/architect && npx vitest run tests/spec-view.test.ts
 */
import { readFileSync, readdirSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import {
  assembleSpecView, normalizeSpec, parseSpecPayload, SPEC_FIELDS,
} from '../src/services/spec-view'

const root = resolve(process.cwd())

describe('spec-view 归一化(表驱动, 两族字段名)', () => {
  it('传输载荷形态(requirementMd 系) → 快照规范形', () => {
    const p = normalizeSpec({
      title: '环境搭建', requirementMd: '**背景**：教学动画引擎',
      designMd: '- pnpm workspace', allowedScopeMd: '根目录\nfrontend/',
      acceptanceMd: '安装成功', estMin: 30, priority: 'P1',
    })
    expect(p.desc).toBe('**背景**：教学动画引擎')
    expect(p.design).toBe('- pnpm workspace')
    expect(p.allowedScope).toEqual(['根目录', 'frontend/'])
    expect(p.acceptance).toEqual(['安装成功'])
    expect(p.estMin).toBe(30)
  })

  it('snapshot 形态(desc/allowedScope[])同样归一(单源双兼容)', () => {
    const p = normalizeSpec({
      desc: '目标x', design: '方案y', allowedScope: ['a', 'b'],
      acceptance: ['c'], assessmentSummary: '评估z',
    })
    expect(p.desc).toBe('目标x')
    expect(p.allowedScope).toEqual(['a', 'b'])
    expect(p.assessmentSummary).toBe('评估z')
  })

  it('空值/缺省字段跳过(首个非空别名生效)', () => {
    const p = normalizeSpec({ requirementMd: '', desc: '兜底生效' })
    expect(p.desc).toBe('兜底生效')
    expect(p.title).toBeUndefined()
  })
})

describe('spec-view 分节 MD 组装', () => {
  it('全字段 → 标准分节(需求目标/清单/方案/允许/禁止/验收/评估)', () => {
    const v = assembleSpecView({
      title: 'T', desc: '**背景**：x', functionalScope: ['a', 'b'],
      design: '方案', allowedScope: ['r1'], forbiddenScope: ['f1'],
      acceptance: ['c1', 'c2'], assessmentSummary: '评估', priority: 'P1',
    })
    expect(v.title).toBe('T')
    expect(v.priority).toBe('P1')
    expect(v.body).toContain('## 需求目标\n\n**背景**：x')   // 字段值 MD 保留
    expect(v.body).toContain('## 需求目标清单\n\n- a\n- b')
    expect(v.body).toContain('## 方案\n\n方案')
    expect(v.body).toContain('## 允许改动范围\n\n- r1')
    expect(v.body).toContain('## 禁止改动\n\n- f1')
    expect(v.body).toContain('## 验收标准\n\n1. c1\n2. c2')
    expect(v.body).toContain('## 评估摘要')
    expect(v.hasBody).toBe(true)
  })

  it('空载荷 → hasBody=false(不渲染空视图)', () => {
    expect(assembleSpecView({}).hasBody).toBe(false)
    expect(assembleSpecView({}).body).toBe('')
  })
})

describe('正文规约载荷识别(字段签名)', () => {
  it('规约 schema JSON 围栏认领(≥3 字段命中)', () => {
    const p = parseSpecPayload(
      '```json\n{"title": "T", "requirementMd": "目标xxx", "acceptanceMd": "验收"}\n```')
    expect(p).toBeTruthy()
    expect(p?.title).toBe('T')
  })

  it('普通 JSON/非规约围栏不认领', () => {
    expect(parseSpecPayload('```json\n{"a": 1, "b": 2, "nodes": []}\n```')).toBeNull()
    expect(parseSpecPayload('```bash\npnpm install\n```')).toBeNull()
    expect(parseSpecPayload('')).toBeNull()
  })

  it('字段签名单源冻结(SPEC_FIELDS 与后端 _SPEC_FIELD_ALIASES 同构契约)', () => {
    expect(SPEC_FIELDS).toContain('requirementMd')
    expect(SPEC_FIELDS).toContain('allowedScopeMd')
    expect(SPEC_FIELDS.length).toBeGreaterThanOrEqual(11)
  })
})

describe('渲染面守门(载荷形态决定渲染形态)', () => {
  const dir = resolve(root, 'src/components/requirements/chat-view')
  const chat = readFileSync(`${root}/src/components/requirements/AnalysisChat.vue`, 'utf-8')
    + readdirSync(dir).filter((f) => f.endsWith('.ts'))
      .map((fl) => readFileSync(resolve(dir, fl), 'utf-8')).join('\n')

  it('specCard 与正文草稿视图共用单源(不内联重复组装)', () => {
    expect(chat.includes("from '@/services/spec-view'")).toBe(true)
    expect(chat.includes('assembleSpecView(p,')).toBe(true)
    // 旧内联分节实现退役(节标题组装只允许出现在 spec-view 单源)
    expect(!chat.includes("sections.push(`## 需求目标"), '旧内联分节未退役').toBe(true)
  })

  it('正文规约草稿视图存在且正文分支排除(防双渲染)', () => {
    expect(chat.includes('specDraftIdx')).toBe(true)
    expect(chat.includes('specDraftView')).toBe(true)
    expect(chat.includes("&& m.item?.type !== 'choices'")).toBe(true)
  })

  it('识别实现不得回流组件(单源纪律)', () => {
    const specView = readFileSync(`${root}/src/services/spec-view.ts`, 'utf-8')
    expect(specView.includes('SIGNATURE_MIN_HITS')).toBe(true)
    expect(specView.includes('_ALIASES')).toBe(true)
  })
})
