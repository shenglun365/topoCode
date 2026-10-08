<script setup lang="ts">
/**
 * P2 规约统一编辑器（2610 定型）——AGENTS.md 单文件模式。
 *
 * 三层结构（原 3-tab 工作台退役）：
 * - 预览：AGENTS.md 最终内容（生成段=store 投影只读 + .topo/rules 人工段）；
 * - 编辑：.topo/rules/*.md 人工规则文件（list/读/写/删，REST 路径钳制）；
 * - 治理：命名规约/词汇表管理（NamingGovernancePanel 折叠保留，store 单源）。
 * 一键 sync 落盘 repo 根（幂等；manual_edit_conflict 询问 force）。
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  ShieldCheckIcon, DocumentTextIcon, PlusIcon, TrashIcon,
  ArrowPathIcon, ChevronDownIcon, ChevronRightIcon, CheckIcon, BookOpenIcon,
} from '@heroicons/vue/24/outline'
import MarkdownView from '@/components/MarkdownView.vue'
import NamingGovernancePanel from '@/components/assets/NamingGovernancePanel.vue'
import { apiGet, apiPost, apiDelete } from '@/services/api-client'
import { useAppDialog } from '@/composables/useAppDialog'
import { currentProjectParams } from '@/services/project-service'

const { t } = useI18n()
const dialog = useAppDialog()

const ctx = () => currentProjectParams()

// ── AGENTS.md 预览 ──
const preview = ref('')
const previewLoading = ref(false)
const syncResult = ref('')

async function loadPreview() {
  previewLoading.value = true
  try {
    const { root, project } = ctx()
    const qs = new URLSearchParams()
    if (root) qs.set('root', root)
    if (project) qs.set('project', project)
    const r = await apiGet<{ content: string }>(`/arch/agents-md/preview?${qs}`)
    preview.value = r.content
  } catch { preview.value = '' } finally { previewLoading.value = false }
}

async function syncNow() {
  const { root, project } = ctx()
  try {
    const r = await apiPost<{ changed?: boolean; status?: string }>('/arch/agents-md/sync', { root, project })
    if (r.status === 'manual_edit_conflict') {
      syncResult.value = t('spec.sync.conflict')
      if (await dialog.confirm(t('spec.sync.forceConfirm'), { danger: true })) {
        const r2 = await apiPost<{ changed: boolean }>('/arch/agents-md/sync', { root, project, force: true })
        syncResult.value = r2.changed ? t('spec.sync.done') : t('spec.sync.idle')
      }
    } else {
      syncResult.value = r.changed ? t('spec.sync.done') : t('spec.sync.idle')
    }
    await loadPreview()
  } catch (e) {
    syncResult.value = e instanceof Error ? e.message : String(e)
  }
}

// ── .topo/rules 文件管理 ──
interface RuleFile { name: string; bytes: number }
const files = ref<RuleFile[]>([])
const activeName = ref('')
const editing = ref('')
const dirty = ref(false)
const creating = ref(false)
const newName = ref('')

async function loadFiles(keep?: string) {
  const { root } = ctx()
  const qs = new URLSearchParams()
  if (root) qs.set('root', root)
  const r = await apiGet<RuleFile[]>(`/arch/rules-files?${qs}`)
  files.value = r
  if (keep && r.some((f) => f.name === keep)) { await openFile(keep); return }
  if (!keep && r.length && !activeName.value) await openFile(r[0].name)
}

async function openFile(name: string) {
  if (dirty.value && !(await dialog.confirm(t('spec.rules.unsaved')))) return
  const { root } = ctx()
  const r = await apiGet<{ name: string; content: string }>(
    `/arch/rules-files/${encodeURIComponent(name)}?root=${encodeURIComponent(root || '')}`)
  activeName.value = name
  editing.value = r.content
  dirty.value = false
  creating.value = false
}

async function saveFile() {
  const { root } = ctx()
  const name = creating.value ? newName.value.trim() : activeName.value
  if (!name || !/[\w.-]+\.md$/.test(name)) {
    await dialog.alert(t('spec.rules.nameInvalid')); return
  }
  if (!editing.value.trim()) { await dialog.alert(t('spec.rules.empty')); return }
  try {
    await apiPost('/arch/rules-files', { root, name, content: editing.value })
    creating.value = false
    dirty.value = false
    await loadFiles(name)
  } catch (e) {
    await dialog.alert(e instanceof Error ? e.message : String(e))
  }
}

async function deleteFile() {
  if (!activeName.value || creating.value) return
  if (!(await dialog.confirm(t('spec.rules.deleteConfirm', { name: activeName.value }), { danger: true }))) return
  const { root } = ctx()
  await apiDelete(`/arch/rules-files/${encodeURIComponent(activeName.value)}?root=${encodeURIComponent(root || '')}`)
  activeName.value = ''
  editing.value = ''
  await loadFiles()
}

function startCreate() {
  creating.value = true
  newName.value = ''
  editing.value = t('spec.rules.template')
  dirty.value = true
}

// ── 命名治理折叠 ──
const governanceOpen = ref(false)

onMounted(() => { loadPreview(); loadFiles() })
const previewStats = computed(() => `${preview.value.length} chars`)
</script>

<template>
  <div class="p-5 space-y-4">
    <!-- 头部: 标题 + sync -->
    <div class="flex items-center gap-3">
      <ShieldCheckIcon class="w-5 h-5 text-ctp-peach" />
      <h2 class="text-base font-semibold">{{ t('spec.unified.title') }}</h2>
      <span class="text-[11px] text-ctp-overlay1">{{ t('spec.unified.desc') }}</span>
      <div class="ml-auto flex items-center gap-2">
        <span v-if="syncResult" class="text-[11px] text-ctp-overlay1">{{ syncResult }}</span>
        <button class="btn btn-sm btn-green" @click="syncNow">
          <ArrowPathIcon class="w-3.5 h-3.5" />{{ t('spec.sync.btn') }}
        </button>
      </div>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-3">
      <!-- 左: AGENTS.md 预览(只读) -->
      <div class="panel overflow-hidden flex flex-col">
        <div class="panel-header">
          <span class="flex items-center gap-2">
            <DocumentTextIcon class="w-4 h-4 text-ctp-sky" />AGENTS.md
            <span class="chip bg-ctp-surface0 text-ctp-overlay0">{{ previewStats }}</span>
          </span>
          <span class="text-[10px] text-ctp-overlay0">{{ t('spec.preview.readonly') }}</span>
        </div>
        <div class="p-3 overflow-auto max-h-[32rem] text-xs">
          <p v-if="previewLoading" class="text-ctp-overlay1">…</p>
          <MarkdownView v-else :content="preview" />
        </div>
      </div>

      <!-- 右: .topo/rules 编辑器 -->
      <div class="panel overflow-hidden flex flex-col">
        <div class="panel-header">
          <span class="flex items-center gap-2">
            {{ t('spec.rules.title') }}
            <span class="chip bg-ctp-surface0 text-ctp-subtext0">{{ files.length }}</span>
          </span>
          <button class="btn btn-xs" @click="startCreate">
            <PlusIcon class="w-3 h-3" />{{ t('common.create') }}
          </button>
        </div>
        <div class="flex gap-px border-b border-ctp-surface0">
          <div class="w-36 shrink-0 border-r border-ctp-surface0 max-h-[32rem] overflow-auto">
            <button
              v-for="f in files" :key="f.name"
              class="w-full text-left px-2.5 py-1.5 text-[11px] font-mono truncate"
              :class="f.name === activeName && !creating ? 'bg-ctp-surface1 text-ctp-text' : 'text-ctp-subtext0 hover:text-ctp-text'"
              @click="openFile(f.name)"
            >{{ f.name }}</button>
          </div>
          <div class="flex-1 flex flex-col">
            <div v-if="creating" class="flex items-center gap-1.5 px-2 py-1.5 border-b border-ctp-surface0">
              <input v-model="newName" class="input !py-0.5 text-[11px] font-mono flex-1" placeholder="arch-style.md" />
              <CheckIcon class="w-3.5 h-3.5 text-ctp-green" />
            </div>
            <div v-else class="px-2 py-1 border-b border-ctp-surface0 text-[10px] text-ctp-overlay0 font-mono">
              {{ activeName || t('common.empty') }}<span v-if="dirty" class="text-ctp-yellow"> ●</span>
            </div>
            <textarea
              v-model="editing"
              class="flex-1 min-h-[24rem] p-2.5 text-[11px] font-mono bg-transparent outline-none resize-none"
              :placeholder="t('spec.rules.placeholder')"
              @input="dirty = true"
            />
            <div class="flex justify-end gap-2 px-2 py-1.5 border-t border-ctp-surface0">
              <button class="btn btn-xs btn-red" :disabled="!activeName || creating" @click="deleteFile">
                <TrashIcon class="w-3 h-3" />
              </button>
              <button class="btn btn-xs btn-green" :disabled="!dirty && !creating" @click="saveFile">
                {{ t('common.save') }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 命名治理(折叠) -->
    <div class="panel overflow-hidden">
      <button
        class="w-full flex items-center gap-2 px-4 py-2.5 text-sm hover:bg-ctp-surface0/50"
        @click="governanceOpen = !governanceOpen"
      >
        <component :is="governanceOpen ? ChevronDownIcon : ChevronRightIcon" class="w-4 h-4 text-ctp-overlay1" />
        <BookOpenIcon class="w-4 h-4 text-ctp-mauve" />
        <span class="font-medium">{{ t('spec.governance.title') }}</span>
        <span class="text-[11px] text-ctp-overlay1 ml-1">{{ t('spec.governance.desc') }}</span>
      </button>
      <div v-show="governanceOpen" class="border-t border-ctp-surface0">
        <NamingGovernancePanel />
      </div>
    </div>
  </div>
</template>
