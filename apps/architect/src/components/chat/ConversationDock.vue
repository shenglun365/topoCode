<script setup lang="ts">
/**
 * 全局会话栏(右侧 dock) —— architect 唯一对话入口(P1 决策2)。
 * 会话引擎在 conversation-store；本组件只做外观与会话切换。
 */
import { useAppDialog } from '@/composables/useAppDialog'
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
import { apiGet, apiPost } from '@/services/api-client'

const props = withDefaults(defineProps<{
  /** inline=停靠形态(页面右栏内嵌)；缺省=全局右侧悬浮 dock。 */
  inline?: boolean
  /** 新建会话的默认类型(资产地图页传 asset, 会话中心传 requirement)——首条消息创建会话时落库。 */
  defaultKind?: string
  /** 页面级技能场景(如资产地图=['extract'])：随发送注入。 */
  skillScenarios?: string[]
  /** 场景标识(sessions=会话中心 / asset=资产管理)：对话状态按场景隔离互不影响。 */
  scope?: string
}>(), { inline: false })

const { t } = useI18n()
const dialog = useAppDialog()
const router = useRouter()
const conv = useConversationStore()

const recent = ref<ConversationMeta[]>([])
const listOpen = ref(false)

// ── 会话操作(工具条): 提炼报告由服务端沉淀为会话消息 ──
const mining = ref(false)
function activeProject(): string {
  return ((conv.activeMeta as any)?.projectId || '') as string
}
async function mineActive() {
  const pid = activeProject()
  if (!conv.activeId || !pid || mining.value) return
  mining.value = true
  try {
    // 提炼报告由服务端沉淀为会话消息(统一时间线)
    await apiPost('/capabilities/mine', { conversationId: conv.activeId, project: pid })
  } catch (e) {
    await dialog.alert(e instanceof Error ? e.message : String(e))
  } finally { mining.value = false }
}
async function archiveActive() {
  if (!conv.activeId || (conv.activeMeta as any)?.status === 'archived') return
  try {
    const r = await sessionService.update(conv.activeId, { status: 'archived' } as any)
    ;(conv.activeMeta as any).status = 'archived'
    if ((r as any)?.mineableHint && activeProject()) {
      if (await dialog.confirm(t('session.mineOnEnd'))) await mineActive()
    }
  } catch { /* 保持 */ }
}

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
  if (props.scope) conv.setScope(props.scope)
  void loadRecent()
  niTimer = setInterval(() => void pollNeedsInput(), 5000)
})
onUnmounted(() => { if (niTimer) clearInterval(niTimer) })

