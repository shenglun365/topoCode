<script setup lang="ts">
/**
 * 全局会话栏(右侧 dock) —— architect 唯一对话入口(P1 决策2)。
 * 会话引擎在 conversation-store；本组件只做外观与会话切换。
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import {
  XMarkIcon, PlusIcon, ChatBubbleLeftRightIcon, ChevronDownIcon,
  ExclamationCircleIcon, PaperAirplaneIcon, ChatBubbleOvalLeftEllipsisIcon,
  PencilSquareIcon, SparklesIcon,
} from '@heroicons/vue/24/outline'
import AnalysisChat from '@/components/requirements/AnalysisChat.vue'
import { useConversationStore } from '@/stores/conversation-store'
import { sessionService, type ConversationMeta } from '@/services/session-service'
import { busService, type NeedsInputItem } from '@/services/bus-service'
import { namingService } from '@/services/naming-service'

const props = withDefaults(defineProps<{
  /** inline=停靠形态(页面右栏内嵌)；缺省=全局右侧悬浮 dock。 */
  inline?: boolean
  /** 新建会话的默认类型(资产地图页传 asset)。 */
  defaultKind?: string
}>(), { inline: false, defaultKind: 'requirement' })

const { t } = useI18n()
const router = useRouter()
const conv = useConversationStore()

const recent = ref<ConversationMeta[]>([])
const listOpen = ref(false)

async function loadRecent() {
  try {
    // scope=all: 跨全库汇总 — 与会话中心同口径(会话管理+资产管理统一视图)
    recent.value = await sessionService.list({ limit: 30, scope: 'all' })
  } catch { /* 列表失败保持旧值 */ }
}

// ── 会话标题: 悬停 → 手动修改(行内输入框) / 自动摘要 ──
const editingTitle = ref(false)
const titleDraft = ref('')
const titleSummarizing = ref(false)
function startTitleEdit() {
  titleDraft.value = conv.activeTitle || ''
  editingTitle.value = true
}
async function saveTitle() {
  if (!editingTitle.value) return
  editingTitle.value = false
  await commitTitle(titleDraft.value)
}
async function onRenameTitle(t: string) {
  await commitTitle(t)
}
async function commitTitle(title: string) {
  title = (title || '').trim()
  if (!title || title === conv.activeTitle) return
  conv.activeTitle = title
  if (conv.activeId) {
    try { await sessionService.update(conv.activeId, { title }) } catch { /* 保存失败保持本地 */ }
    void loadRecent()
  }
}
async function summarizeTitle() {
  if (!conv.activeId || titleSummarizing.value) return
  titleSummarizing.value = true
  try {
    const updated = await sessionService.summarize(conv.activeId, true)
    conv.activeTitle = updated.title || conv.activeTitle
    void loadRecent()
  } catch { /* 摘要失败静默 */ } finally {
    titleSummarizing.value = false
  }
}
onMounted(() => {
  void loadRecent()
  niTimer = setInterval(() => void pollNeedsInput(), 5000)
})
onUnmounted(() => { if (niTimer) clearInterval(niTimer) })

function kindClass(kind: string) {
  if (kind === 'asset') return 'bg-ctp-mauve/15 text-ctp-mauve'
  if (kind === 'design') return 'bg-ctp-peach/15 text-ctp-peach'
  if (kind === 'execution') return 'bg-ctp-green/15 text-ctp-green'
  return 'bg-ctp-sky/15 text-ctp-sky'
}

function switchTo(meta: ConversationMeta) {
  listOpen.value = false
  void conv.openConversation(meta)
  void loadRecent()
}
function newChat() {
  listOpen.value = false
  conv.newConversation(props.defaultKind || 'requirement')
  void loadRecent()
}
function onGotoRequirements() {
  // 提案卡 → 会话中心定位该会话(备案文档/执行详情)
  router.push({ path: '/workbench/sessions', query: { select: conv.activeId || undefined } })
}
function onSent() { void loadRecent() }

/** dock 内「刷新资产」卡事件 → 资产地图页监听的全局事件。 */
function emitRefreshAsset(id: string) {
  window.dispatchEvent(new CustomEvent('arch:refresh-asset', { detail: id }))
}

