<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  ArrowPathIcon,
  ArrowUpIcon,
  CheckIcon,
  DocumentIcon,
  ExclamationTriangleIcon,
  FolderIcon,
  PlusIcon,
  XMarkIcon,
} from '@heroicons/vue/24/outline'
import { ipc } from '@/services/ipc'

const emit = defineEmits<{ close: []; saved: [path: string] }>()

const { t } = useI18n()

interface DirEntry {
  name: string
  isDir: boolean
  size?: number
  mtime?: number
  readable?: boolean
  writable?: boolean
}

interface DirList {
  path: string
  parent: string | null
  host?: { name?: string; ip?: string }
  readable?: boolean
  writable?: boolean
  entries: DirEntry[]
}

interface DirAnalysis {
  root: string
  name: string
  writable?: boolean
  isGitRoot?: boolean
  gitToplevel?: string | null
  gitBranch?: string | null
  isEmpty?: boolean
  hasCode?: boolean
  duplicate?: { id: string; name: string; rootPath: string; mode?: string } | null
  signatureProject?: { id: string; name: string; rootPath: string } | null
}

const dir = ref<DirList | null>(null)
const loading = ref(false)
const error = ref('')
const selectedPath = ref('')
// 路径/过滤二合一输入：输入即过滤当前列表，回车按路径跳转
const pathDraft = ref('')

const filteredEntries = computed(() => {
  const entries = dir.value?.entries ?? []
  const raw = pathDraft.value.trim()
  if (!raw) return entries
  // 兼容 Windows(\) 与 Linux(/) 分隔符：只取最后一段作为过滤片段。
  // /home/user/s 在 /home/user 下等价于过滤 "s"，可命中 soft；
  // 以分隔符结尾（如 /home/user/）表示完整路径，不过滤。
  const sepIdx = Math.max(raw.lastIndexOf('/'), raw.lastIndexOf('\\'))
  const kw = (sepIdx >= 0 ? raw.slice(sepIdx + 1) : raw).toLowerCase()
  if (!kw) return entries
  return entries.filter(e => e.name.toLowerCase().includes(kw))
})

const newDirMode = ref(false)
const newDirName = ref('')
const creating = ref(false)

const analyzing = ref(false)
const analysis = ref<DirAnalysis | null>(null)

const hostLabel = computed(() => {
  const h = dir.value?.host
  if (!h) return ''
  return h.ip ? `${h.name || ''} (${h.ip})` : (h.name || '')
})

function fullPath(name: string): string {
  return `${dir.value?.path ?? ''}/${name}`
}

async function load(path?: string) {
  loading.value = true
  error.value = ''
  const prevPath = dir.value?.path
  try {
    dir.value = await ipc.dir.list(path)
    const d = dir.value
    if (!d) return
    if (d.path !== prevPath) pathDraft.value = ''
    const cur = d.path
    const selectedInView = selectedPath.value === cur || selectedPath.value.startsWith(`${cur}/`)
    if (!selectedInView) {
      selectedPath.value = cur ?? ''
    }
  } catch (e: any) {
    error.value = e?.message || t('project.dirLoadFailed')
  } finally {
    loading.value = false
  }
}

function enter(entry: { name: string; isDir: boolean }) {
  if (!entry.isDir || !dir.value) return
  load(fullPath(entry.name))
}

function selectEntry(entry: { name: string; isDir: boolean }) {
  if (!entry.isDir || !dir.value) return
  selectedPath.value = fullPath(entry.name)
}

function selectHere() {
  if (!dir.value) return
  selectedPath.value = dir.value.path
}

function goUp() {
  if (!dir.value?.parent) return
  load(dir.value.parent)
}

function goRoot() {
  load('/')
}

function home() {
  load()
}

async function createDir() {
  const parent = dir.value?.path
  const name = newDirName.value.trim()
  if (!parent || !name) return
  creating.value = true
  error.value = ''
  try {
    await ipc.dir.create(parent, name)
    newDirName.value = ''
    newDirMode.value = false
    await load(parent)
  } catch (e: any) {
    error.value = e?.message || t('project.dirCreateFailed')
  } finally {
    creating.value = false
  }
}

async function analyzeAndConfirm() {
  const root = selectedPath.value
  if (!root) return
  analyzing.value = true
  error.value = ''
  try {
    analysis.value = await ipc.dir.analyze(root)
  } catch (e: any) {
    error.value = e?.message || t('project.dirAnalyzeFailed')
  } finally {
    analyzing.value = false
  }
}

function backToBrowse() {
  analysis.value = null
}

function confirmSelect() {
  if (!analysis.value) return
  emit('saved', analysis.value.root)
  emit('close')
}

onMounted(() => load())
</script>

