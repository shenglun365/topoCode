<script setup lang="ts">
/**
 * 需求草稿停靠面板（批C 骨架）：草稿列表 + md 编辑器（编辑/分栏/预览）。
 * 预览支持 mermaid/plantuml/dot 图表块渲染（纯文本则纯文本预览）。
 * AI 工具条（批D）、diff 采纳流（批E）、发布（批F）后续批次接入。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  DocumentTextIcon, PlusIcon, TrashIcon, ArrowPathIcon,
  PencilSquareIcon, EyeIcon, Squares2X2Icon, ArchiveBoxIcon,
  SparklesIcon, ChevronRightIcon,
} from '@heroicons/vue/24/outline'
import { useAppDialog } from '@/composables/useAppDialog'
import MarkdownView from '@/components/MarkdownView.vue'
import DiagramCard from '@/components/diagram/DiagramCard.vue'
import { parseMessageBlocks } from '@/services/parse-message-blocks'
import { renderDiagram } from '@/services/topo-render'
import { semanticAssetService } from '@/services/semantic-asset-service'
import { reqDraftService, type ReqDraft } from '@/services/req-draft-service'

const { t } = useI18n()
const dialog = useAppDialog()

// ---- 列表与当前草稿 ----
const drafts = ref<ReqDraft[]>([])
const current = ref<ReqDraft | null>(null)
const loading = ref(false)
const saving = ref(false)
const dirty = ref(false)
/** 编辑缓冲（title/contentMd 本地编辑，保存落库）。 */
const titleDraft = ref('')
const contentDraft = ref('')

async function loadList(keepId?: string) {
  loading.value = true
  try {
    drafts.value = await reqDraftService.list()
    const target = keepId
      ? drafts.value.find((d) => d.id === keepId)
      : (drafts.value.find((d) => d.status === 'editing') ?? drafts.value[0])
    if (target) await openDraft(target)
    else current.value = null
  } finally {
    loading.value = false
  }
}

async function openDraft(d: ReqDraft) {
  if (dirty.value && current.value && !(await dialog.confirm(t('draft.unsavedConfirm')))) return
  loading.value = true
  try {
    current.value = await reqDraftService.get(d.id) ?? null
    titleDraft.value = current.value?.title ?? ''
    contentDraft.value = current.value?.contentMd ?? ''
    dirty.value = false
  } finally {
    loading.value = false
  }
}

async function createDraft() {
  const d = await reqDraftService.create({ title: t('draft.untitled') })
  await loadList(d.id)
}

async function saveDraft() {
  if (!current.value || current.value.status === 'archived') return
  saving.value = true
  try {
    current.value = await reqDraftService.update(current.value.id, {
      title: titleDraft.value, contentMd: contentDraft.value,
    })
    dirty.value = false
    const idx = drafts.value.findIndex((x) => x.id === current.value!.id)
    if (idx >= 0) drafts.value[idx] = { ...drafts.value[idx], ...current.value }
  } finally {
    saving.value = false
  }
}

async function removeDraft() {
  if (!current.value) return
  if (!(await dialog.confirm(t('draft.deleteConfirm', { title: current.value.title || t('draft.untitled') }), { danger: true }))) return
  await reqDraftService.remove(current.value.id)
  await loadList()
}

/** 续写：归档草稿复制副本继续编写。 */
async function copyDraft() {
  if (!current.value) return
  const cp = await reqDraftService.copy(current.value.id)
  await loadList(cp.id)
}

const archived = computed(() => current.value?.status === 'archived')

// ---- AI 处理（批D）：单轮对话+多轮工具；产物落 lastProposedMd（diff 比对批E 接入） ----
const aiBusy = ref(false)
const aiStatus = ref('')
const aiInstruction = ref('')
let aiJobTimer: ReturnType<typeof setInterval> | null = null

