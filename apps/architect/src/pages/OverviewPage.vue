<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  ArrowPathIcon, BookOpenIcon, DocumentTextIcon, FolderIcon,
  MagnifyingGlassIcon, PencilSquareIcon, RocketLaunchIcon, ShieldCheckIcon, SparklesIcon,
  CheckCircleIcon, TrashIcon, XMarkIcon,
} from '@heroicons/vue/24/outline'
import { ArrowUpOnSquareIcon, StarIcon } from '@heroicons/vue/24/solid'
import HostDirPickerDialog from '@/components/project/HostDirPickerDialog.vue'
import type { KbConfig, OverviewMission, ProjectInfo } from '@/types'
import { getOverview } from '@/services/overview-service'
import { apiGet } from '@/services/api-client'
import { projectService } from '@/services/project-service'
import { kbService } from '@/services/kb-service'

const { t } = useI18n()

const showSetup = ref(false)
const recent = ref<ProjectInfo[]>([])
const kbConfig = ref<KbConfig | null>(null)
const kbCount = ref(0)
const kbLinked = ref(false)
const missions = ref<OverviewMission[]>([])
const loading = ref(true)

const search = ref('')
const deleting = ref<ProjectInfo | null>(null)
const deleteData = ref(false)
const deletePurged = ref('')
const busyId = ref<string | null>(null)

const testingKb = ref(false)

const pinnedWarning = ref(false)
let pinnedWarningTimer: ReturnType<typeof setTimeout> | null = null

onUnmounted(() => {
  if (pinnedWarningTimer) clearTimeout(pinnedWarningTimer)
})

const filtered = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return recent.value
  return recent.value.filter((p) =>
    (p.name || '').toLowerCase().includes(q) ||
    (p.rootPath || '').toLowerCase().includes(q),
  )
})

onMounted(() => {
  loadOverview()
  loadDocs()
})

async function loadOverview() {
  loading.value = true
  const data = await getOverview()
  if (data) {
    recent.value = data.recent ?? []
    kbConfig.value = data.kbConfig ?? null
    kbCount.value = data.kb?.count ?? 0
    kbLinked.value = !!data.kb?.linked
    missions.value = data.missions ?? []
  }
  loading.value = false
}

function reload() {
  showSetup.value = false
  loadOverview()
}

/** 打开新项目成功 → 刷新主页列表。 */
function onSetupSaved() {
  reload()
}

function workbenchUrl(p: ProjectInfo): string {
  const base = window.location.origin + window.location.pathname
  return `${base}#/workbench?project=${encodeURIComponent(p.id)}`
}

/** 点击近期项目 → 开新浏览器 tab 进入其 workbench。 */
function openProjectAt(p: ProjectInfo) {
  if (!p.id) return
  window.open(workbenchUrl(p), '_blank')
}

async function toggleFavorite(p: ProjectInfo) {
  busyId.value = p.id
  try {
    await projectService.flagProject({ execRoot: p.rootPath, favorite: !p.favorite })
    await loadOverview()
  } finally {
    busyId.value = null
  }
}

async function togglePinned(p: ProjectInfo) {
  if (p.pinned) {
    busyId.value = p.id
    try {
      await projectService.flagProject({ execRoot: p.rootPath, pinned: false })
      await loadOverview()
    } finally {
      busyId.value = null
    }
    return
  }
  // 置顶数量上限 10(与 KB project card 一致)
  const pinnedCount = recent.value.filter((x) => x.pinned).length
  if (pinnedCount >= 10) {
    pinnedWarning.value = true
    if (pinnedWarningTimer) clearTimeout(pinnedWarningTimer)
    pinnedWarningTimer = setTimeout(() => { pinnedWarning.value = false }, 2500)
    return
  }
  busyId.value = p.id
  try {
    await projectService.flagProject({ execRoot: p.rootPath, pinned: true })
    await loadOverview()
  } finally {
    busyId.value = null
  }
}

function askDelete(p: ProjectInfo) {
  deleting.value = p
  deleteData.value = false
}

