<script setup lang="ts">
/**
 * AGENTS.md 单文件编辑器（纯文件模式，2610 定型修订）。
 *
 * 对齐 Codex/Claude Code/opencode：repo 根 AGENTS.md = 项目规约唯一真相源，
 * 100% 人治 markdown。本页三件事：
 * - 编辑/保存（sha1 乐观锁，外部改动 409 提示重读）；
 * - Markdown 预览切换；
 * - 初始化（文件不存在时生成初稿；存在时 init 只给体检建议不盲改）。
 * 引擎消费（命名规约/术语表章节）由后端解析进 store 缓存，本页无管理面板。
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  ShieldCheckIcon, ArrowPathIcon, SparklesIcon,
  DocumentTextIcon, PencilSquareIcon, CheckCircleIcon,
} from '@heroicons/vue/24/outline'
import MarkdownView from '@/components/MarkdownView.vue'
import { apiGet, apiPost, apiPut } from '@/services/api-client'
import { useAppDialog } from '@/composables/useAppDialog'
import { currentProjectParams } from '@/services/project-service'

const { t } = useI18n()
const dialog = useAppDialog()

// 空文件占位 = AGENTS.md 初稿骨架。不进 i18n: vue-i18n 消息格式把 `|`
// 当复数分隔符, markdown 表格行会编译报错(Plural must have messages)。
const SCAFFOLD = [
  '# AGENTS.md',
  '',
  '## 命名规约',
  '',
  '- [场景] 规则文本',
  '',
  '## 术语表',
  '',
  '| 术语 | 别名 | 含义 |',
  '| --- | --- | --- |',
  '',
].join('\n')

const content = ref('')
const baseHash = ref('')
const exists = ref(false)
const loading = ref(true)
const saving = ref(false)
const dirty = ref(false)
const mode = ref<'edit' | 'preview'>('preview')
const initReport = ref('')

async function load(keepLocal = false) {
  loading.value = true
  try {
    const { root, project } = currentProjectParams()
    const qs = new URLSearchParams()
    if (root) qs.set('root', root)
    if (project) qs.set('project', project)
    const r = await apiGet<{ exists: boolean; content: string; hash: string }>(
      `/arch/agents-md?${qs}`)
    if (!keepLocal || !dirty.value) {
      exists.value = r.exists
      content.value = r.content
      baseHash.value = r.hash
      dirty.value = false
    }
  } catch (e) {
    initReport.value = e instanceof Error ? e.message : String(e)
  } finally { loading.value = false }
}

async function save() {
  const { root, project } = currentProjectParams()
  saving.value = true
  try {
    const r = await apiPut<{ hash: string }>('/arch/agents-md', {
      root, project, content: content.value, baseHash: baseHash.value,
    })
    baseHash.value = r.hash
    dirty.value = false
    exists.value = true
    initReport.value = t('spec.editor.saved')
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e)
    if (msg.includes('409') || msg.includes('已被外部修改')) {
      initReport.value = t('spec.editor.conflict')
      if (await dialog.confirm(t('spec.editor.conflictReload'), { danger: true })) {
        await load(true)
      }
    } else {
      initReport.value = msg
    }
  } finally { saving.value = false }
}

async function initDraft() {
  const { root, project } = currentProjectParams()
  try {
    const r = await apiPost<{
      created: boolean; lines: number; conventions: number
      glossary: number; suggestions: string[]
    }>('/arch/agents-md/init', { root, project })
    initReport.value = (r.created
      ? t('spec.editor.initDone', { lines: r.lines })
      : t('spec.editor.initCheck', { lines: r.lines })) + ' — ' + r.suggestions.join('；')
    await load()
  } catch (e) {
    initReport.value = e instanceof Error ? e.message : String(e)
  }
}

onMounted(() => load())
const lineCount = computed(() => content.value.split('\n').length)
const tooLong = computed(() => lineCount.value > 200)
</script>

<template>
  <div class="p-5 space-y-4">
    <!-- 头部 -->
    <div class="flex items-center gap-3">
      <ShieldCheckIcon class="w-5 h-5 text-ctp-peach" />
      <h2 class="text-base font-semibold">{{ t('spec.editor.title') }}</h2>
      <span class="text-[11px] text-ctp-overlay1">{{ t('spec.editor.desc') }}</span>
      <div class="ml-auto flex items-center gap-2">
        <span v-if="initReport" class="text-[11px] text-ctp-overlay1 truncate max-w-[24rem]" :title="initReport">
          {{ initReport }}
        </span>
        <button class="btn btn-sm" :disabled="loading" @click="initDraft">
          <SparklesIcon class="w-3.5 h-3.5" />
          {{ exists ? t('spec.editor.check') : t('spec.editor.init') }}
        </button>
        <button class="btn btn-sm btn-green" :disabled="!dirty || saving" @click="save">
          <CheckCircleIcon v-if="!dirty" class="w-3.5 h-3.5" />
          {{ saving ? '…' : t('common.save') }}<span v-if="dirty" class="text-ctp-yellow"> ●</span>
        </button>
      </div>
    </div>

    <!-- 工具条 -->
    <div class="flex items-center gap-2 text-[11px] text-ctp-overlay1">
      <div class="flex rounded-lg border border-ctp-surface0 overflow-hidden">
        <button
          class="px-2.5 py-1 flex items-center gap-1"
          :class="mode === 'edit' ? 'bg-ctp-surface1 text-ctp-text' : 'hover:text-ctp-text'"
          @click="mode = 'edit'"
        ><PencilSquareIcon class="w-3 h-3" />{{ t('spec.editor.edit') }}</button>
        <button
          class="px-2.5 py-1 flex items-center gap-1"
          :class="mode === 'preview' ? 'bg-ctp-surface1 text-ctp-text' : 'hover:text-ctp-text'"
          @click="mode = 'preview'"
        ><DocumentTextIcon class="w-3 h-3" />{{ t('spec.editor.preview') }}</button>
      </div>
      <span :class="tooLong ? 'text-ctp-red' : ''">
        {{ lineCount }} / 200 {{ t('spec.editor.lines') }}
      </span>
      <span v-if="dirty" class="text-ctp-yellow">{{ t('spec.editor.unsaved') }}</span>
      <span class="ml-auto">{{ t('spec.editor.contract') }}</span>
    </div>

    <!-- 主体 -->
    <div class="panel overflow-hidden">
      <p v-if="loading" class="p-4 text-xs text-ctp-overlay1">…</p>
      <textarea
        v-else-if="mode === 'edit'"
        v-model="content"
        class="w-full min-h-[34rem] p-4 text-xs font-mono bg-transparent outline-none resize-y"
        :placeholder="SCAFFOLD"
        @input="dirty = true"
      />
      <div v-else class="p-4 max-h-[34rem] overflow-auto text-xs">
        <MarkdownView :content="content" />
      </div>
    </div>

    <!-- 首次引导 -->
    <div v-if="!loading && !exists && !dirty" class="panel p-4 flex items-center gap-3">
      <ArrowPathIcon class="w-5 h-5 text-ctp-sky shrink-0" />
      <div class="text-xs text-ctp-subtext0 flex-1">{{ t('spec.editor.emptyHint') }}</div>
      <button class="btn btn-sm btn-green" @click="initDraft">
        <SparklesIcon class="w-3.5 h-3.5" />{{ t('spec.editor.init') }}
      </button>
    </div>
  </div>
</template>