// 命名规约提议卡(资产对话): 确认固化 / 忽略(原资产页逻辑迁至 dock)
async function onConventionConfirm(id: string) {
  try { await namingService.updateConvention(id, { status: 'active' }) } catch { /* 忽略 */ }
}
async function onConventionIgnore(id: string) {
  try { await namingService.deleteConvention(id) } catch { /* 忽略 */ }
}

// ── 需要你输入(N): agent 澄清问题应答(原 AgentWorkbench 逻辑) ──
const needsInput = ref<{ count: number; items: NeedsInputItem[] } | null>(null)
const clarifyDraft = ref('')
const clarifyBusy = ref(false)
let niTimer: ReturnType<typeof setInterval> | null = null
async function pollNeedsInput() {
  if (!conv.dockOpen) return
  try {
    needsInput.value = await busService.needsInput()
  } catch { /* broker 暂不可达 → 保持上次值 */ }
}
const pendingClarify = computed<NeedsInputItem | null>(() => {
  const items = needsInput.value?.items ?? []
  const reqId = conv.activeReqId
  return items.find((i) => i.type === 'clarify' && (!reqId || !i.reqId || i.reqId === reqId)) ?? null
})
async function answerClarify() {
  const c = pendingClarify.value
  const text = clarifyDraft.value.trim()
  if (!c || !text || clarifyBusy.value) return
  clarifyBusy.value = true
  try {
    await busService.publish('user', c.src || 'plan', 'interaction.answer',
      { replyTo: c.id, reqId: conv.activeReqId || c.reqId || '', answer: text })
    conv.turns.push({ role: 'user', content: text })
    clarifyDraft.value = ''
  } finally {
    clarifyBusy.value = false
  }
}
</script>

