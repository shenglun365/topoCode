/**
 * 信息卡收起/展开统一状态源 —— 所有对话卡片(inline 卡 + TaskCard)共用。
 *
 * 心智模型: effective = 用户覆盖(持久化) ?? 自动规则(auto)
 * - 用户 toggle 写覆盖; 覆盖与 auto 一致时清除覆盖项(存储只留「与默认不同」的卡)
 * - 持久化: localStorage `topo:card-collapsed`, 只存 collapsed=true 的覆盖,
 *   上限 _MAX_ENTRIES 条(超限修剪最旧); 刷新/重开页面保留用户裁决
 * - 键约定: inline 卡 `msg:{m.id}`, 任务卡 `task:{taskId}`(稳定持久 id)
 */
import { reactive } from 'vue'

const STORE_KEY = 'topo:card-collapsed'
const _MAX_ENTRIES = 500

/** 覆盖表: key → true(仅记录「用户收起了默认展开的卡」或「展开了默认收起的卡」以外的
 *  收起覆盖; 展开覆盖 = 存 false, 与 auto 相异即记)。值即覆盖后的期望态。 */
type Overrides = Record<string, boolean>

let _overrides: Overrides | null = null

function _load(): Overrides {
  if (_overrides !== null) return _overrides
  try {
    const raw = localStorage.getItem(STORE_KEY)
    const parsed = raw ? JSON.parse(raw) : {}
    _overrides = (parsed && typeof parsed === 'object') ? parsed as Overrides : {}
  } catch {
    _overrides = {}
  }
  return _overrides!
}

function _persist() {
  try {
    const entries = Object.entries(_overrides || {})
    if (entries.length > _MAX_ENTRIES) {
      // 超限修剪最旧(JSON 对象键保持插入序; toggle 时 delete+重写即刷新新鲜度)
      _overrides = Object.fromEntries(entries.slice(entries.length - _MAX_ENTRIES))
    }
    localStorage.setItem(STORE_KEY, JSON.stringify(_overrides))
  } catch { /* 存储不可用(隐私模式等) → 退化为内存态 */ }
}

/** 单例状态(渲染层读用; 写操作经 toggle 保持与持久化同步)。 */
const state = reactive<Overrides>(_load())

export interface CardCollapse {
  readonly state: Overrides
  isCollapsed: (key: string, auto?: boolean) => boolean
  toggle: (key: string, auto?: boolean) => void
  /** 测试专用: 清空内存与持久化。 */
  _resetForTest: () => void
}

export function useCardCollapse(): CardCollapse {
  function isCollapsed(key: string, auto = false): boolean {
    const s = state as Overrides
    return key in s ? !!s[key] : auto
  }
  function toggle(key: string, auto = false) {
    const next = !isCollapsed(key, auto)
    if (next === auto) delete state[key]     // 与默认一致 → 清覆盖(存储最小化)
    else state[key] = next
    _overrides = { ...state }
    _persist()
  }
  function _resetForTest() {
    for (const k of Object.keys(state)) delete state[k]
    _overrides = {}
    try { localStorage.removeItem(STORE_KEY) } catch { /* ignore */ }
  }
  return { state, isCollapsed, toggle, _resetForTest }
}