// ---- 项目改名(仅 architect 本地 arch_projects，不联动 KB) ----
const renamingId = ref('')
const renameDraft = ref('')
const renameInputRef = ref<HTMLInputElement | null>(null)

function startRename(p: ProjectInfo) {
  renamingId.value = p.id
  renameDraft.value = p.name || ''
  void nextTick(() => renameInputRef.value?.focus())
}

function cancelRename() {
  renamingId.value = ''
  renameDraft.value = ''
}

async function saveRename(p: ProjectInfo) {
  if (renamingId.value !== p.id) return   // blur/enter 双触发防抖
  const name = renameDraft.value.trim()
  cancelRename()
  if (!name || name === p.name) return
  busyId.value = p.id
  try {
    await projectService.renameProject({ execRoot: p.rootPath, name })
    await loadOverview()
  } finally {
    busyId.value = null
  }
}

async function confirmDelete() {
  if (!deleting.value) return
  busyId.value = deleting.value.id
  try {
    const res = await projectService.deleteProject({ execRoot: deleting.value.rootPath, deleteData: deleteData.value })
    const groups = Object.keys(res.purged || {}).length
    deletePurged.value = deleteData.value && groups ? t('overview.deletePurged', { n: groups }) : ''
    deleting.value = null
    if (deletePurged.value) setTimeout(() => { deletePurged.value = '' }, 5000)
    await loadOverview()
  } finally {
    busyId.value = null
  }
}

async function testKb() {
  testingKb.value = true
  try {
    const res = await kbService.test()
    kbConfig.value = res
  } finally {
    testingKb.value = false
  }
}

const connDocs: { icon: unknown; title: string; note: string }[] = [
  { icon: BookOpenIcon, title: 'README', note: t('overview.docNoteReadme') },
  { icon: DocumentTextIcon, title: 'Conventions', note: t('overview.docNoteConventions') },
  { icon: DocumentTextIcon, title: 'KB Contract', note: t('overview.docNoteKbContract') },
]
const docList = ref<{ id: string; title: string }[]>([])

async function loadDocs() {
  try {
    docList.value = (await apiGet<{ id: string; title: string }[]>('/docs/list')) ?? []
  } catch {
    docList.value = []
  }
}

function openDoc(id: string) {
  const base = window.location.origin + window.location.pathname
  window.open(`${base}#/docs/${id}`, '_blank')
}
</script>

