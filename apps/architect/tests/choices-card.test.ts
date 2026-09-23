/**
 * 结构化问询卡(cv-247)特征: 回复组装纯逻辑(单源 choices-reply) +
 * 组件交互守门(三态元素/禁用绑定/单源消费——项目无 mount 依赖, 静态断言)。
 *
 * Run: cd apps/architect && npx vitest run tests/choices-card.test.ts
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { assembleReply, groupKey, requiredMissing } from '../src/services/choices-reply'
import type { ChoiceGroup, ReplyState } from '../src/services/choices-reply'

const root = resolve(process.cwd())

const GROUPS: ChoiceGroup[] = [
  { id: '1', label: '后端框架', question: 'API 层用哪个框架？',
    options: [{ id: 'A', label: 'Fastify', hint: '高性能', recommended: true },
              { id: 'B', label: 'Express' }] },
  { id: '2', label: '复现步骤', question: '问题如何复现？' },
]

const st = (over: Partial<ReplyState>): ReplyState => ({
  selections: {}, customs: {}, skipped: {}, note: '', ...over })

describe('choices-reply 组装逻辑(cv-247)', () => {
  it('点选/跳过/自定义三态组装; 跳过显式表达', () => {
    const t = assembleReply(GROUPS, st({
      selections: { '1': 'B' }, skipped: { '2': true } }))
    expect(t).toContain('后端框架: Express')
    expect(t).toContain('复现步骤: 跳过（由你决定）')
  })

  it('自定义输入覆盖点选; 补充说明附尾; 全空返回空串', () => {
    const t = assembleReply(GROUPS, st({
      selections: { '1': 'A' }, customs: { '1': 'Hono 轻量框架' },
      note: '另需兼容 pnpm' }))
    expect(t).toContain('后端框架: Hono 轻量框架（自定义）')
    expect(t).toContain('—— 另需兼容 pnpm')
    expect(assembleReply(GROUPS, st({}))).toBe('')
  })

  it('组 id 缺省按序号; 开放题组直接以 question 为标签', () => {
    const gs: ChoiceGroup[] = [{ label: '开放', question: '如何复现？' }]
    expect(groupKey(gs[0], 0)).toBe('1')
    const t = assembleReply(gs, st({ customs: { '1': '打开页面即崩' } }))
    expect(t).toBe('开放: 打开页面即崩（自定义）')
  })

  it('requiredMissing: 必答项未答计数(跳过/已答不计)', () => {
    const gs: ChoiceGroup[] = [
      { id: '1', label: 'q1', required: true,
        options: [{ id: 'A', label: 'a' }] },
      { id: '2', label: 'q2', required: true,
        options: [{ id: 'A', label: 'a' }] }]
    expect(requiredMissing(gs, st({ selections: { '1': 'A' } }))).toBe(1)
    expect(requiredMissing(gs, st({ skipped: { '2': true }, selections: { '1': 'A' } }))).toBe(0)
  })
})

describe('ChoicesCard 组件守门(A6.2 同思路, 静态断言)', () => {
  const src = readFileSync(`${root}/src/components/chat/ChoicesCard.vue`, 'utf-8')

  it('三态交互元素齐备且受 disabled/已答约束', () => {
    for (const t of ['choices-option', 'choices-custom', 'choices-skip',
                     'choices-extra', 'choices-send']) {
      expect(src.includes(`data-test="${t}"`), t).toBe(true)
    }
    // 交互全部受 disabled 或 answered 约束(禁用/已答态)
    expect(src.match(/:disabled="disabled \|\| answered\.done/g)?.length).toBeGreaterThanOrEqual(4)
  })

  it('自定义输入恒驻(每题都有, 含选择题)', () => {
    // input v-model=customs 在选项渲染之后无条件渲染(非 v-if 分支)
    expect(src.includes('v-model="customs[gid(g, i)]"')).toBe(true)
    expect(src.includes('或自定义回答…')).toBe(true)
  })

  it('组装逻辑消费单源(不内联重复实现)', () => {
    expect(src.includes("from '@/services/choices-reply'")).toBe(true)
    expect(src.includes('assembleReply')).toBe(true)
    // 组件内不得重复组装逻辑(parts.push(${label}...) 旧实现痕迹)
    expect(!src.includes('parts.push('), '组件内不得重复组装逻辑').toBe(true)
  })

  it('已答态与宿主接线: markAnswered 暴露 + reply emit', () => {
    expect(src.includes('markAnswered')).toBe(true)
    expect(src.includes("(e: 'reply', text: string)")).toBe(true)
  })

  it('缩略收起(cv-248): 收起开关+摘要行+已答自动收起', () => {
    expect(src.includes('data-test="choices-collapse"')).toBe(true)
    expect(src.includes('collapsed')).toBe(true)
    expect(src.includes("watch(() => answered.done")).toBe(true)
    expect(src.includes('groupSummary')).toBe(true)
  })
})

describe('会话流持久化守门(cv-248)', () => {
  it('choices 卡单渲染: 正文分支排除 choices(卡片即全部, 无标题文本双显)', () => {
    const chat = readFileSync(`${root}/src/components/requirements/AnalysisChat.vue`, 'utf-8')
    expect(chat.includes("m.item?.type !== 'choices'")).toBe(true)
    expect(chat.includes("m.item?.type === 'choices'")).toBe(true)
  })

  it('applyConversation 保留 item(choices 卡随会话消息持久化加载)', () => {
    const store = readFileSync(`${root}/src/stores/conversation-store.ts`, 'utf-8')
    // turns 映射显式保留 item(丢 item = 刷新后卡片降级为正文)
    expect(store.includes("item: (m as any).item")).toBe(true)
    // choices 不在气泡过滤集合(必须保留交卡片分支渲染)
    expect(store.includes("_CARD_BUBBLE_KINDS = new Set(['task_card', 'specReady', 'task_status'])")).toBe(true)
    expect(store.includes("'choices', 'task_card'")).toBe(false)
  })
})
