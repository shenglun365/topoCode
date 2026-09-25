/**
 * A6.2 UI 守门规则（归入 A6.2 验收）：会话流渲染面只吃统一投影。
 *
 * - 禁止 meta.kind / meta?.kind 渲染分支（卡片→item 投影在服务端完成）；
 * - 禁止按 executorType 分支渲染（执行器特有能力经 B1 能力矩阵开关；
 *   执行器「配置控件」(如 TaskCard 切换按钮)不属渲染分支, 允许存在于 TaskCard）。
 *
 * Run: cd apps/architect && npx vitest run tests/ui-item-guard.test.ts
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

// vitest 以 apps/architect 为 cwd 运行(jsdom 环境 import.meta.url 非 file 协议)
const root = resolve(process.cwd())

const RENDER_FILES = [
  'src/components/requirements/AnalysisChat.vue',
  'src/components/requirements/chat-view/panels/ChatFeedPanel.vue',
  'src/components/requirements/chat-view/panels/ChatBottomPanel.vue',
  'src/components/chat/StreamItems.vue',
  'src/components/chat/ConversationDock.vue',
]

describe('A6.2 UI 守门: 渲染面只吃统一投影', () => {
  it('会话流组件无 meta.kind 渲染分支', () => {
    for (const f of RENDER_FILES) {
      const src = readFileSync(`${root}/${f}`, 'utf-8')
      expect(src.match(/meta\??\.kind/g), `${f} 出现 meta.kind 渲染分支——卡片应由服务端投影为 item (m.item)`).toBeNull()
    }
  })

  it('会话流组件无 executorType 渲染分支(script 内事件管道除外)', () => {
    for (const f of RENDER_FILES) {
      const src = readFileSync(`${root}/${f}`, 'utf-8')
      const tpl = (src.match(/<template>[\s\S]*<\/template>/)?.[0] ?? '')
        .split('\n')
        .filter((ln) => !/set-executor|task-executor/.test(ln))  // 事件管道(配置控件转发)豁免
        .join('\n')
      expect(tpl.match(/executorType/g),
        `${f} 模板出现 executorType 渲染分支——特有能力走 B1 能力矩阵显式开关`).toBeNull()
    }
  })

  it('AnalysisChat 消息渲染经 m.item 统一投影', () => {
    const src = RENDER_FILES.map((f) => readFileSync(`${root}/${f}`, 'utf-8')).join('\n')
    expect(src).toMatch(/m\.item\?\.type/)
    // 守门规则注释在位(防后人误删)
    expect(src).toMatch(/守门|统一投影/)
  })

  it('StreamItems 组件按 item.type 开放映射(无封闭类型 if 链以外的硬编码)', () => {
    const src = readFileSync(`${root}/src/components/chat/StreamItems.vue`, 'utf-8')
    // 词汇表常量驱动(ICON/LABEL map), 不允许 item.type === 'xxx' 离散分支膨胀
    expect(src.match(/item\.type === '/g)?.length ?? 0).toBeLessThanOrEqual(1)
  })
})