<template>
  <!-- 收起态: 右缘浮标(仅全局悬浮形态) -->
  <button
    v-if="!props.inline && !conv.dockOpen"
    class="fixed right-0 top-1/2 z-40 -translate-y-1/2 rounded-l-xl border border-r-0 border-ctp-surface1 bg-ctp-mantle px-1.5 py-4 text-ctp-subtext0 shadow-lg hover:text-ctp-text"
    :title="t('session.dock.open')"
    @click="conv.setDockOpen(true)"
  >
    <ChatBubbleOvalLeftEllipsisIcon class="h-5 w-5" />
  </button>

  <!-- 展开态: 全局悬浮(右缘 overlay) / inline(页面右栏停靠) -->
  <aside
    v-else-if="props.inline || conv.dockOpen"
    :class="props.inline
      ? 'relative flex h-full min-h-0 w-full flex-col bg-ctp-base'
      : 'fixed right-0 top-0 z-40 flex h-full w-[26rem] flex-col border-l border-ctp-surface0 bg-ctp-base shadow-2xl'"
  >
    <!-- 头部: 标题 + kind + 会话切换(仅悬浮形态; inline 停靠的标题编辑在对话面板 header 内) -->
    <div v-if="!props.inline" class="relative shrink-0 border-b border-ctp-surface0 px-3 py-2">
      <div class="flex items-center gap-2">
        <span class="chip shrink-0" :class="kindClass(conv.activeKind)">
          {{ t(`session.kind.${conv.activeKind}`) }}
        </span>
        <span class="group/t flex min-w-0 flex-1 items-center gap-1">
          <input
            v-if="editingTitle"
            v-model="titleDraft"
            class="input w-full min-w-0 !px-1.5 !py-0.5 text-xs"
            @click.stop
            @keydown.enter.prevent="saveTitle"
            @keydown.esc="editingTitle = false"
            @blur="saveTitle"
          >
          <template v-else>
            <span class="min-w-0 truncate text-xs font-medium text-ctp-text">
              {{ conv.activeTitle || t('session.dock.untitled') }}
            </span>
            <span
              v-if="conv.activeId"
              class="hidden shrink-0 items-center gap-0.5 group-hover/t:flex"
            >
              <button class="rounded p-0.5 text-ctp-overlay0 hover:bg-ctp-surface0 hover:text-ctp-blue" :title="t('session.actions.rename')" @click.stop="startTitleEdit">
                <PencilSquareIcon class="h-3 w-3" />
              </button>
              <button class="rounded p-0.5 text-ctp-overlay0 hover:bg-ctp-surface0 hover:text-ctp-blue" :title="t('session.actions.summarize')" @click.stop="summarizeTitle">
                <SparklesIcon class="h-3 w-3" :class="titleSummarizing ? 'animate-pulse' : ''" />
              </button>
            </span>
          </template>
        </span>
        <template v-if="!props.inline">
          <button
            class="rounded p-1 text-ctp-subtext0 hover:bg-ctp-surface0 hover:text-ctp-text"
            :title="t('session.dock.newChat')"
            @click="newChat"
          >
            <PlusIcon class="h-4 w-4" />
          </button>
          <button
            class="rounded p-1 text-ctp-subtext0 hover:bg-ctp-surface0 hover:text-ctp-text"
            :title="t('session.dock.switch')"
            @click="listOpen = !listOpen"
          >
            <ChevronDownIcon class="h-4 w-4" />
          </button>
          <button
            class="rounded p-1 text-ctp-subtext0 hover:bg-ctp-surface0 hover:text-ctp-text"
            :title="t('common.close')"
            @click="conv.setDockOpen(false)"
          >
            <XMarkIcon class="h-4 w-4" />
          </button>
        </template>
      </div>

      <!-- 会话切换浮层 -->
      <div
        v-if="listOpen"
        class="absolute left-2 right-2 top-full z-50 max-h-80 overflow-auto rounded-lg border border-ctp-surface1 bg-ctp-mantle p-1 shadow-xl"
      >
        <button
          v-for="c in recent"
          :key="c.id"
          class="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs hover:bg-ctp-surface0"
          :class="c.id === conv.activeId ? 'bg-ctp-surface0' : ''"
          @click="switchTo(c)"
        >
          <span class="chip shrink-0" :class="kindClass(c.kind)">{{ t(`session.kind.${c.kind}`) }}</span>
          <span class="min-w-0 flex-1 truncate text-ctp-text">{{ c.title }}</span>
          <span class="shrink-0 text-[10px] text-ctp-overlay0">{{ c.msgCount }}</span>
        </button>
        <p v-if="!recent.length" class="px-2 py-3 text-center text-xs text-ctp-overlay0">
          {{ t('common.empty') }}
        </p>
      </div>
    </div>

    <!-- 澄清应答横幅 -->
    <div
      v-if="pendingClarify"
      class="shrink-0 border-b border-ctp-surface0 bg-ctp-yellow/5 px-3 py-2"
    >
      <div class="flex items-start gap-1.5">
        <ExclamationCircleIcon class="mt-0.5 h-3.5 w-3.5 shrink-0 text-ctp-yellow" />
        <p class="flex-1 text-[11px] leading-relaxed text-ctp-subtext1">
          {{ pendingClarify.label || t('session.dock.clarifyPending') }}
        </p>
      </div>
      <div class="mt-1.5 flex items-center gap-1.5">
        <input
          v-model="clarifyDraft"
          class="input !py-1 flex-1 text-xs"
          :placeholder="t('session.dock.clarifyPlaceholder')"
          @keydown.enter="answerClarify"
        >
        <button
          class="btn btn-sm btn-blue shrink-0"
          :disabled="clarifyBusy || !clarifyDraft.trim()"
          @click="answerClarify"
        >
          <PaperAirplaneIcon class="h-3 w-3" />
        </button>
      </div>
    </div>

    <!-- 对话主体 -->
    <div class="min-h-0 flex-1">
      <AnalysisChat
        class="h-full"
        :turns="conv.turns"
        :busy="conv.busy"
        :busy-label="conv.busyLabel"
        :tool-trail="conv.toolTrail"
        :insert-draft="conv.insertDraft"
        :title="conv.activeTitle || t('session.dock.untitled')"
        :editable="!!conv.activeId && !conv.busy"
        :title-summarizing="titleSummarizing"
        @rename="onRenameTitle"
        @summarize-title="summarizeTitle"
        :diagram-skill="conv.diagramSkill"
        @send="(text) => { conv.send(text, conv.activeKind === 'asset' ? { skillScenarios: ['extract'] } : undefined); onSent() }"
        @answers="(a) => { conv.sendAnswers(a); onSent() }"
        @delete-turn="conv.deleteTurn"
        @toggle-diagram-skill="conv.toggleDiagramSkill"
        @goto-requirements="onGotoRequirements"
        @convention-confirm="onConventionConfirm"
        @convention-ignore="onConventionIgnore"
        @refresh-asset="emitRefreshAsset"
        @stop="conv.stop"
      />
    </div>
  </aside>
</template>
