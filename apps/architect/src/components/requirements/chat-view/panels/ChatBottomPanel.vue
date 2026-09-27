<script setup lang="ts">

/** MS6-W3-S2 自 AnalysisChat 模板整块迁出(逐行未动)；状态经 WS_KEY 注入。 */

import { computed, nextTick, onMounted, onUnmounted, provide, reactive, ref, watch } from 'vue'
import { DocumentTextIcon, ArrowPathIcon, PaperAirplaneIcon, ChatBubbleLeftRightIcon, PencilSquareIcon, SparklesIcon, BookOpenIcon, CheckIcon, QuestionMarkCircleIcon, ClipboardDocumentCheckIcon, ClipboardDocumentIcon, TrashIcon, CubeTransparentIcon, BoltIcon, AdjustmentsHorizontalIcon, ChevronDownIcon, ChevronRightIcon, StopIcon, ArrowTopRightOnSquareIcon, WrenchScrewdriverIcon, XMarkIcon, ExclamationCircleIcon, AtSymbolIcon, CpuChipIcon } from '@heroicons/vue/24/outline'
import AssetsPanel from '@/components/chat/AssetsPanel.vue'
import CtxUsageChip from '@/components/chat/CtxUsageChip.vue'
import { useI18n } from 'vue-i18n'
import type { CtxUsage } from '../../../../types'
import { useChatWs } from '../key'

// 父层 v-bind="props" 全量下传, 本组件仅声明消费的子集——其余(turns/
// analysisMode 等状态经 useChatWs 注入流动, 不走 props); 多根 fragment 无法
// 自动继承 attrs, 显式关闭以消 extraneous non-props 警告(cv-261)。
defineOptions({ inheritAttrs: false })

const props = defineProps<{
  busy?: boolean
  ctxUsage?: CtxUsage | null
  toolTrail?: any[]
  boundExecutorId?: string
  convId?: string
  diagramSkill?: boolean
  executors?: Array<{ id: string; type?: string; default?: boolean }>
  readOnly?: boolean
  showAssetsPanel?: boolean
}>()
const emit = defineEmits<{
  'toggle-diagram-skill': [v: boolean]
  stop: []
}>()
const { t } = useI18n()
const {
  LOCAL_CMD_LIST,
  activeTask,
  autoResize,
  canDigest,
  cancelDeleteTurn,
  clarifyForced,
  clarifyTitle,
  cmdFilter,
  cmdMenuOpen,
  confirmDeleteTurn,
  deletePending,
  digestMode,
  effectiveRoute,
  executorFull,
  executorLabel,
  input,
  inputPlaceholder,
  inputRef,
  isolatedOn,
  isolatedTitle,
  onInputKeydown,
  pickCmd,
  pickExecutor,
  pickRoute,
  quickOn,
  quickTitle,
  routeBtnClass,
  routeDetail,
  routeMenuOpen,
  routeOverride,
  send,
  taskTitleOf,
  toggleClarifyMode,
  toggleDigestMode,
  toggleIsolated,
  toggleQuickMode,
  trailOpen,
} = useChatWs()
</script>