async function runAi(preset: 'generate' | 'review' | 'relate' | 'custom') {
  if (!current.value || aiBusy.value || archived.value) return
  if (preset === 'custom' && !aiInstruction.value.trim()) return
  if (dirty.value) await saveDraft()   // AI 上下文=已保存的 contentMd
  aiBusy.value = true
  aiStatus.value = t('draft.ai.submitting')
  try {
    const r = await reqDraftService.runAi(current.value.id, {
      preset, instruction: preset === 'custom' ? aiInstruction.value.trim() : undefined,
    })
    const jobId = r?.job?.id
    if (!jobId || (!r?.started && r?.reason !== 'already_running')) {
      aiStatus.value = t('draft.ai.submitFailed')
      return
    }
    await new Promise<void>((resolve) => {
      aiJobTimer = setInterval(async () => {
        try {
          const j = await semanticAssetService.getJob(jobId)
          if (!j || j.state === 'done') { resolve() }
          else if (j.state === 'failed' || j.state === 'cancelled' || j.state === 'lost') {
            aiStatus.value = t('draft.ai.failed')
            resolve()
          } else {
            aiStatus.value = t('draft.ai.running', { current: j.result?.summary || j.state })
          }
        } catch { /* 轮询失败静默 */ }
      }, 2000)
    })
    if (aiJobTimer) { clearInterval(aiJobTimer); aiJobTimer = null }
    // 完成：拉取草稿（lastProposedMd 已更新）
    current.value = await reqDraftService.get(current.value.id) ?? current.value
    aiStatus.value = current.value.lastProposedMd ? t('draft.ai.done') : t('draft.ai.failed')
  } catch (e) {
    aiStatus.value = e instanceof Error && e.message ? e.message : t('draft.ai.submitFailed')
  } finally {
    if (aiJobTimer) { clearInterval(aiJobTimer); aiJobTimer = null }
    aiBusy.value = false
  }
}

const proposedOpen = ref(false)

// ---- 编辑/预览 ----
type ViewMode = 'edit' | 'split' | 'preview'
const viewMode = ref<ViewMode>('split')

interface PreviewBlock {
  kind: 'text' | 'mermaid' | 'plantuml' | 'diagram' | 'dot'
  text?: string
  code?: string
  schema?: unknown
}
/** 预览块序列：```mermaid/plantuml/diagram 围栏拆出渲染；dot 走 plantuml 服务端通道。 */
const previewBlocks = computed<PreviewBlock[]>(() => {
  const src = contentDraft.value || ''
  const out: PreviewBlock[] = []
  // dot 围栏独立拆（parse-message-blocks 未覆盖 dot）
  const DOT_RE = /```dot[ \t]*\r?\n([\s\S]*?)```/g
  const dotSpans: [number, number, string][] = []
  let m: RegExpExecArray | null
  while ((m = DOT_RE.exec(src))) dotSpans.push([m.index, m.index + m[0].length, m[1]])
  let cursor = 0
  for (const blocks of parseMessageBlocks(src)) {
    const kind = blocks.type
    const text = blocks.type === 'text' ? blocks.text : ''
    // 在 text 块内找 dot 围栏（按位置切分）
    if (kind === 'text') {
      const absStart = src.indexOf(text, cursor)
      let localCursor = 0
      for (const [s, e, code] of dotSpans.filter(([s]) => s >= absStart && s < absStart + text.length)) {
        const rel = s - absStart
        const before = text.slice(localCursor, rel)
        if (before.trim()) out.push({ kind: 'text', text: before })
        out.push({ kind: 'dot', code })
        localCursor = e - absStart
      }
      const rest = text.slice(localCursor)
      if (rest.trim()) out.push({ kind: 'text', text: rest })
      cursor = absStart + text.length
    } else if (kind === 'diagram') {
      out.push({ kind: 'diagram', schema: blocks.schema })
    } else {
      out.push({ kind, code: blocks.code })
    }
  }
  return out
})

/** dot 块渲染（PlantUML 服务端原生支持 GraphViz DOT；失败降级代码块）。 */
const dotSvgs = ref<Record<number, string>>({})
watch(previewBlocks, async (blocks) => {
  for (let i = 0; i < blocks.length; i++) {
    const b = blocks[i]
    if (b.kind !== 'dot' || !b.code) continue
    try {
      dotSvgs.value[i] = await renderDiagram('plantuml', b.code.trim())
    } catch {
      dotSvgs.value[i] = ''
    }
  }
}, { immediate: true })

function fmtTime(ts: number): string {
  return ts ? new Date(ts).toLocaleString() : ''
}

onMounted(() => { void loadList() })
</script>

