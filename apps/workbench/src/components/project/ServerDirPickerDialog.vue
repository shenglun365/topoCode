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
import { ipc } from '@topo/web-core/services/ipc'

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
  try {
    dir.value = await ipc.dir.list(path)
    const d = dir.value
    if (!d) return
    const cur = d.path
    const selectedInView = selectedPath.value === cur || selectedPath.value.startsWith(`${cur}/`)
    if (!selectedInView) {
      selectedPath.value = cur ?? ''
    }
  } catch (e: any) {
    error.value = e?.message || t('project.dirLoadFailed', '目录加载失败')
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
    error.value = e?.message || t('project.dirCreateFailed', '创建目录失败')
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
    error.value = e?.message || t('project.dirAnalyzeFailed', '目录分析失败')
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
          <span class="dialog-title">{{ t('project.dirPickerTitle', '选择服务器目录') }}</span>
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
                :title="t('project.dirUp', '上级目录')"
                @click="goUp"
              >
                <ArrowUpIcon class="w-4 h-4" />
              </button>
              <button class="btn btn-ghost btn-sm" title="/" @click="goRoot">/</button>
              <button class="btn btn-ghost btn-sm" :title="t('project.dirHome', '用户主目录')" @click="home">~</button>
              <input
                class="input path-input"
                :value="dir?.path ?? ''"
                :placeholder="t('project.dirPathPlaceholder', '输入路径后回车')"
                @keyup.enter="(e: any) => load((e.target as HTMLInputElement).value)"
              >
              <button
                class="btn btn-ghost btn-sm"
                :title="t('project.dirRefresh', '刷新')"
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
                {{ dir.writable ? t('project.dirWritable', '可写') : t('project.dirReadonly', '只读') }}
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
                {{ selectedPath === dir.path ? t('project.dirSelected', '已选择当前目录') : t('project.dirSelectCurrent', '选择当前目录') }}
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
                v-for="e in dir.entries"
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
                >{{ t('project.dirReadonlyShort', '只读') }}</span>
                <button
                  v-if="e.isDir"
                  class="btn btn-ghost btn-sm"
                  @click.stop="enter(e)"
                >
                  {{ t('project.dirEnter', '进入') }}
                </button>
              </li>
              <li
                v-if="dir.entries.length === 0"
                class="dir-empty"
              >{{ t('project.dirEmpty', '目录为空') }}</li>
            </ul>

            <div class="new-dir-row">
              <button
                v-if="!newDirMode"
                class="btn btn-ghost btn-sm"
                :disabled="!dir?.writable"
                @click="newDirMode = true"
              >
                <PlusIcon class="w-3.5 h-3.5" />{{ t('project.dirNew', '新建目录') }}
              </button>
              <template v-else>
                <input
                  v-model="newDirName"
                  class="input"
                  :placeholder="t('project.dirNewPlaceholder', '目录名')"
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
                {{ analyzing ? t('common.loading') : t('project.dirSelect', '确认选择') }}
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
                  {{ analysis.isGitRoot ? t('project.analyzeGitRoot', '是 git 仓库根目录') : t('project.analyzeNotGitRoot', '非 git 仓库根目录') }}
                </div>
                <div class="analyze-item-sub">
                  {{ analysis.isGitRoot ? (analysis.gitBranch || '—') : t('project.analyzeGitHint', 'git-local 模式会克隆到源码缓存') }}
                </div>
              </div>
              <div
                class="analyze-item"
                :class="analysis.hasCode ? 'analyze-ok' : ''"
              >
                <div class="analyze-item-title">
                  {{ analysis.hasCode ? t('project.analyzeHasCode', '目录已包含代码/内容') : t('project.analyzeEmpty', '目录为空') }}
                </div>
                <div class="analyze-item-sub">
                  {{ t('project.analyzeCodeHint', '静态导入建议选择独立静态源码目录') }}
                </div>
              </div>
            </div>

            <div
              v-if="analysis.duplicate"
              class="analyze-warn-block"
            >
              <ExclamationTriangleIcon class="w-4 h-4 shrink-0" />
              <div>
                <div class="analyze-item-title">{{ t('project.analyzeDuplicate', '该目录已存在对应项目') }}</div>
                <p class="analyze-item-sub font-mono">{{ analysis.duplicate.name }} · {{ analysis.duplicate.rootPath }}</p>
              </div>
            </div>

            <div
              v-if="analysis.signatureProject"
              class="analyze-ok-block"
            >
              <CheckIcon class="w-4 h-4 shrink-0" />
              <div>
                <div class="analyze-item-title">{{ t('project.analyzeSignature', '检测到源码目录签名，将重关联到既有项目') }}</div>
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
                  {{ t('project.dirConfirm', '使用该目录') }}
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
  width: 640px;
  max-width: 94vw;
  background: var(--bg-secondary, #1e1e2e);
  border: 1px solid var(--border);
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  max-height: 85vh;
}
.dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px 12px;
}
.dialog-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}
.dialog-close {
  font-size: 18px;
  color: var(--text-muted);
  background: none;
  border: none;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 6px;
  line-height: 1;
}
.dialog-close:hover {
  color: var(--text-primary);
  background: color-mix(in srgb, var(--text-primary) 10%, transparent);
}
.server-dir-body {
  padding: 16px 20px 20px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.import-error {
  font-size: 12px;
  color: #ef4444;
  background: color-mix(in srgb, #ef4444 10%, transparent);
  border-radius: 8px;
  padding: 8px 10px;
}
.path-bar {
  display: flex;
  align-items: center;
  gap: 6px;
}
.path-input {
  flex: 1;
  min-width: 0;
  font-family: var(--font-mono, monospace);
  font-size: 12px;
}
.dir-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 11px;
}
.perm-chip, .host-chip {
  border-radius: 6px;
  padding: 2px 8px;
  font-size: 11px;
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
  font-size: 12px;
  color: var(--text-muted);
  padding: 12px 0;
}
.dir-list {
  border: 1px solid var(--border);
  border-radius: 10px;
  max-height: 44vh;
  overflow-y: auto;
  list-style: none;
  margin: 0;
  padding: 0;
}
.dir-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 12px;
  cursor: pointer;
  font-size: 12px;
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
  width: 18px;
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
  font-size: 10px;
  color: #ef4444;
  flex-shrink: 0;
}
.dir-empty {
  padding: 14px;
  font-size: 12px;
  color: var(--text-muted);
  text-align: center;
}
.new-dir-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.dir-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-top: 4px;
}
.dir-selection {
  font-size: 11px;
  color: var(--text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.analyze-block {
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 10px 12px;
}
.analyze-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}
.analyze-root {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.analyze-grid {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.analyze-item {
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 8px 12px;
}
.analyze-ok {
  border-color: color-mix(in srgb, #22c55e 40%, transparent);
}
.analyze-warn {
  border-color: color-mix(in srgb, #f59e0b 40%, transparent);
}
.analyze-item-title {
  font-size: 12px;
  color: var(--text-primary);
}
.analyze-item-sub {
  font-size: 10px;
  color: var(--text-muted);
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.analyze-warn-block, .analyze-ok-block {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  border-radius: 10px;
  padding: 8px 12px;
  font-size: 12px;
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