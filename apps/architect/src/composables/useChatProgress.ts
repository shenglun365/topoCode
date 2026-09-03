import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ChatStreamEvent } from '@/services/kb-analysis-agent'

/** 工具轨迹条目(tool_call 建档、tool_result 回填结果；供浮层展示)。 */
export interface ToolTrailItem {
  tool: string
  ok?: boolean
  summary?: string
  at: number
}

/**
 * 对话等待期进度反馈（AnalysisChat 三页共用，消除「提交后零感知」）：
 * - busyLabel：底部忙碌行动态文案（提交/生成/调工具/降级同步通道各相位）；
 * - toolTrail：本轮工具轨迹（tool_call/tool_result 驱动），浮层展示；
 * - onChatEvent：页面事件处理器里调一次即可，未知事件自动忽略。
 * ⚠️ done/error 自动 reset——页面勿在 done 后再手动清（防漏清挂死文案）。
 */
export function useChatProgress() {
  const { t } = useI18n()
  const busyLabel = ref('')
  const toolTrail = ref<ToolTrailItem[]>([])

  function reset() {
    busyLabel.value = ''
    toolTrail.value = []
  }

  /** 提交时调用：立即可见「已提交」反馈（早于任何后端事件）。 */
  function begin(label?: string) {
    reset()
    busyLabel.value = label || t('requirement.chat.phaseSubmitted')
  }

  function statusLabel(ev: ChatStreamEvent): string {
    if (ev.phase === 'sync') return t('requirement.chat.phaseSync')
    if (ev.phase === 'sync_llm') return t('requirement.chat.phaseSyncLlm', { round: ev.round ?? 1 })
    if (ev.phase === 'sync_tool') {
      const pos = ev.total ? ` (${ev.idx}/${ev.total})` : ''
      return t('requirement.chat.phaseTool', { tool: ev.tool ?? '' }) + pos
    }
    if (ev.phase === 'llm_round') return t('requirement.chat.phaseLlmRound', { round: ev.round ?? 2 })
    return ev.message || busyLabel.value
  }

  function onChatEvent(ev: ChatStreamEvent) {
    if (ev.type === 'chat_start') {
      busyLabel.value = t('requirement.chat.phaseLlm')
    } else if (ev.type === 'tool_call') {
      busyLabel.value = t('requirement.chat.phaseTool', { tool: ev.tool ?? '' })
      toolTrail.value = [...toolTrail.value, { tool: ev.tool ?? '', at: Date.now() }]
    } else if (ev.type === 'tool_result') {
      const trail = [...toolTrail.value]
      for (let i = trail.length - 1; i >= 0; i--) {
        if (trail[i].tool === ev.tool && trail[i].ok === undefined) {
          trail[i] = { ...trail[i], ok: ev.ok !== false, summary: ev.summary }
          break
        }
      }
      toolTrail.value = trail
      busyLabel.value = t('requirement.chat.phaseToolDone', { tool: ev.tool ?? '' })
    } else if (ev.type === 'status') {
      busyLabel.value = statusLabel(ev)
    } else if (ev.type === 'done' || ev.type === 'error') {
      reset()
    }
  }

  return { busyLabel, toolTrail, begin, onChatEvent, reset }
}