<template>
  <div class="flex h-full min-h-0 flex-col">
    <!-- 顶栏：标题 + 保存 + 视图切换 -->
    <div class="flex shrink-0 items-center gap-1.5 border-b border-ctp-surface0 px-2 py-1.5">
      <input
        v-model="titleDraft"
        class="input !py-0.5 !px-2 !text-xs min-w-0 flex-1"
        :placeholder="t('draft.untitled')"
        :disabled="archived"
        @input="dirty = true"
      >
      <span v-if="archived" class="chip bg-ctp-surface0 text-ctp-overlay1 !text-[9px] shrink-0">{{ t('draft.archived') }}</span>
      <span v-else-if="dirty" class="text-[9px] text-ctp-peach shrink-0">{{ t('draft.dirty') }}</span>
      <button
        class="btn btn-xs" :class="dirty ? 'btn-blue' : 'btn-ghost'"
        :disabled="archived || !dirty || saving"
        title="Ctrl/⌘+S" @click="saveDraft"
      ><ArrowPathIcon class="h-3 w-3" :class="saving ? 'animate-spin' : ''" />{{ t('common.save') }}</button>
      <div class="flex items-center overflow-hidden rounded-md border border-ctp-surface1">
        <button
          v-for="vm in (['edit', 'split', 'preview'] as const)" :key="vm"
          class="px-1.5 py-0.5 text-[10px]"
          :class="viewMode === vm ? 'bg-ctp-surface0 text-ctp-text' : 'text-ctp-overlay1 hover:text-ctp-subtext1'"
          :title="t(`draft.view.${vm}`)"
          @click="viewMode = vm"
        >
          <PencilSquareIcon v-if="vm === 'edit'" class="h-3 w-3" />
          <Squares2X2Icon v-else-if="vm === 'split'" class="h-3 w-3" />
          <EyeIcon v-else class="h-3 w-3" />
        </button>
      </div>
    </div>

    <!-- AI 工具条：固定指令按钮 + 自定义指令（标记块指令在正文中 ```agent 围栏） -->
    <div class="flex shrink-0 items-center gap-1 border-b border-ctp-surface0 px-2 py-1">
      <SparklesIcon class="h-3.5 w-3.5 text-ctp-mauve shrink-0" />
      <button class="btn btn-xs btn-ghost" :disabled="aiBusy || archived" @click="runAi('generate')">{{ t('draft.ai.generate') }}</button>
      <button class="btn btn-xs btn-ghost" :disabled="aiBusy || archived" @click="runAi('review')">{{ t('draft.ai.review') }}</button>
      <button class="btn btn-xs btn-ghost" :disabled="aiBusy || archived" @click="runAi('relate')">{{ t('draft.ai.relate') }}</button>
      <input
        v-model="aiInstruction"
        class="input !py-0.5 !px-1.5 !text-[11px] min-w-0 flex-1"
        :placeholder="t('draft.ai.instructionPlaceholder')"
        :disabled="aiBusy || archived"
        @keydown.enter="runAi('custom')"
      >
      <button class="btn btn-xs btn-blue shrink-0" :disabled="aiBusy || archived || (aiInstruction && !aiInstruction.trim())" @click="runAi('custom')">{{ t('draft.ai.run') }}</button>
    </div>
    <div v-if="aiBusy || aiStatus" class="shrink-0 px-2 py-0.5 text-[10px]" :class="aiBusy ? 'text-ctp-sky' : 'text-ctp-overlay1'">
      {{ aiBusy ? t('draft.ai.running', { current: aiStatus }) : aiStatus }}
    </div>

    <div class="flex min-h-0 flex-1">
      <!-- 左：草稿列表（替换原对话列表） -->
      <div class="flex w-44 shrink-0 flex-col border-r border-ctp-surface0">
        <button
          class="m-1.5 flex items-center gap-1 rounded-md border border-dashed border-ctp-surface1 px-2 py-1 text-[11px] text-ctp-overlay1 hover:border-ctp-blue/50 hover:text-ctp-text"
          @click="createDraft"
        ><PlusIcon class="h-3 w-3" />{{ t('draft.newDraft') }}</button>
        <div class="min-h-0 flex-1 overflow-y-auto px-1.5 pb-1.5">
          <div
            v-for="d in drafts" :key="d.id"
            class="group mb-0.5 cursor-pointer rounded px-1.5 py-1"
            :class="current?.id === d.id ? 'bg-ctp-surface0/80' : 'hover:bg-ctp-surface0/40'"
            @click="openDraft(d)"
          >
            <div class="flex items-center gap-1">
              <DocumentTextIcon class="h-3 w-3 shrink-0" :class="d.status === 'archived' ? 'text-ctp-overlay0' : 'text-ctp-blue'" />
              <span class="min-w-0 flex-1 truncate text-[11px]" :class="d.status === 'archived' ? 'text-ctp-overlay1' : 'text-ctp-text'">{{ d.title || t('draft.untitled') }}</span>
              <button
                class="hidden shrink-0 text-ctp-overlay0 group-hover:block hover:text-ctp-red"
                :title="t('common.delete')"
                @click.stop="current = d; removeDraft()"
              ><TrashIcon class="h-3 w-3" /></button>
            </div>
            <div class="truncate text-[9px] text-ctp-overlay0" :title="d.excerpt">{{ d.excerpt || '—' }}</div>
          </div>
          <p v-if="!drafts.length && !loading" class="py-4 text-center text-[10px] text-ctp-overlay0">{{ t('draft.empty') }}</p>
        </div>
      </div>

      <!-- 右：编辑/预览 -->
      <div class="flex min-h-0 min-w-0 flex-1">
        <template v-if="current">
          <textarea
            v-if="viewMode !== 'preview'"
            v-model="contentDraft"
            class="h-full min-w-0 flex-1 resize-none bg-transparent p-3 font-mono text-[12px] leading-relaxed text-ctp-text outline-none"
            :class="viewMode === 'split' ? 'border-r border-ctp-surface0' : ''"
            :disabled="archived"
            :placeholder="t('draft.editorPlaceholder')"
            @input="dirty = true"
            @keydown.ctrl.s.prevent="saveDraft"
            @keydown.meta.s.prevent="saveDraft"
          />
          <div v-if="viewMode !== 'edit'" class="h-full min-w-0 flex-1 overflow-y-auto p-3">
            <template v-for="(b, i) in previewBlocks" :key="i">
              <MarkdownView v-if="b.kind === 'text'" :content="b.text ?? ''" />
              <DiagramCard
                v-else-if="b.kind === 'mermaid'" :title="t('draft.diagram')" headerless
                :diagrams="{ mermaid: b.code ?? '' }" :allowed-langs="['mermaid']"
              />
              <DiagramCard
                v-else-if="b.kind === 'plantuml'" :title="t('draft.diagram')" headerless
                :diagrams="{ plantuml: b.code ?? '' }" :allowed-langs="['plantuml']"
              />
              <div v-else-if="b.kind === 'dot'" class="my-2 overflow-x-auto rounded-md border border-ctp-surface0 bg-ctp-crust/60 p-2">
                <span v-if="dotSvgs[i]" class="block text-center" v-html="dotSvgs[i]" />
                <pre v-else class="overflow-x-auto text-[10px] text-ctp-subtext0">{{ b.code }}</pre>
              </div>
            </template>
            <p v-if="!previewBlocks.length" class="py-8 text-center text-[11px] text-ctp-overlay0">{{ t('draft.previewEmpty') }}</p>
          </div>
        </template>
        <div v-else class="flex flex-1 flex-col items-center justify-center gap-2 text-ctp-overlay0">
          <DocumentTextIcon class="h-8 w-8" />
          <span class="text-xs">{{ t('draft.noneSelected') }}</span>
        </div>
      </div>
    </div>

    <!-- 上一轮 AI 产物（未采纳参考：给人工修正文本/指令做参考；不进下轮上下文） -->
    <div v-if="current?.lastProposedMd" class="shrink-0 border-t border-ctp-surface0">
      <button
        class="flex w-full items-center gap-1 px-2 py-1 text-[10px] text-ctp-overlay1 hover:text-ctp-text"
        @click="proposedOpen = !proposedOpen"
      >
        <ChevronRightIcon class="h-3 w-3" :class="proposedOpen ? 'rotate-90' : ''" />
        {{ t('draft.proposed.title') }}
        <span class="text-ctp-overlay0">{{ fmtTime(current.lastProposedAt ?? 0) }}</span>
        <span class="flex-1" />
        <span class="text-ctp-overlay0">{{ t('draft.proposed.hint') }}</span>
      </button>
      <div v-if="proposedOpen" class="max-h-56 overflow-y-auto border-t border-ctp-surface0 px-3 py-2">
        <MarkdownView :content="current.lastProposedMd" />
      </div>
    </div>

    <!-- 底栏：归档草稿续写入口 -->
    <div v-if="archived" class="flex shrink-0 items-center gap-2 border-t border-ctp-surface0 px-2 py-1">
      <span class="min-w-0 flex-1 truncate text-[10px] text-ctp-overlay1" :title="current?.publishedReqId">
        {{ t('draft.publishedInfo', { req: current?.publishedReqId || '—' }) }} · {{ fmtTime(current?.updatedAt ?? 0) }}
      </span>
      <button class="btn btn-xs btn-ghost" @click="copyDraft">
        <ArchiveBoxIcon class="h-3 w-3" />{{ t('draft.continue') }}
      </button>
    </div>
  </div>
</template>