<template>
  <div class="p-6 max-w-7xl mx-auto space-y-6">
    <div v-if="deletePurged" class="fixed bottom-5 right-5 z-50 rounded-lg border border-ctp-green/40 bg-ctp-surface0 px-4 py-2 text-xs text-ctp-green shadow-lg">
      {{ deletePurged }}
    </div>
    <!-- 组① 顶部启动条：启动命令 + 新建 / 打开 -->
    <section class="panel p-5">
      <div class="flex flex-wrap items-center gap-4">
        <div class="w-11 h-11 rounded-xl bg-ctp-surface0 flex items-center justify-center shrink-0">
          <RocketLaunchIcon class="w-6 h-6 text-ctp-mauve" />
        </div>
        <div class="flex-1 min-w-[240px]">
          <div class="text-sm font-medium text-ctp-text">{{ t('overview.launchTitle') }}</div>
          <p class="text-xs text-ctp-subtext0 mt-0.5">{{ t('overview.launchNote') }}</p>
          <p class="text-xs text-ctp-subtext0 mt-0.5">{{ t('overview.launchScript') }}</p>
        </div>
        <div class="flex items-center gap-2 shrink-0">
          <button class="btn btn-green text-xs" @click="showSetup = true">
            {{ t('overview.newProject') }}
          </button>
        </div>
      </div>
    </section>

    <HostDirPickerDialog v-if="showSetup" @close="showSetup = false" @saved="onSetupSaved" />

    <!-- 左栏：近期项目；右栏：agent设置 + 使用文档 -->
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-4 items-start">
      <!-- ② 近期项目（左栏） -->
      <section class="panel overflow-hidden lg:col-span-2">
        <div class="panel-header">
          <span class="flex items-center gap-2">
            <FolderIcon class="w-4 h-4 text-ctp-blue" />{{ t('overview.recentProjects') }}
          </span>
          <span v-if="recent.length" class="text-[11px] text-ctp-overlay1">{{ recent.length }}</span>
        </div>
        <div class="p-3 border-b border-ctp-surface0">
          <div class="relative">
            <MagnifyingGlassIcon class="w-4 h-4 text-ctp-overlay1 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              v-model="search"
              class="input pl-9 text-xs"
              :placeholder="t('overview.searchProjects')"
            />
          </div>
        </div>
        <div v-if="loading" class="p-4 text-xs text-ctp-subtext0">{{ t('app.loading') }}</div>
        <div v-else-if="!filtered.length" class="p-4 text-xs text-ctp-subtext0">
          {{ search ? t('overview.searchEmpty') : t('overview.recentEmpty') }}
        </div>
        <ul v-else class="p-3 space-y-2 max-h-[420px] overflow-y-auto">
          <li
            v-for="p in filtered"
            :key="p.id"
            class="relative flex items-center gap-2 border rounded-lg px-3 py-2 cursor-pointer transition-colors"
            :class="p.pinned ? 'border-ctp-blue' : 'border-ctp-surface0 hover:border-ctp-surface2'"
            @click="openProjectAt(p)"
          >
            <div class="flex-1 min-w-0 pl-1">
              <div class="flex items-center gap-2 min-w-0">
                <input
                  v-if="renamingId === p.id"
                  ref="renameInputRef"
                  v-model="renameDraft"
                  class="input !py-0.5 !px-2 !text-xs w-52"
                  :placeholder="t('overview.renamePlaceholder')"
                  :title="t('overview.renameHint')"
                  @click.stop
                  @keyup.enter="saveRename(p)"
                  @keyup.esc="cancelRename"
                  @blur="saveRename(p)"
                >
                <span v-else class="text-sm text-ctp-text truncate">{{ p.name }}</span>
                <ArrowUpOnSquareIcon
                  v-if="p.pinned"
                  class="w-3.5 h-3.5 text-ctp-blue shrink-0"
                  :title="t('overview.pinned')"
                />
                <StarIcon
                  v-if="p.favorite"
                  class="w-3.5 h-3.5 text-ctp-yellow shrink-0"
                  :title="t('overview.favorited')"
                />
                <span
                  v-if="p.kbProjectId"
                  class="chip bg-ctp-green/15 text-ctp-green shrink-0"
                >{{ t('overview.kbLinkedShort') }}</span>
              </div>
              <div class="text-[11px] text-ctp-overlay1 font-mono truncate">{{ p.rootPath }}</div>
            </div>
            <div class="flex items-center gap-1 shrink-0" @click.stop>
              <button
                v-if="renamingId !== p.id"
                class="btn btn-ghost !px-1.5 !py-1 text-ctp-overlay1 hover:text-ctp-text"
                :title="t('overview.rename')"
                :disabled="busyId === p.id"
                @click="startRename(p)"
              >
                <PencilSquareIcon class="w-4 h-4" />
              </button>
              <template v-else>
                <button
                  class="btn btn-ghost !px-1.5 !py-1 text-ctp-green"
                  :title="t('common.confirm')"
                  @mousedown.prevent
                  @click="saveRename(p)"
                >
                  <CheckCircleIcon class="w-4 h-4" />
                </button>
                <button
                  class="btn btn-ghost !px-1.5 !py-1 text-ctp-overlay1 hover:text-ctp-red"
                  :title="t('common.cancel')"
                  @mousedown.prevent
                  @click="cancelRename"
                >
                  <XMarkIcon class="w-4 h-4" />
                </button>
              </template>
              <button
                class="btn btn-ghost !px-1.5 !py-1"
                :class="p.pinned ? 'text-ctp-blue' : 'text-ctp-overlay1 hover:text-ctp-blue'"
                :title="p.pinned ? t('overview.unpin') : t('overview.pin')"
                :disabled="busyId === p.id"
                @click="togglePinned(p)"
              >
                <ArrowUpOnSquareIcon class="w-4 h-4" />
              </button>
              <button
                class="btn btn-ghost !px-1.5 !py-1"
                :class="p.favorite ? 'text-ctp-yellow' : 'text-ctp-overlay1 hover:text-ctp-yellow'"
                :title="p.favorite ? t('overview.unfavorite') : t('overview.favorite')"
                :disabled="busyId === p.id"
                @click="toggleFavorite(p)"
              >
                <StarIcon class="w-4 h-4" />
              </button>
              <button
                class="btn btn-ghost !px-1.5 !py-1 text-ctp-overlay1 hover:text-ctp-red"
                :title="t('overview.deleteProject')"
                :disabled="busyId === p.id"
                @click="askDelete(p)"
              >
                <TrashIcon class="w-4 h-4" />
              </button>
            </div>
          </li>
        </ul>

        <!-- 置顶数量上限提示 -->
        <Teleport to="body">
          <div
            v-if="pinnedWarning"
            class="fixed bottom-8 left-1/2 -translate-x-1/2 z-50 px-6 py-2.5 rounded-lg border border-ctp-surface1 bg-ctp-crust text-xs text-ctp-text shadow-2xl"
          >
            {{ t('overview.maxPinnedReached') }}
          </div>
        </Teleport>
      </section>

      <!-- 右栏：agent设置 + 使用文档 -->
      <div class="space-y-4">
        <!-- ③ agent设置 -->
        <section class="panel overflow-hidden">
          <div class="panel-header">
            <span class="flex items-center gap-2">
              <ShieldCheckIcon class="w-4 h-4 text-ctp-mauve" />{{ t('overview.sysSettings') }}
            </span>
          </div>
          <div class="p-4 space-y-4">
            <!-- 知识库 -->
            <div>
              <div class="flex items-center justify-between mb-1.5">
                <div class="text-xs text-ctp-overlay1">{{ t('overview.kb') }}</div>
                <button class="btn btn-ghost !px-2 !py-1 text-xs" :disabled="testingKb" @click="testKb">
                  <ArrowPathIcon :class="['w-3.5 h-3.5', testingKb ? 'animate-spin' : '']" />
                  {{ testingKb ? t('common.loading') : t('overview.kbTest') }}
                </button>
              </div>
              <div class="flex items-center gap-2 border border-ctp-surface0 rounded-md px-3 py-2">
                <span
                  class="w-2 h-2 rounded-full shrink-0"
                  :class="kbConfig?.lastStatus === 'ok' ? 'bg-ctp-green' : kbConfig?.lastStatus === 'fail' ? 'bg-ctp-red' : 'bg-ctp-overlay0'"
                />
                <span class="flex-1 text-sm text-ctp-text">{{ t('overview.kbDesc') }}</span>
                <span class="chip bg-ctp-surface0 text-ctp-subtext1 shrink-0">{{ t('overview.kbProjects', { n: kbCount }) }}</span>
              </div>
              <p
                v-if="kbConfig?.lastStatus === 'fail' && kbConfig?.lastDetail"
                class="text-[10px] text-ctp-red mt-1 truncate"
                :title="kbConfig.lastDetail"
              >{{ kbConfig.lastDetail }}</p>
            </div>
          </div>
        </section>

        <!-- ④ 使用文档(教程区：视觉独立，避免与主体混淆) -->
        <section class="panel p-4 bg-ctp-mantle/40 border-dashed">
          <div class="flex items-center gap-2 mb-3">
            <SparklesIcon class="w-4 h-4 text-ctp-peach" />
            <span class="text-sm font-medium text-ctp-subtext1">{{ t('overview.docs') }}</span>
          </div>
          <div class="space-y-4">
            <div>
              <div class="text-[11px] text-ctp-overlay1 mb-1.5">{{ t('overview.guideTitle') }}</div>
              <ul v-if="missions.length" class="space-y-1.5">
                <li
                  v-for="m in missions"
                  :key="m.id"
                  class="flex items-start gap-2 text-xs text-ctp-subtext1 cursor-pointer group hover:bg-ctp-surface0/50 rounded-md px-1.5 py-1 transition-colors"
                  @click="m.docId && openDoc(m.docId)"
                >
                  <CheckCircleIcon class="w-3.5 h-3.5 mt-0.5 shrink-0 text-ctp-peach" />
                  <div>
                    <span class="text-ctp-text group-hover:text-ctp-blue">{{ m.title }}</span>
                    <span class="text-ctp-overlay1"> — {{ m.desc }}</span>
                  </div>
                </li>
              </ul>
              <p v-else class="text-xs text-ctp-overlay1">{{ t('overview.guideEmpty') }}</p>
            </div>
            <div>
              <div class="text-[11px] text-ctp-overlay1 mb-1.5">{{ t('overview.docTitle') }}</div>
              <ul v-if="docList.length" class="space-y-1.5">
                <li
                  v-for="d in docList"
                  :key="d.id"
                  class="flex items-center gap-2 cursor-pointer group hover:bg-ctp-surface0/50 rounded-md px-1.5 py-1 transition-colors"
                  @click="openDoc(d.id)"
                >
                  <DocumentTextIcon class="w-4 h-4 text-ctp-peach shrink-0" />
                  <span class="text-xs text-ctp-sapphire truncate group-hover:text-ctp-blue">{{ d.title }}</span>
                </li>
              </ul>
              <ul v-else class="space-y-1.5">
                <li
                  v-for="d in connDocs"
                  :key="d.title"
                  class="flex items-center gap-2"
                >
                  <component :is="d.icon" class="w-4 h-4 text-ctp-peach shrink-0" />
                  <span class="text-xs text-ctp-sapphire truncate">{{ d.title }}</span>
                  <span class="text-[11px] text-ctp-overlay1 truncate">{{ d.note }}</span>
                </li>
              </ul>
            </div>
          </div>
        </section>
      </div>
    </div>

    <!-- 删除确认弹窗 -->
    <div
      v-if="deleting"
      class="fixed inset-0 z-50 flex items-center justify-center bg-ctp-base/70 backdrop-blur-sm"
      @click.self="deleting = null"
    >
      <div class="panel w-full max-w-md p-5">
        <div class="flex items-center justify-between mb-1">
          <div class="flex items-center gap-2">
            <TrashIcon class="w-5 h-5 text-ctp-red" />
            <h2 class="text-base font-medium text-ctp-text">{{ t('overview.deleteTitle') }}</h2>
          </div>
          <button class="text-ctp-overlay1 hover:text-ctp-text" @click="deleting = null">
            <XMarkIcon class="w-5 h-5" />
          </button>
        </div>
        <p class="text-xs text-ctp-subtext0 mb-3">{{ t('overview.deleteDesc') }}</p>
        <div class="border border-ctp-surface0 rounded-lg px-3 py-2 mb-3">
          <div class="text-sm text-ctp-text truncate">{{ deleting.name }}</div>
          <div class="text-[11px] text-ctp-overlay1 font-mono truncate">{{ deleting.rootPath }}</div>
        </div>
        <label class="flex items-start gap-2 text-xs text-ctp-subtext1 cursor-pointer mb-4">
          <input v-model="deleteData" type="checkbox" class="accent-ctp-red mt-0.5 shrink-0" />
          <span>
            {{ t('overview.deleteDataLabel') }}
            <span class="text-ctp-overlay1 block">{{ t('overview.deleteDataHint') }}</span>
          </span>
        </label>
        <div class="flex justify-end gap-2">
          <button class="btn btn-ghost text-xs" @click="deleting = null">
            {{ t('common.cancel') }}
          </button>
          <button
            class="btn text-xs"
            :class="deleteData ? 'btn-red' : 'btn-ghost'"
            :disabled="busyId === deleting.id"
            @click="confirmDelete"
          >
            {{ busyId === deleting.id ? t('common.loading') : t('overview.deleteConfirm') }}
          </button>
        </div>
      </div>
    </div>

  </div>
</template>