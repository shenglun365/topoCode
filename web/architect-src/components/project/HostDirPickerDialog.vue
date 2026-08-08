<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  ArrowPathIcon, ArrowUpIcon, CheckIcon, CheckCircleIcon, DocumentIcon,
  DocumentTextIcon,
  ExclamationTriangleIcon, FolderIcon, PlusIcon, XMarkIcon,
} from '@heroicons/vue/24/outline'
import type { DirAnalysis, DirList, ProjectInfo } from '@/types'
import { dirService } from '@/services/dir-service'
import { useArchProjectStore } from '@/stores/project-store'

const emit = defineEmits<{ close: []; saved: [project: ProjectInfo] }>()

const { t } = useI18n()
const project = useArchProjectStore()

const view = ref<'browse' | 'confirm'>('browse')
const dir = ref<DirList | null>(null)
const loading = ref(false)
const error = ref('')

/** 当前选中的项目目录(三种方式：进入子目录后当前目录 / 点选子目录 / 默认当前目录)。 */
const selectedPath = ref<string>('')

const newDirMode = ref(false)
const newDirName = ref('')
const creating = ref(false)

const analyzing = ref(false)
const analysis = ref<DirAnalysis | null>(null)
const kbChoice = ref<string>('')
const busy = ref(false)

const hostLabel = computed(() => {
  const h = dir.value?.host
  if (!h) return ''
  return h.ip ? `${h.name} (${h.ip})` : h.name
})

function fullPath(name: string): string {
  return `${dir.value?.path ?? ''}/${name}`
}

async function load(path?: string) {
  loading.value = true
  error.value = ''
  try {
    dir.value = await dirService.list(path)
    const cur = dir.value.path
    const selectedInView = selectedPath.value === cur || selectedPath.value.startsWith(`${cur}/`)
    if (!selectedInView) {
      // 进入新目录/离开视图后，默认选中当前目录作为项目目录
      selectedPath.value = cur ?? ''
    }
  } catch (e) {
    error.value = e instanceof Error && e.message ? e.message : t('overview.openDir.loadFailed')
  } finally {
    loading.value = false
  }
}

function enter(entry: { name: string; isDir: boolean }) {
  if (!entry.isDir || !dir.value) return
  load(fullPath(entry.name))
}

/** 点选当前目录下的子目录作为项目目录(不必进入)。 */
function selectEntry(entry: { name: string; isDir: boolean }) {
  if (!entry.isDir || !dir.value) return
  selectedPath.value = fullPath(entry.name)
}

/** 选中当前目录本身作为项目目录。 */
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
    await dirService.createDir(parent, name)
    newDirName.value = ''
    newDirMode.value = false
    await load(parent)
  } catch (e) {
    error.value = e instanceof Error && e.message ? e.message : t('overview.openDir.createFailed')
  } finally {
    creating.value = false
  }
}

async function selectCurrent() {
  const root = selectedPath.value
  if (!root) return
  analyzing.value = true
  error.value = ''
  try {
    analysis.value = await dirService.analyze(root)
    kbChoice.value = ''
    view.value = 'confirm'
  } catch (e) {
    error.value = e instanceof Error && e.message ? e.message : t('overview.openDir.analyzeFailed')
  } finally {
    analyzing.value = false
  }
}

function backToBrowse() {
  view.value = 'browse'
  analysis.value = null
}

async function confirmOpen() {
  if (!analysis.value) return
  busy.value = true
  error.value = ''
  try {
    const root = analysis.value.root
    const p = kbChoice.value
      ? await project.bindKbProject(kbChoice.value, root)
      : await project.bindWorkingDir(root)
    emit('saved', p)
    emit('close')
    // 跳转到当前项目工作台(新标签)。用 architect 项目 id 而非目录路径作 URL 参数。
    const base = window.location.origin + window.location.pathname
    window.open(`${base}#/workbench?project=${encodeURIComponent(p?.id ?? '')}`, '_blank')
  } catch (e) {
    error.value = e instanceof Error && e.message ? e.message : t('overview.openDir.bindFailed')
  } finally {
    busy.value = false
  }
}

onMounted(() => load())
</script>