function switchTo(meta: ConversationMeta) {
  listOpen.value = false
  void conv.openConversation(meta)
  void loadRecent()
}
function newChat() {
  listOpen.value = false
  conv.newConversation()
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

// ── PR3 角色条: 会话执行角色徽标 + 首次绑定执行角色(切换即锁定) ──
interface RoleRow { id: string; name: string; kind: string; executorId: string }
const roleNames = ref<Record<string, string>>({})
const roleSwitchOpen = ref(false)
const roleSwitchMsg = ref('')
const roleSwitching = ref(false)
const executorRoles = ref<RoleRow[]>([])
const activeRoleId = computed(() => ((conv.activeMeta as any)?.roleId as string) || 'architect')
const roleLocked = computed(() => !!((conv.activeMeta as any)?.roleLocked))
const roleSwitchEligible = computed(() =>
  activeRoleId.value === 'architect' && !!conv.activeId
  && (conv.activeMeta as any)?.status !== 'archived')

async function loadRoleNames() {
  try {
    const roles = await apiGet<RoleRow[]>('/session-roles')
    roleNames.value = Object.fromEntries(roles.map((r) => [r.id, r.name]))
  } catch { /* 徽标降级显示 id */ }
}
onMounted(() => { void loadRoleNames() })

async function openRoleSwitch() {
  roleSwitchMsg.value = ''
  try {
    const roles = await apiGet<RoleRow[]>('/session-roles')
    executorRoles.value = roles.filter((r) => r.kind === 'executor')
  } catch (e: any) {
    roleSwitchMsg.value = e?.message || String(e)
  }
  roleSwitchOpen.value = true
}

/** PR4 交接: 锁定会话换绑 → 标准化摘要生成新会话(绑目标 executor 角色)。 */
const handoffOpen = ref(false)
const handoffMsg = ref('')
const handoffBusy = ref(false)
const handoffTarget = ref('')
const handoffArchive = ref(true)
const handoffEligible = computed(() =>
  !!conv.activeId && roleLocked.value && (conv.activeMeta as any)?.status !== 'archived')

async function openHandoff() {
  handoffMsg.value = ''
  handoffTarget.value = ''
  try {
    const roles = await apiGet<RoleRow[]>('/session-roles')
    executorRoles.value = roles.filter((r) => r.kind === 'executor')
    handoffTarget.value = executorRoles.value[0]?.id || ''
  } catch (e: any) {
    handoffMsg.value = e?.message || String(e)
  }
  handoffOpen.value = true
}

async function runHandoff() {
  if (!conv.activeId || !handoffTarget.value || handoffBusy.value) return
  handoffBusy.value = true
  handoffMsg.value = ''
  try {
    const { apiPost } = await import('@/services/api-client')
    const d = await apiPost<{ newConvId: string }>(`/sessions/${conv.activeId}/handoff`,
      { targetRoleId: handoffTarget.value, archiveOrigin: handoffArchive.value })
    handoffOpen.value = false
    const list = await sessionService.list({ limit: 30, scope: 'all' })
    const meta = list.find((c) => c.id === d.newConvId)
    if (meta) await conv.openConversation(meta)
    void loadRecent()
  } catch (e: any) {
    handoffMsg.value = e?.message || String(e)
  } finally {
    handoffBusy.value = false
  }
}

async function switchRole(role: RoleRow) {
  if (!conv.activeId || roleSwitching.value) return
  roleSwitching.value = true
  roleSwitchMsg.value = ''
  try {
    const updated = await sessionService.update(conv.activeId, { roleId: role.id } as any)
    conv.activeMeta = { ...(conv.activeMeta as ConversationMeta), roleId: role.id, roleLocked: true } as ConversationMeta
    roleSwitchMsg.value = t('session.role.switched', { name: updated.title || role.name })
    roleSwitchOpen.value = false
  } catch (e: any) {
    roleSwitchMsg.value = e?.message || String(e)
  } finally {
    roleSwitching.value = false
  }
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
          <span class="min-w-0 flex-1 truncate text-ctp-text">{{ c.title }}</span>
          <span
            v-if="c.reviewState && c.reviewState !== 'read'"
            class="h-1.5 w-1.5 shrink-0 rounded-full"
            :class="c.reviewState === 'error' ? 'bg-ctp-red' : c.reviewState === 'awaiting_reply' ? 'bg-ctp-yellow' : 'bg-ctp-blue'"
          />
          <span class="shrink-0 text-[10px] text-ctp-overlay0">{{ c.msgCount }}</span>
        </button>
        <p v-if="!recent.length" class="px-2 py-3 text-center text-xs text-ctp-overlay0">
          {{ t('common.empty') }}
        </p>
      </div>
    </div>



    <!-- 会话信息面板(可折叠): 待执行方案 / 操作 / 待审提案 / 关联执行 -->
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
      <!-- PR3 角色切换对话框 -->
      <div
        v-if="roleSwitchOpen"
        class="absolute inset-0 z-50 flex items-center justify-center bg-ctp-crust/60 backdrop-blur-sm p-4"
        @click.self="roleSwitchOpen = false"
      >
        <div class="panel w-full max-w-sm">
          <div class="panel-header">
            <span>{{ t('session.role.bindTitle') }}</span>
            <button class="btn btn-xs btn-ghost" @click="roleSwitchOpen = false">
              <XMarkIcon class="w-3.5 h-3.5" />
            </button>
          </div>
          <div class="p-3 space-y-2">
            <p class="text-[11px] text-ctp-subtext0">{{ t('session.role.bindHint') }}</p>
            <p v-if="roleSwitchMsg" class="text-[11px] text-ctp-yellow break-all">{{ roleSwitchMsg }}</p>
            <button
              v-for="r in executorRoles"
              :key="r.id"
              class="w-full rounded-lg border border-ctp-surface1 px-3 py-2 text-left hover:border-ctp-blue/40 transition-colors"
              :disabled="roleSwitching"
              @click="switchRole(r)"
            >
              <div class="text-xs text-ctp-text">{{ r.name }}</div>
              <div class="text-[10px] text-ctp-subtext0">{{ t('session.role.executorOf') }}: {{ r.executorId || '—' }}</div>
            </button>
            <p v-if="!executorRoles.length" class="text-[11px] text-ctp-overlay1">
              {{ t('session.role.noExecutors') }}
            </p>
          </div>
        </div>
      </div>

      <!-- PR4 交接对话框: 生成新会话绑目标角色 -->
      <div
        v-if="handoffOpen"
        class="absolute inset-0 z-50 flex items-center justify-center bg-ctp-crust/60 backdrop-blur-sm p-4"
        @click.self="handoffOpen = false"
      >
        <div class="panel w-full max-w-sm">
          <div class="panel-header">
            <span>{{ t('session.role.handoffTitle') }}</span>
            <button class="btn btn-xs btn-ghost" @click="handoffOpen = false">
              <XMarkIcon class="w-3.5 h-3.5" />
            </button>
          </div>
          <div class="p-3 space-y-2">
            <p class="text-[11px] text-ctp-subtext0">{{ t('session.role.handoffHint') }}</p>
            <p v-if="handoffMsg" class="text-[11px] text-ctp-yellow break-all">{{ handoffMsg }}</p>
            <select v-model="handoffTarget" class="input !py-1 text-xs w-full">
              <option v-for="r in executorRoles" :key="r.id" :value="r.id">{{ r.name }}（{{ r.executorId || '—' }}）</option>
            </select>
            <label class="flex items-center gap-1.5 text-[11px] text-ctp-subtext1">
              <input v-model="handoffArchive" type="checkbox" class="accent-ctp-blue">
              {{ t('session.role.handoffArchive') }}
            </label>
            <button
              class="btn btn-primary w-full !py-1.5 text-xs"
              :disabled="!handoffTarget || handoffBusy"
              @click="runHandoff"
            >{{ handoffBusy ? t('common.saving') : t('session.role.handoffGo') }}</button>
          </div>
        </div>
      </div>

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
        :read-only="(conv.activeMeta as any)?.status === 'archived'"
        @send="(text) => { conv.send(text, { ...(props.skillScenarios?.length ? { skillScenarios: props.skillScenarios } : {}), ...(props.defaultKind ? { kind: props.defaultKind } : {}) }); onSent() }"
        @answers="(a) => { conv.sendAnswers(a); onSent() }"
        @delete-turn="conv.deleteTurn"
        @toggle-diagram-skill="conv.toggleDiagramSkill"
        @goto-requirements="onGotoRequirements"
        @convention-confirm="onConventionConfirm"
        @convention-ignore="onConventionIgnore"
        @refresh-asset="emitRefreshAsset"
        @stop="conv.stop"
      >
        <template #header-extra>
          <div v-if="conv.activeId" class="ml-auto flex shrink-0 items-center gap-1.5">
            <span
              class="chip !text-[10px]"
              :class="activeRoleId === 'architect' ? 'bg-ctp-surface0/60 text-ctp-subtext1' : 'bg-ctp-peach/15 text-ctp-peach'"
            >{{ roleNames[activeRoleId] || activeRoleId }}</span>
            <span v-if="roleLocked" class="text-[10px] text-ctp-overlay0" :title="t('session.role.lockedHint')">🔒</span>
            <button
              v-if="roleSwitchEligible"
              class="btn !py-0 !px-2 !text-[10px]"
              @click="openRoleSwitch"
            >{{ t('session.role.bind') }}</button>
            <button
              v-if="handoffEligible"
              class="btn !py-0 !px-2 !text-[10px]"
              @click="openHandoff"
            >{{ t('session.role.handoff') }}</button>
          </div>
        </template>
        <template #toolbar-extra>
          <button
            class="btn btn-xs"
            :class="titleSummarizing ? 'btn-blue' : 'btn-ghost'"
            :disabled="titleSummarizing || !conv.activeId"
            :title="t('session.actions.summarize')"
            @click="summarizeTitle"
          >{{ titleSummarizing ? '…' : t('session.actions.summarize') }}</button>
          <button
            class="btn btn-xs btn-ghost"
            :disabled="mining || !activeProject()"
            :title="t('session.mineOnEnd')"
            @click="mineActive"
          >{{ mining ? '…' : t('session.mine') }}</button>
          <button
            class="btn btn-xs btn-ghost"
            :disabled="!conv.activeId || (conv.activeMeta as any)?.status === 'archived'"
            :title="t('session.archiveHint')"
            @click="archiveActive"
          >{{ t('session.archive') }}</button>
        </template>
      </AnalysisChat>
    </div>
  </aside>
</template>
