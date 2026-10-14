/**
 * useChat · send 域（MS6-W3 机械迁出：域内逐行原文，跨域引用 D. 前缀重写）。
 */
import { computed, nextTick, ref, watch } from 'vue'

import type { ChatDeps } from './chatTypes'

export function useChatSend(D: ChatDeps) {
  const props = D.props
  const emit = D.emit

const modelMenuOpen = ref(false)
function onModelClick() {
  modelMenuOpen.value = !modelMenuOpen.value
}
function pickModel(m: string) {
  modelMenuOpen.value = false
  if (m !== (props.executorModel || '')) emit('set-model', m)
}

/** 问询卡回复: 组装文本走既有发送通道(与手打等价, cv-247)。 */
function onChoicesReply(msgId: string, text: string) {
  D.input.choicesAnswered.add(msgId)
  D.input.clearChoiceDraft(msgId)               // 答复已提交, 草稿使命完成
  emit('send', { text })
}

function send() {
  if (!D.input.input.value.trim()) return
  if (props.busy) return
  // 本地命令拦截(绘图/方案/摘要/提炼/归档): 组件内或上抛宿主执行, 不发后端
  const local = matchLocalCmd(D.input.input.value)
  if (local) {
    runLocalCmd(local)
    D.input.input.value = ''
    cmdMenuOpen.value = false
    D.input.resetInputHeight()
    return
  }
  // 语境路由: 组装 attachTo(转达任务卡)/agent(一次性指派), 剥离内联 @执行器 前缀
  const r = D.route.effectiveRoute.value
  let text = D.input.input.value.trim()
  const ia = D.route.inlineAgent.value
  if (ia) text = text.replace(new RegExp(`^@${ia}[\\s\\u00A0]*`), '').trim()
  emit('send', {
    text,
    attachTo: r.kind === 'task' ? r.taskId : undefined,
    agent: r.kind === 'assign' ? r.agent : undefined,
  })
  D.route.routeOverride.value = null // 单次翻转复位(避免持久模式陷阱)
  // 自由回复消化在飞问询卡(cv-247: 模板可整体弃用)
  for (const m of D.input.choicesCards.value) D.input.choicesAnswered.add(String(m.id || m.item?.id || ''))
  D.input.input.value = ''
  cmdMenuOpen.value = false
  D.input.resetInputHeight()
  nextTick(() => D.input.scrollRef.value?.scrollTo({ top: D.input.scrollRef.value.scrollHeight, behavior: 'smooth' }))
}

/** 本地命令(前端拦截, 不发后端): 会话操作/状态切换——与工具条按钮同动作。 */
const LOCAL_CMD_LIST = [
  { name: '绘图', desc: '切换绘图增强(IR→代码)' },
  { name: '摘要', desc: '生成会话标题与摘要' },
  { name: '提炼', desc: '提炼会话为数据资产' },
  { name: '归档', desc: '结束会话(有可提炼内容时提示)' },
  { name: '选摘', desc: '选取历史生成摘要转达执行器' },
]
const cmdMenuOpen = ref(false)
const cmdFilter = computed(() => {
  const v = D.input.input.value.trim()
  if (!v.startsWith('/')) return []
  const q = v.slice(1).toLowerCase()
  return LOCAL_CMD_LIST.filter((c) => c.name.toLowerCase().startsWith(q))
})
/** 精确命中本地命令(拦截: 本地执行, 不发后端)。 */
function matchLocalCmd(v: string): string | null {
  const t = v.trim()
  if (!t.startsWith('/')) return null
  const name = t.slice(1)
  return LOCAL_CMD_LIST.some((c) => c.name === name) ? name : null
}
watch(cmdFilter, (list) => { cmdMenuOpen.value = list.length > 0 && D.input.input.value.trim().startsWith('/') })
function pickCmd(name: string) {
  D.input.input.value = `/${name}`
  cmdMenuOpen.value = false
  D.input.inputRef.value?.focus()
}
function onCmdMenuKeydown(e: KeyboardEvent) {
  if (!cmdMenuOpen.value) return
  if (e.key === 'Escape') { cmdMenuOpen.value = false; e.preventDefault() }
  else if (e.key === 'Enter' && cmdFilter.value.length === 1) {
    D.input.input.value = `/${cmdFilter.value[0].name}`
    cmdMenuOpen.value = false
    e.preventDefault()
  }
}
/** 本地命令分发: 绘图/选摘在组件内执行; 摘要/提炼/归档上抛宿主(与工具条同动作)。 */
function runLocalCmd(name: string) {
  if (name === '绘图') {
    emit('toggle-diagram-skill', !props.diagramSkill)
  } else if (name === '选摘') {
    D.digest.toggleDigestMode()
  } else {
    emit('local-cmd', name)
  }
}

  return {
    LOCAL_CMD_LIST,
    cmdFilter,
    cmdMenuOpen,
    matchLocalCmd,
    modelMenuOpen,
    onChoicesReply,
    onCmdMenuKeydown,
    onModelClick,
    pickCmd,
    pickModel,
    runLocalCmd,
    send,
  }
}
