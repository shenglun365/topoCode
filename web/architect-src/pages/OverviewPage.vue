<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  ArrowPathIcon, BookOpenIcon, DocumentTextIcon, FolderIcon,
  MagnifyingGlassIcon, RocketLaunchIcon, ShieldCheckIcon, SparklesIcon,
  CheckCircleIcon, PlusIcon, TrashIcon, XMarkIcon,
} from '@heroicons/vue/24/outline'
import { ArrowUpOnSquareIcon, StarIcon } from '@heroicons/vue/24/solid'
import HostDirPickerDialog from '@/components/project/HostDirPickerDialog.vue'
import AgentConfigDialog from '@/components/project/AgentConfigDialog.vue'
import type { AgentConfig, Connectivity, KbConfig, OverviewMission, ProjectInfo } from '@/types'
import { getOverview } from '@/services/overview-service'
import { projectService } from '@/services/project-service'
import { deleteAgentConfig, testAgentConfig } from '@/services/agent-service'
import { kbService } from '@/services/kb-service'

const router = useRouter()
const { t } = useI18n()

const showSetup = ref(false)
const showAgentConfig = ref(false)
const recent = ref<ProjectInfo[]>([])
const adapters = ref<{ id: string; name: string; conn: Connectivity }[]>([])
const agentConfigs = ref<AgentConfig[]>([])
const kbConfig = ref<KbConfig | null>(null)
const kbCount = ref(0)
const kbLinked = ref(false)
const missions = ref<OverviewMission[]>([])
const loading = ref(true)

const search = ref('')
const deleting = ref<ProjectInfo | null>(null)
const deleteData = ref(false)
const busyId = ref<string | null>(null)

const testingCfgId = ref<string | null>(null)
const testingKb = ref(false)
const deletingCfg = ref<AgentConfig | null>(null)

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

onMounted(loadOverview)