<template>
  <Teleport to="body">
    <div class="dialog-overlay" @click.self="emit('close')">
      <div class="dialog-card server-dir-card">
        <div class="dialog-header">
          <span class="dialog-title">{{ t('project.dirPickerTitle') }}</span>
          <button class="dialog-close" @click="emit('close')">&times;</button>
        </div>

        <div class="server-dir-body">
          <div
            v-if="error"
            class="import-error"
          >{{ error }}</div>

          <!-- ── 浏览视图 ── -->
          <template v-if="!analysis">
            <div class="path-bar">
              <button
                class="btn btn-ghost btn-sm"
                :disabled="!dir?.parent"
                :title="t('project.dirUp')"
                @click="goUp"
              >
                <ArrowUpIcon class="w-4 h-4" />
              </button>
              <button class="btn btn-ghost btn-sm" title="/" @click="goRoot">/</button>
              <button class="btn btn-ghost btn-sm" :title="t('project.dirHome')" @click="home">~</button>
              <input
                class="input path-input"
                :value="pathDraft || dir?.path || ''"
                :placeholder="t('project.dirPathPlaceholder')"
                @input="(e: any) => pathDraft = e.target.value"
                @keyup.enter="(e: any) => load((e.target as HTMLInputElement).value)"
              >
              <button
                class="btn btn-ghost btn-sm"
                :title="t('project.dirRefresh')"
                @click="load(dir?.path)"
              >
                <ArrowPathIcon class="w-4 h-4" />
              </button>
            </div>

            <div
              v-if="dir"
              class="dir-meta"
            >
              <span
                class="perm-chip"
                :class="dir.writable ? 'perm-ok' : 'perm-no'"
              >
                {{ dir.writable ? t('project.dirWritable') : t('project.dirReadonly') }}
              </span>
              <span
                v-if="hostLabel"
                class="host-chip"
              >{{ hostLabel }}</span>
              <button
                class="btn btn-ghost btn-sm"
                :class="selectedPath === dir.path ? 'sel-active' : ''"
                @click="selectHere"
              >
                <CheckIcon class="w-3 h-3" />
                {{ selectedPath === dir.path ? t('project.dirSelected') : t('project.dirSelectCurrent') }}
              </button>
            </div>

            <div
              v-if="loading"
              class="dir-loading"
            >{{ t('common.loading') }}</div>
            <ul
              v-else-if="dir"
              class="dir-list"
            >
              <li
                v-for="e in filteredEntries"
                :key="e.name"
                class="dir-item"
                :class="selectedPath === fullPath(e.name) ? 'dir-item-sel' : ''"
                @click="selectEntry(e)"
              >
                <span class="dir-icon">
                  <FolderIcon v-if="e.isDir" class="w-4 h-4 text-accent" />
                  <DocumentIcon v-else class="w-4 h-4 text-muted" />
                </span>
                <span class="dir-name">{{ e.name }}</span>
                <span
                  v-if="e.isDir && e.writable === false"
                  class="dir-ro"
                >{{ t('project.dirReadonlyShort') }}</span>
                <button
                  v-if="e.isDir"
                  class="btn btn-ghost btn-sm"
                  @click.stop="enter(e)"
                >
                  {{ t('project.dirEnter') }}
                </button>
              </li>
              <li
                v-if="dir.entries.length === 0"
                class="dir-empty"
              >{{ t('project.dirEmpty') }}</li>
              <li
                v-else-if="filteredEntries.length === 0"
                class="dir-empty"
              >{{ t('project.dirFilterNoMatch') }}</li>
            </ul>

            <div class="new-dir-row">
              <button
                v-if="!newDirMode"
                class="btn btn-ghost btn-sm"
                :disabled="!dir?.writable"
                @click="newDirMode = true"
              >
                <PlusIcon class="w-3.5 h-3.5" />{{ t('project.dirNew') }}
              </button>
              <template v-else>
                <input
                  v-model="newDirName"
                  class="input"
                  :placeholder="t('project.dirNewPlaceholder')"
                  @keyup.enter="createDir"
                >
                <button class="btn btn-primary btn-sm" :disabled="creating || !newDirName.trim()" @click="createDir">
                  {{ creating ? t('common.loading') : t('common.confirm') }}
                </button>
                <button class="btn btn-ghost btn-sm" @click="newDirMode = false">
                  {{ t('common.cancel') }}
                </button>
              </template>
            </div>

            <div class="dir-footer">
              <span class="dir-selection font-mono">{{ selectedPath || '—' }}</span>
              <button
                class="btn btn-primary btn-sm"
                :disabled="!selectedPath || analyzing"
                @click="analyzeAndConfirm"
              >
                {{ analyzing ? t('common.loading') : t('project.dirSelect') }}
              </button>
            </div>
          </template>

          <!-- ── 分析确认视图 ── -->
          <template v-else>
            <div class="analyze-block">
              <div class="analyze-name">{{ analysis.name }}</div>
              <p class="analyze-root font-mono">{{ analysis.root }}</p>
            </div>

            <div class="analyze-grid">
              <div
                class="analyze-item"
                :class="analysis.isGitRoot ? 'analyze-ok' : 'analyze-warn'"
              >
                <div class="analyze-item-title">
                  {{ analysis.isGitRoot ? t('project.analyzeGitRoot') : t('project.analyzeNotGitRoot') }}
                </div>
                <div class="analyze-item-sub">
                  {{ analysis.isGitRoot ? (analysis.gitBranch || '—') : t('project.analyzeGitHint') }}
                </div>
              </div>
              <div
                class="analyze-item"
                :class="analysis.hasCode ? 'analyze-ok' : ''"
              >
                <div class="analyze-item-title">
                  {{ analysis.hasCode ? t('project.analyzeHasCode') : t('project.analyzeEmpty') }}
                </div>
                <div class="analyze-item-sub">
                  {{ t('project.analyzeCodeHint') }}
                </div>
              </div>
            </div>

            <div
              v-if="analysis.duplicate"
              class="analyze-warn-block"
            >
              <ExclamationTriangleIcon class="w-4 h-4 shrink-0" />
              <div>
                <div class="analyze-item-title">{{ t('project.analyzeDuplicate') }}</div>
                <p class="analyze-item-sub font-mono">{{ analysis.duplicate.name }} · {{ analysis.duplicate.rootPath }}</p>
              </div>
            </div>

            <div
              v-if="analysis.signatureProject"
              class="analyze-ok-block"
            >
              <CheckIcon class="w-4 h-4 shrink-0" />
              <div>
                <div class="analyze-item-title">{{ t('project.analyzeSignature') }}</div>
                <p class="analyze-item-sub font-mono">{{ analysis.signatureProject.name }} · {{ analysis.signatureProject.rootPath }}</p>
              </div>
            </div>

            <div class="dir-footer">
              <button class="btn btn-ghost btn-sm" @click="backToBrowse">
                {{ t('guide.back') }}
              </button>
              <div class="flex gap-2">
                <button class="btn btn-ghost btn-sm" @click="emit('close')">
                  {{ t('common.cancel') }}
                </button>
                <button class="btn btn-primary btn-sm" @click="confirmSelect">
                  <CheckIcon class="w-3.5 h-3.5" />
                  {{ t('project.dirConfirm') }}
                </button>
              </div>
            </div>
          </template>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.server-dir-card {
  width: calc(640px * var(--ui-scale, 1));
  max-width: 94vw;
  background: var(--bg-secondary, #1e1e2e);
  border: 1px solid var(--border);
  border-radius: calc(12px * var(--ui-scale, 1));
  display: flex;
  flex-direction: column;
  max-height: 85vh;
}
.dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: calc(16px * var(--ui-scale, 1)) calc(20px * var(--ui-scale, 1)) calc(12px * var(--ui-scale, 1));
}
.dialog-title {
  font-size: calc(14px * var(--ui-scale, 1));
  font-weight: 600;
  color: var(--text-primary);
}
.dialog-close {
  font-size: calc(18px * var(--ui-scale, 1));
  color: var(--text-muted);
  background: none;
  border: none;
  cursor: pointer;
  padding: calc(2px * var(--ui-scale, 1)) calc(6px * var(--ui-scale, 1));
  border-radius: calc(6px * var(--ui-scale, 1));
  line-height: 1;
}
.dialog-close:hover {
  color: var(--text-primary);
  background: color-mix(in srgb, var(--text-primary) 10%, transparent);
}
.server-dir-body {
  padding: calc(16px * var(--ui-scale, 1)) calc(20px * var(--ui-scale, 1)) calc(20px * var(--ui-scale, 1));
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: calc(12px * var(--ui-scale, 1));
}
.import-error {
  font-size: calc(12px * var(--ui-scale, 1));
  color: #ef4444;
  background: color-mix(in srgb, #ef4444 10%, transparent);
  border-radius: calc(8px * var(--ui-scale, 1));
  padding: calc(8px * var(--ui-scale, 1)) calc(10px * var(--ui-scale, 1));
}
.path-bar {
  display: flex;
  align-items: center;
  gap: calc(6px * var(--ui-scale, 1));
}
.path-input {
  flex: 1;
  min-width: 0;
  font-family: var(--font-mono, monospace);
  font-size: calc(12px * var(--ui-scale, 1));
}
.dir-meta {
  display: flex;
  align-items: center;
  gap: calc(10px * var(--ui-scale, 1));
  font-size: calc(11px * var(--ui-scale, 1));
}
.perm-chip, .host-chip {
  border-radius: calc(6px * var(--ui-scale, 1));
  padding: calc(2px * var(--ui-scale, 1)) calc(8px * var(--ui-scale, 1));
  font-size: calc(11px * var(--ui-scale, 1));
}
.perm-ok {
  background: color-mix(in srgb, #22c55e 15%, transparent);
  color: #22c55e;
}
.perm-no {
  background: color-mix(in srgb, #ef4444 15%, transparent);
  color: #ef4444;
}
.host-chip {
  background: color-mix(in srgb, var(--accent) 12%, transparent);
  color: var(--accent);
  font-family: var(--font-mono, monospace);
}
.sel-active {
  color: var(--accent);
}
.dir-loading {
  font-size: calc(12px * var(--ui-scale, 1));
  color: var(--text-muted);
  padding: calc(12px * var(--ui-scale, 1)) 0;
}
.dir-list {
  border: 1px solid var(--border);
  border-radius: calc(10px * var(--ui-scale, 1));
  max-height: 44vh;
  overflow-y: auto;
  list-style: none;
  margin: 0;
  padding: 0;
}
.dir-item {
  display: flex;
  align-items: center;
  gap: calc(8px * var(--ui-scale, 1));
  padding: calc(7px * var(--ui-scale, 1)) calc(12px * var(--ui-scale, 1));
  cursor: pointer;
  font-size: calc(12px * var(--ui-scale, 1));
  border-bottom: 1px solid var(--border);
  color: var(--text-primary);
}
.dir-item:last-child {
  border-bottom: none;
}
.dir-item:hover {
  background: color-mix(in srgb, var(--text-primary) 6%, transparent);
}
.dir-item-sel {
  background: color-mix(in srgb, var(--accent) 12%, transparent);
}
.dir-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: calc(18px * var(--ui-scale, 1));
  flex-shrink: 0;
}
.dir-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dir-ro {
  font-size: calc(10px * var(--ui-scale, 1));
  color: #ef4444;
  flex-shrink: 0;
}
.dir-empty {
  padding: calc(14px * var(--ui-scale, 1));
  font-size: calc(12px * var(--ui-scale, 1));
  color: var(--text-muted);
  text-align: center;
}
.new-dir-row {
  display: flex;
  align-items: center;
  gap: calc(8px * var(--ui-scale, 1));
}
.dir-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: calc(10px * var(--ui-scale, 1));
  margin-top: calc(4px * var(--ui-scale, 1));
}
.dir-selection {
  font-size: calc(11px * var(--ui-scale, 1));
  color: var(--text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.analyze-block {
  border: 1px solid var(--border);
  border-radius: calc(10px * var(--ui-scale, 1));
  padding: calc(10px * var(--ui-scale, 1)) calc(12px * var(--ui-scale, 1));
}
.analyze-name {
  font-size: calc(13px * var(--ui-scale, 1));
  font-weight: 600;
  color: var(--text-primary);
}
.analyze-root {
  font-size: calc(11px * var(--ui-scale, 1));
  color: var(--text-muted);
  margin-top: calc(2px * var(--ui-scale, 1));
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.analyze-grid {
  display: flex;
  flex-direction: column;
  gap: calc(8px * var(--ui-scale, 1));
}
.analyze-item {
  border: 1px solid var(--border);
  border-radius: calc(10px * var(--ui-scale, 1));
  padding: calc(8px * var(--ui-scale, 1)) calc(12px * var(--ui-scale, 1));
}
.analyze-ok {
  border-color: color-mix(in srgb, #22c55e 40%, transparent);
}
.analyze-warn {
  border-color: color-mix(in srgb, #f59e0b 40%, transparent);
}
.analyze-item-title {
  font-size: calc(12px * var(--ui-scale, 1));
  color: var(--text-primary);
}
.analyze-item-sub {
  font-size: calc(10px * var(--ui-scale, 1));
  color: var(--text-muted);
  margin-top: calc(2px * var(--ui-scale, 1));
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.analyze-warn-block, .analyze-ok-block {
  display: flex;
  align-items: flex-start;
  gap: calc(8px * var(--ui-scale, 1));
  border-radius: calc(10px * var(--ui-scale, 1));
  padding: calc(8px * var(--ui-scale, 1)) calc(12px * var(--ui-scale, 1));
  font-size: calc(12px * var(--ui-scale, 1));
}
.analyze-warn-block {
  border: 1px solid color-mix(in srgb, #f59e0b 40%, transparent);
  background: color-mix(in srgb, #f59e0b 8%, transparent);
  color: #f59e0b;
}
.analyze-ok-block {
  border: 1px solid color-mix(in srgb, #22c55e 40%, transparent);
  background: color-mix(in srgb, #22c55e 8%, transparent);
  color: #22c55e;
}
</style>