<template>
  <div
    class="fixed inset-0 z-50 flex items-center justify-center bg-ctp-base/70 backdrop-blur-sm"
    @click.self="emit('close')"
  >
    <div class="panel w-full max-w-2xl p-5 flex flex-col max-h-[85vh]">
      <div class="flex items-center justify-between mb-1">
        <div class="flex items-center gap-2">
          <FolderIcon class="w-5 h-5 text-ctp-blue" />
          <h2 class="text-base font-medium text-ctp-text">
            {{ view === 'confirm' ? t('overview.openDir.confirmTitle') : t('overview.openDir.title') }}
          </h2>
          <span
            v-if="hostLabel"
            class="chip bg-ctp-surface0 text-ctp-sapphire font-mono"
            :title="t('overview.openDir.hostHint')"
          >
            {{ hostLabel }}
          </span>
        </div>
        <button class="text-ctp-overlay1 hover:text-ctp-text" @click="emit('close')">
          <XMarkIcon class="w-5 h-5" />
        </button>
      </div>
      <p class="text-xs text-ctp-subtext0 mb-3">
        {{ view === 'confirm' ? t('overview.openDir.confirmDesc') : t('overview.openDir.desc') }}
      </p>

      <div
        v-if="error"
        class="flex items-center gap-2 text-xs text-ctp-red border border-ctp-red/30 bg-ctp-red/5 rounded-md px-3 py-2 mb-3"
      >
        <ExclamationTriangleIcon class="w-3.5 h-3.5 shrink-0" />
        <span class="flex-1">{{ error }}</span>
      </div>

      <!-- ── 浏览视图 ─────────────────────────────── -->
      <template v-if="view === 'browse'">
        <!-- 路径栏 -->
        <div class="flex items-center gap-2 mb-3">
          <button
            class="btn btn-ghost !px-2 text-xs"
            title="上级目录"
            :disabled="!dir?.parent"
            @click="goUp"
          >
            <ArrowUpIcon class="w-4 h-4" />
          </button>
          <button class="btn btn-ghost !px-2 text-xs" title="根目录" @click="goRoot">/</button>
          <button class="btn btn-ghost !px-2 text-xs" title="用户主目录" @click="home">~</button>
          <div class="flex-1 min-w-0">
            <input
              class="input font-mono text-xs !py-1.5"
              :value="dir?.path ?? ''"
              :placeholder="t('overview.openDir.pathPlaceholder')"
              @keyup.enter="(e: KeyboardEvent) => load((e.target as HTMLInputElement).value)"
            />
          </div>
          <button class="btn btn-ghost !px-2 text-xs" title="刷新" @click="load(dir?.path)">
            <ArrowPathIcon class="w-4 h-4" />
          </button>
        </div>

        <!-- 权限提示 -->
        <div
          v-if="dir"
          class="flex items-center gap-3 text-[11px] mb-2"
        >
          <span
            class="chip"
            :class="dir.writable ? 'bg-ctp-green/15 text-ctp-green' : 'bg-ctp-red/15 text-ctp-red'"
          >
            {{ dir.writable ? t('overview.openDir.writable') : t('overview.openDir.readonly') }}
          </span>
          <button
            class="btn btn-ghost !px-2 !py-0.5 text-[11px]"
            :class="selectedPath === dir.path ? 'text-ctp-blue' : ''"
            @click="selectHere"
          >
            <CheckIcon class="w-3 h-3" />
            {{ selectedPath === dir.path ? t('overview.openDir.selectedCurrent') : t('overview.openDir.selectCurrent') }}
          </button>
          <span class="text-ctp-overlay1 font-mono truncate">{{ dir.path }}</span>
        </div>

        <!-- 目录列表 -->
        <div v-if="loading" class="text-xs text-ctp-subtext0 py-4">{{ t('app.loading') }}</div>
        <ul
          v-else-if="dir"
          class="border border-ctp-surface0 rounded-lg divide-y divide-ctp-surface0 max-h-72 overflow-y-auto"
        >
          <li
            v-for="e in dir.entries"
            :key="e.name"
            class="flex items-center gap-2 px-3 py-1.5 cursor-pointer transition-colors"
            :class="selectedPath === fullPath(e.name) ? 'bg-ctp-blue/10' : 'hover:bg-ctp-surface0/60'"
            @click="selectEntry(e)"
          >
            <span class="w-4 flex justify-center shrink-0">
              <span
                v-if="e.isDir"
                class="w-3.5 h-3.5 rounded-full border flex items-center justify-center shrink-0"
                :class="selectedPath === fullPath(e.name) ? 'border-ctp-blue bg-ctp-blue' : 'border-ctp-overlay1'"
              >
                <CheckIcon v-if="selectedPath === fullPath(e.name)" class="w-2.5 h-2.5 text-ctp-base" />
              </span>
              <span v-else class="w-3.5 h-3.5" />
            </span>
            <span class="w-8 flex justify-center shrink-0">
              <FolderIcon v-if="e.isDir" class="w-4 h-4 text-ctp-blue" />
              <DocumentIcon v-else class="w-4 h-4 text-ctp-overlay1" />
            </span>
            <span class="flex-1 min-w-0 text-xs text-ctp-text truncate">{{ e.name }}</span>
            <span
              v-if="e.isDir"
              class="text-[10px] shrink-0"
              :class="e.writable === false ? 'text-ctp-red' : 'text-ctp-overlay1'"
            >
              {{ e.writable === false ? t('overview.openDir.readonlyShort') : '' }}
            </span>
            <button
              v-if="e.isDir"
              class="btn btn-ghost !px-2 text-xs shrink-0"
              @click.stop="enter(e)"
            >
              {{ t('overview.openDir.enter') }}
            </button>
          </li>
          <li v-if="dir.entries.length === 0" class="px-3 py-4 text-xs text-ctp-overlay1">
            {{ t('overview.openDir.dirEmpty') }}
          </li>
        </ul>

        <!-- 新建目录 -->
        <div class="flex items-center gap-2 mt-3">
          <button
            v-if="!newDirMode"
            class="btn btn-ghost text-xs"
            :disabled="!dir?.writable"
            @click="newDirMode = true"
          >
            <PlusIcon class="w-3.5 h-3.5" />{{ t('overview.openDir.newDir') }}
          </button>
          <template v-else>
            <input
              v-model="newDirName"
              class="input text-xs !py-1.5"
              :placeholder="t('overview.openDir.newDirPlaceholder')"
              @keyup.enter="createDir"
            />
            <button class="btn btn-blue text-xs" :disabled="creating || !newDirName.trim()" @click="createDir">
              {{ creating ? t('common.loading') : t('common.confirm') }}
            </button>
            <button class="btn btn-ghost text-xs" @click="newDirMode = false">
              {{ t('common.cancel') }}
            </button>
          </template>
        </div>

        <div class="flex items-center justify-between mt-4 gap-2">
          <div class="flex items-center gap-2 min-w-0">
            <CheckIcon class="w-3.5 h-3.5 text-ctp-blue shrink-0" />
            <span class="text-[11px] text-ctp-overlay1 font-mono truncate">
              {{ selectedPath || t('overview.openDir.noSelection') }}
            </span>
          </div>
          <button class="btn btn-blue text-xs shrink-0" :disabled="!selectedPath || analyzing" @click="selectCurrent">
            {{ analyzing ? t('common.loading') : t('overview.openDir.select') }}
          </button>
        </div>
      </template>

      <!-- ── 确认视图：自动识别结果 ─────────────────── -->
      <template v-else-if="analysis">
        <div class="space-y-3 overflow-y-auto">
          <!-- 目录基本信息 -->
          <div class="border border-ctp-surface0 rounded-lg px-3 py-2.5">
            <div class="flex items-center gap-2 flex-wrap">
              <span class="text-sm font-medium text-ctp-text truncate">{{ analysis.name }}</span>
              <span
                v-if="hostLabel"
                class="chip bg-ctp-surface0 text-ctp-sapphire font-mono"
              >{{ hostLabel }}</span>
              <span
                class="chip"
                :class="analysis.writable ? 'bg-ctp-green/15 text-ctp-green' : 'bg-ctp-red/15 text-ctp-red'"
              >
                {{ analysis.writable ? t('overview.openDir.writable') : t('overview.openDir.readonly') }}
              </span>
            </div>
            <p class="text-[11px] text-ctp-overlay1 font-mono mt-1 truncate">{{ analysis.root }}</p>
          </div>

          <!-- 自动识别项: GIT 状态识别 / 目录内容识别 -->
          <div class="space-y-2">
            <div>
              <div class="text-[11px] text-ctp-overlay1 mb-1">{{ t('overview.openDir.gitStatusTitle') }}</div>
              <div
                class="flex items-center gap-2 border rounded-lg px-3 py-2"
                :class="analysis.isGitRoot ? 'border-ctp-green/40' : 'border-ctp-peach/40'"
              >
                <CheckCircleIcon v-if="analysis.isGitRoot" class="w-4 h-4 text-ctp-green shrink-0" />
                <ExclamationTriangleIcon v-else class="w-4 h-4 text-ctp-peach shrink-0" />
                <div class="min-w-0">
                  <div class="text-xs text-ctp-text">{{ analysis.isGitRoot ? t('overview.openDir.isGitRoot') : t('overview.openDir.notGitRoot') }}</div>
                  <div class="text-[10px] text-ctp-overlay1 truncate">
                    {{ analysis.isGitRoot ? analysis.gitBranch || '—' : t('overview.openDir.notGitRootHint') }}
                  </div>
                </div>
              </div>
            </div>

            <div>
              <div class="text-[11px] text-ctp-overlay1 mb-1">{{ t('overview.openDir.contentStatusTitle') }}</div>
              <div
                class="flex items-center gap-2 border rounded-lg px-3 py-2"
                :class="analysis.hasCode ? 'border-ctp-green/40' : 'border-ctp-surface0'"
              >
                <CheckCircleIcon v-if="analysis.hasCode" class="w-4 h-4 text-ctp-green shrink-0" />
                <DocumentTextIcon v-else class="w-4 h-4 text-ctp-overlay1 shrink-0" />
                <div class="min-w-0">
                  <div class="text-xs text-ctp-text">{{ analysis.hasCode ? t('overview.openDir.hasCode') : t('overview.openDir.noCode') }}</div>
                  <div class="text-[10px] text-ctp-overlay1 truncate">
                    {{ t('overview.openDir.contentHint') }}
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- 重复打开已建立项目警告 -->
          <div
            v-if="analysis.duplicate"
            class="flex items-start gap-2 border border-ctp-peach/40 bg-ctp-peach/5 rounded-lg px-3 py-2"
          >
            <ExclamationTriangleIcon class="w-4 h-4 text-ctp-peach shrink-0 mt-0.5" />
            <div class="min-w-0 flex-1">
              <div class="text-xs text-ctp-text">{{ t('overview.openDir.duplicateProject') }}</div>
              <p class="text-[10px] text-ctp-overlay1 mt-0.5 font-mono truncate">
                {{ analysis.duplicate.name }} · {{ analysis.duplicate.rootPath }}
              </p>
            </div>
          </div>

          <!-- 可关联 KB 候选 -->
          <div v-if="analysis.kbCandidates.length" class="border border-ctp-surface0 rounded-lg p-3">
            <div class="text-xs text-ctp-overlay1 mb-2">{{ t('overview.openDir.kbCandidates') }}</div>
            <div class="space-y-1.5">
              <label
                v-for="kb in analysis.kbCandidates"
                :key="kb.id"
                class="flex items-center gap-2 px-2 py-1.5 rounded-md cursor-pointer border border-transparent hover:border-ctp-surface2 transition-colors"
                :class="kbChoice === kb.id ? 'border-ctp-blue bg-ctp-blue/5' : ''"
              >
                <input v-model="kbChoice" type="radio" :value="kb.id" class="accent-ctp-blue shrink-0" />
                <span class="flex-1 min-w-0">
                  <span class="block text-xs text-ctp-text truncate">{{ kb.name }}</span>
                  <span class="block text-[10px] text-ctp-overlay1 truncate">{{ kb.rootPath }}</span>
                </span>
              </label>
            </div>
          </div>
          <p v-else class="text-xs text-ctp-overlay1">
            {{ t('overview.openDir.kbNone') }}
          </p>
        </div>

        <div class="flex items-center justify-between mt-4">
          <button class="btn btn-ghost text-xs" :disabled="busy" @click="backToBrowse">
            {{ t('guide.back') }}
          </button>
          <div class="flex items-center gap-2">
            <button class="btn btn-ghost text-xs" @click="emit('close')">
              {{ t('common.cancel') }}
            </button>
            <button class="btn btn-green text-xs" :disabled="busy" @click="confirmOpen">
              <CheckIcon class="w-3.5 h-3.5" />
              {{ busy ? t('common.loading') : t('overview.openDir.confirmOpen') }}
            </button>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>