<template>
    <div class="flex items-center gap-1 border-t border-ctp-surface0 px-2.5 py-1.5 shrink-0">
      <!-- 快捷挡直切(闪电): 选中=蓝色填充 / 未选中=置灰半透明(悬停恢复); 空白对话禁用(title 说明原因) -->
      <button
        class="btn btn-xs !px-1.5"
        :class="quickOn ? 'btn-blue' : 'btn-ghost opacity-50 hover:opacity-100'"
        :title="quickTitle"
        @click="toggleQuickMode"
      >
        <BoltIcon class="w-3.5 h-3.5" />
      </button>
      <!-- 需求澄清挡位(cv-190): 自动(缺口驱动, 置灰) / 强制(先问后落卡, 高亮) -->
      <button
        class="btn btn-xs !px-1.5"
        :class="clarifyForced ? 'btn-teal' : 'btn-ghost opacity-50 hover:opacity-100'"
        :title="clarifyTitle"
        @click="toggleClarifyMode"
      >
        <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" /></svg>
      </button>
      <!-- worktree 隔离挡位(cv-202/cv-203): 关(缺省, 置灰) / 开(高亮)——
           开关状态走悬停 tooltip(直显文字占工具栏空间, 用户裁决) -->
      <button
        class="btn btn-xs !px-1.5"
        :class="isolatedOn ? 'btn-blue' : 'btn-ghost opacity-50 hover:opacity-100'"
        :title="isolatedTitle"
        @click="toggleIsolated"
      >
        <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M16 3h5v5" /><path d="M8 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-5" /><path d="M21 3l-9 9" /></svg>
      </button>
      <!-- 语境摘要(仅转达语境): 选史 → 生成摘要 → 随转达下发执行器 -->
      <button
        v-if="canDigest"
        class="btn btn-xs !px-1.5"
        :class="digestMode ? 'btn-teal' : 'btn-ghost'"
        title="语境摘要(/选摘) — 选取会话历史生成摘要, 随转达发给执行器"
        @click="toggleDigestMode"
      >
        <ClipboardDocumentIcon class="w-3.5 h-3.5" />
      </button>
      <!-- 工具条: 纯 icon(悬停 title 提示); 动作均可用 /命令 触达(见命令浮层) -->
      <button
        class="btn btn-xs !px-1.5"
        :class="props.diagramSkill ? 'btn-blue' : 'btn-ghost'"
        :disabled="busy"
        :title="`${t('requirement.chat.diagramSkill')} — /绘图`"
        @click="emit('toggle-diagram-skill', !props.diagramSkill)"
      >
        <svg
          class="w-3.5 h-3.5"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.8"
          stroke-linecap="round"
          stroke-linejoin="round"
        ><path d="M3 3h18v18H3z" /><path d="M3 9h18" /><path d="M3 15h18" /><path d="M9 3v18" /></svg>
      </button>
      <slot name="toolbar-extra" />
      <!-- v2 语境路由(发起者感知自动变 + 菜单单次翻转): 靠右加宽, 同钮显示当前执行器完整名称 -->
      <div class="relative shrink-0 ml-auto">
        <button
          class="btn btn-xs gap-1 !px-2 max-w-[200px]"
          :class="routeBtnClass"
          :title="routeDetail(effectiveRoute) + '（点击切换）；执行器选择见菜单底部'"
          @click="routeMenuOpen = !routeMenuOpen"
        >
          <AtSymbolIcon class="w-3.5 h-3.5 shrink-0" />
          <span
            class="truncate text-[10px] font-mono"
            :class="props.boundExecutorId ? 'text-ctp-teal' : 'opacity-70'"
          >{{ executorLabel }}</span>
        </button>
        <div
          v-if="routeMenuOpen"
          class="absolute bottom-full right-0 z-50 mb-1 w-72 flex-col gap-1 rounded-lg border border-ctp-surface1 bg-ctp-mantle p-1.5 shadow-lg flex"
          @mouseleave="routeMenuOpen = false"
        >
          <div class="px-1.5 pt-0.5 text-[9px] uppercase tracking-wide text-ctp-overlay0">回复对象（单次, 发送后复位）</div>
          <button
            class="w-full rounded px-2 py-1 text-left text-[11px] transition-colors hover:bg-ctp-surface0"
            :class="effectiveRoute.kind === 'architect' && !routeOverride ? 'bg-ctp-blue/10' : ''"
            @click="pickRoute({ kind: 'architect' })"
          >
            <span class="font-mono text-ctp-sky">@architect</span>
            <span class="ml-1.5 text-ctp-subtext0">外循环(分析/设计/编排)</span>
          </button>
          <button
            v-if="activeTask"
            class="w-full rounded px-2 py-1 text-left text-[11px] transition-colors hover:bg-ctp-surface0"
            :class="effectiveRoute.kind === 'task' && effectiveRoute.taskId === activeTask.id && !routeOverride ? 'bg-ctp-blue/10' : ''"
            @click="pickRoute({ kind: 'task', taskId: activeTask.id })"
          >
            <span class="font-mono text-ctp-sky truncate">→ {{ taskTitleOf(activeTask.id) || '活跃任务' }}</span>
            <span class="ml-1.5 text-ctp-subtext0">转达（{{ activeTask.status === 'waiting_input' ? '等待回复' : '排队' }}）</span>
          </button>
          <!-- 会话执行器: 绑定后新任务卡默认使用(与 /执行 直通、模型建卡同链) -->
          <div class="mx-1 my-0.5 border-t border-ctp-surface0" />
          <div class="px-1.5 pt-0.5 text-[9px] uppercase tracking-wide text-ctp-overlay0">会话执行器（新任务卡默认）</div>
          <button
            v-for="e in (props.executors || [])"
            :key="e.id"
            class="w-full rounded px-2 py-1 text-left text-[11px] transition-colors hover:bg-ctp-surface0 flex items-center gap-1.5"
            :class="e.id === props.boundExecutorId ? 'bg-ctp-teal/10' : ''"
            @click="pickExecutor(e.id)"
          >
            <CpuChipIcon class="w-3 h-3 shrink-0 text-ctp-teal" />
            <span class="font-mono truncate">{{ executorFull(e) }}</span>
            <span class="flex-1" />
            <span
              v-if="e.id === props.boundExecutorId"
              class="chip !text-[9px] bg-ctp-teal/15 text-ctp-teal shrink-0"
            >已绑定</span>
            <span
              v-else-if="e.default"
              class="chip !text-[9px] bg-ctp-surface0/60 text-ctp-overlay0 shrink-0"
            >默认</span>
          </button>
          <div
            v-if="!(props.executors || []).length"
            class="px-2 py-1.5 text-[10px] text-ctp-overlay0"
          >注册表无启用执行器</div>
          <div class="px-1.5 pt-0.5 text-[10px] text-ctp-overlay0">
            ℹ 临时单次换引擎：输入框以 <span class="font-mono">@cline</span> 开头发送
          </div>
        </div>
      </div>
    </div>

    <!-- 知识资产面板(K2): 任务回执/里程碑沉淀清单, 检索+删除(会话中心场景移至左栏, showAssetsPanel=false 隐藏) -->
    <AssetsPanel
      v-if="props.showAssetsPanel !== false && props.convId"
      :conv-id="props.convId"
      :read-only="props.readOnly"
    />

    <div class="relative flex items-end gap-2 border-t border-ctp-surface0 p-2.5 shrink-0">
      <!-- `/` 命令提示浮层(会话指令发后端 + 会话操作本地执行) -->
      <div
        v-if="cmdMenuOpen"
        class="absolute bottom-full left-2 z-50 mb-1 w-72 flex-col gap-0.5 rounded-lg border border-ctp-surface1 bg-ctp-mantle p-1 shadow-lg flex"
      >
        <span class="px-2 pt-0.5 text-[9px] uppercase tracking-wide text-ctp-overlay0">会话操作(本地)</span>
        <button
          v-for="c in cmdFilter.filter((x) => LOCAL_CMD_LIST.includes(x))"
          :key="c.name"
          class="rounded px-2 py-1 text-left text-[11px] transition-colors hover:bg-ctp-surface0"
          @click="pickCmd(c.name)"
        >
          <span class="font-mono text-ctp-mauve">/{{ c.name }}</span>
          <span class="ml-1.5 text-ctp-subtext0">{{ c.desc }}</span>
        </button>
      </div>
      <textarea
        ref="inputRef"
        v-model="input"
        rows="2"
        class="input !py-2.5 text-xs resize-y min-h-0"
        :disabled="props.readOnly"
        :placeholder="inputPlaceholder"
        @input="autoResize"
        @keydown="onInputKeydown"
      />
      <div class="flex flex-col items-end gap-1 shrink-0">
        <!-- 空态也显示(裁决): 发送按钮正上方, 新会话 used=0 即可见 -->
        <CtxUsageChip v-if="ctxUsage" :usage="ctxUsage" />
        <button
          v-if="busy"
          class="btn btn-red !py-2.5 whitespace-nowrap"
          :title="t('requirement.chat.stop')"
          @click="emit('stop')"
        >
          <StopIcon class="w-4 h-4" />{{ t('requirement.chat.stop') }}
        </button>
        <button
          v-else
          class="btn btn-primary !py-2.5 whitespace-nowrap"
          :disabled="!input.trim() || props.readOnly"
          :title="t('coding.sendHint')"
          @click="send"
        >
          <PaperAirplaneIcon class="w-4 h-4" />{{ t('coding.send') }}
        </button>
      </div>
    </div>

    <!-- 删除消息确认弹窗(DOM) -->
    <div
      v-if="deletePending !== null"
      class="fixed inset-0 z-50 flex items-center justify-center bg-ctp-crust/60 backdrop-blur-sm p-4"
      @click.self="cancelDeleteTurn"
    >
      <div class="panel w-full max-w-xs">
        <div class="panel-header">
          <span class="flex items-center gap-2">
            <TrashIcon class="w-4 h-4 text-ctp-red" />{{ t('requirement.chat.deleteTurn') }}
          </span>
        </div>
        <div class="p-4 text-xs text-ctp-subtext1">
          {{ t('requirement.chat.deleteTurnConfirm') }}
        </div>
        <div class="flex items-center justify-end gap-2 px-4 pb-4">
          <button
            class="btn btn-sm btn-ghost"
            @click="cancelDeleteTurn"
          >
            {{ t('requirement.chat.deleteTurnCancel') }}
          </button>
          <button
            class="btn btn-sm btn-red"
            @click="confirmDeleteTurn"
          >
            {{ t('requirement.chat.deleteTurnOk') }}
          </button>
        </div>
      </div>
    </div>

    <!-- 工具轨迹浮层：防信息过载，默认收起；Teleport+fixed 避免被对话区 overflow 裁剪 -->
    <Teleport to="body">
      <div
        v-if="trailOpen"
        class="fixed inset-0 z-50 bg-black/40"
        @click="trailOpen = false"
      >
        <div
          class="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[min(520px,92vw)] max-h-[70vh] flex flex-col rounded-xl bg-ctp-base border border-ctp-surface1 shadow-2xl overflow-hidden"
          @click.stop
        >
          <div class="flex items-center gap-2 px-4 py-3 border-b border-ctp-surface0 shrink-0">
            <WrenchScrewdriverIcon class="w-4 h-4 text-ctp-blue" />
            <span class="text-sm font-semibold text-ctp-text">{{ t('requirement.chat.trail') }}</span>
            <span class="chip bg-ctp-surface0 text-ctp-subtext0 font-mono text-[10px]">{{ toolTrail?.length ?? 0 }}</span>
            <span class="flex-1" />
            <button
              class="text-ctp-overlay0 hover:text-ctp-text p-0.5"
              @click="trailOpen = false"
            >
              <XMarkIcon class="w-4 h-4" />
            </button>
          </div>
          <div class="p-3 space-y-1 overflow-y-auto">
            <div
              v-for="(it, i) in toolTrail"
              :key="`${it.tool}-${i}`"
              class="flex items-start gap-2 px-2 py-1.5 rounded-lg bg-ctp-mantle"
            >
              <span class="shrink-0 mt-0.5">
                <CheckIcon
                  v-if="it.ok === true"
                  class="w-3.5 h-3.5 text-ctp-green"
                />
                <XMarkIcon
                  v-else-if="it.ok === false"
                  class="w-3.5 h-3.5 text-ctp-red"
                />
                <ArrowPathIcon
                  v-else
                  class="w-3.5 h-3.5 text-ctp-yellow animate-spin"
                />
              </span>
              <span class="min-w-0">
                <span class="font-mono text-[11px] text-ctp-text">{{ it.tool }}</span>
                <span
                  v-if="it.summary"
                  class="block text-[10px] text-ctp-subtext0 truncate"
                  :title="it.summary"
                >{{ it.summary }}</span>
              </span>
            </div>
            <div
              v-if="!toolTrail || !toolTrail.length"
              class="text-[11px] text-ctp-overlay0 px-2 py-3"
            >
              {{ t('requirement.chat.trailEmpty') }}
            </div>
          </div>
        </div>
      </div>
    </Teleport>
</template>