async function loadOverview() {
  loading.value = true
  const data = await getOverview()
  if (data) {
    recent.value = data.recent ?? []
    adapters.value = data.adapters ?? []
    agentConfigs.value = data.agentConfigs ?? []
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

async function openProjectAt(p: ProjectInfo) {
  if (!p.rootPath) return
  await router.replace({ path: '/overview', query: { root: p.rootPath } })
  reload()
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

async function confirmDelete() {
  if (!deleting.value) return
  busyId.value = deleting.value.id
  try {
    await projectService.deleteProject({ execRoot: deleting.value.rootPath, deleteData: deleteData.value })
    deleting.value = null
    await loadOverview()
  } finally {
    busyId.value = null
  }
}

async function onAgentConfigSaved() {
  showAgentConfig.value = false
  await loadOverview()
}

async function testAgent(cfg: AgentConfig) {
  testingCfgId.value = cfg.id
  try {
    await testAgentConfig(cfg.id)
    await loadOverview()
  } finally {
    testingCfgId.value = null
  }
}

async function confirmDeleteCfg() {
  if (!deletingCfg.value) return
  try {
    await deleteAgentConfig(deletingCfg.value.id)
    deletingCfg.value = null
    await loadOverview()
  } catch (e) {
    console.error('delete agent config failed', e)
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
  { icon: BookOpenIcon, title: 'README', note: '架构师概览与入口' },
  { icon: DocumentTextIcon, title: 'Conventions', note: '约定与库归属' },
  { icon: DocumentTextIcon, title: 'KB Contract', note: 'KB 接口契约' },
]
</script>

<template>
  <div class="p-6 max-w-7xl mx-auto space-y-6">
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

    <HostDirPickerDialog v-if="showSetup" @close="showSetup = false" />
    <AgentConfigDialog v-if="showAgentConfig" @close="showAgentConfig = false" @saved="onAgentConfigSaved" />

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
            <span
              class="w-8 h-8 rounded-md bg-ctp-surface0 flex items-center justify-center shrink-0"
              :title="p.mode === 'greenfield' ? 'greenfield' : 'existing'"
            >
              <span class="text-xs font-semibold text-ctp-blue">{{ p.mode === 'greenfield' ? 'g' : 'e' }}</span>
            </span>
            <div class="flex-1 min-w-0 pl-1">
              <div class="flex items-center gap-2 min-w-0">
                <span class="text-sm text-ctp-text truncate">{{ p.name }}</span>
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
            <!-- Coding Agent -->
            <div>
              <div class="flex items-center justify-between mb-1.5">
                <div class="text-xs text-ctp-overlay1">{{ t('overview.codingAgent') }}</div>
                <button class="btn btn-ghost !px-2 !py-1 text-xs text-ctp-blue" @click="showAgentConfig = true">
                  <PlusIcon class="w-3.5 h-3.5" />{{ t('agent.newConfig') }}
                </button>
              </div>

              <div v-if="loading" class="text-xs text-ctp-subtext0">{{ t('app.loading') }}</div>

              <!-- 已保存连接配置 -->
              <div v-else-if="agentConfigs.length" class="space-y-1.5">
                <div
                  v-for="c in agentConfigs"
                  :key="c.id"
                  class="flex items-center gap-2 border border-ctp-surface0 rounded-md px-3 py-1.5"
                >
                  <span
                    class="w-2 h-2 rounded-full shrink-0"
                    :class="c.lastStatus === 'ok' ? 'bg-ctp-green' : c.lastStatus === 'fail' ? 'bg-ctp-red' : 'bg-ctp-overlay0'"
                  />
                  <div class="flex-1 min-w-0">
                    <div class="text-sm text-ctp-text truncate">{{ c.name }}</div>
                    <div class="text-[10px] text-ctp-overlay1 font-mono truncate">{{ c.host }}:{{ c.port }}</div>
                  </div>
                  <span class="text-[10px] shrink-0" :class="c.lastStatus === 'ok' ? 'text-ctp-green' : c.lastStatus === 'fail' ? 'text-ctp-red' : 'text-ctp-overlay1'">
                    {{ t(`agent.configStatus.${c.lastStatus || 'unknown'}`) }}
                  </span>
                  <button
                    class="btn btn-ghost !px-1.5 !py-1 text-ctp-overlay1 hover:text-ctp-green shrink-0"
                    :title="t('agent.retest')"
                    :disabled="testingCfgId === c.id"
                    @click="testAgent(c)"
                  >
                    <ArrowPathIcon :class="['w-3.5 h-3.5', testingCfgId === c.id ? 'animate-spin' : '']" />
                  </button>
                  <button
                    class="btn btn-ghost !px-1.5 !py-1 text-ctp-overlay1 hover:text-ctp-red shrink-0"
                    :title="t('agent.delete')"
                    @click="deletingCfg = c"
                  >
                    <TrashIcon class="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>

              <!-- 已检测到但未配置的适配器 -->
              <div v-else class="space-y-1">
                <p class="text-[11px] text-ctp-subtext0">{{ t('agent.noConfigs') }}</p>
                <ul class="flex flex-wrap gap-1.5">
                  <li
                    v-for="a in adapters"
                    :key="a.id"
                    class="chip bg-ctp-surface0 text-ctp-subtext1"
                  >
                    <span class="flex items-center gap-1.5">
                      <span
                        class="w-1.5 h-1.5 rounded-full"
                        :class="a.conn === 'ok' ? 'bg-ctp-green' : 'bg-ctp-overlay0'"
                      />
                      {{ a.name }}
                    </span>
                  </li>
                </ul>
              </div>
            </div>

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
                  class="flex items-start gap-2 text-xs text-ctp-subtext1"
                >
                  <CheckCircleIcon class="w-3.5 h-3.5 mt-0.5 shrink-0 text-ctp-peach" />
                  <div>
                    <span class="text-ctp-text">{{ m.title }}</span>
                    <span class="text-ctp-overlay1"> — {{ m.desc }}</span>
                  </div>
                </li>
              </ul>
              <p v-else class="text-xs text-ctp-overlay1">{{ t('overview.guideEmpty') }}</p>
            </div>
            <div>
              <div class="text-[11px] text-ctp-overlay1 mb-1.5">{{ t('overview.docTitle') }}</div>
              <ul class="space-y-1.5">
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

    <!-- 删除 agent 配置确认弹窗 -->
    <div
      v-if="deletingCfg"
      class="fixed inset-0 z-50 flex items-center justify-center bg-ctp-base/70 backdrop-blur-sm"
      @click.self="deletingCfg = null"
    >
      <div class="panel w-full max-w-md p-5">
        <div class="flex items-center justify-between mb-1">
          <div class="flex items-center gap-2">
            <TrashIcon class="w-5 h-5 text-ctp-red" />
            <h2 class="text-base font-medium text-ctp-text">{{ t('agent.deleteTitle') }}</h2>
          </div>
          <button class="text-ctp-overlay1 hover:text-ctp-text" @click="deletingCfg = null">
            <XMarkIcon class="w-5 h-5" />
          </button>
        </div>
        <p class="text-xs text-ctp-subtext0 mb-3">{{ t('agent.deleteDesc') }}</p>
        <div class="border border-ctp-surface0 rounded-lg px-3 py-2 mb-3">
          <div class="text-sm text-ctp-text truncate">{{ deletingCfg.name }}</div>
          <div class="text-[11px] text-ctp-overlay1 font-mono truncate">{{ deletingCfg.host }}:{{ deletingCfg.port }}</div>
        </div>
        <div class="flex justify-end gap-2">
          <button class="btn btn-ghost text-xs" @click="deletingCfg = null">
            {{ t('common.cancel') }}
          </button>
          <button class="btn btn-red text-xs" @click="confirmDeleteCfg">
            {{ t('common.confirm') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>