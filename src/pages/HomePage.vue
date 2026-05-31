<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import {
  RocketLaunchIcon,
  MagnifyingGlassIcon,
  StarIcon,
  Squares2X2Icon,
  PlusIcon,
  XMarkIcon,
} from '@heroicons/vue/24/outline'
import { useProjectStore } from '@/stores/project'
import { useSettingsStore } from '@/stores/settings'
import { useNavigationStore } from '@/stores/navigation'
import ProjectCard from '@/components/project/ProjectCard.vue'
import GroupFilter from '@/components/project/GroupFilter.vue'
import GroupManager from '@/components/project/GroupManager.vue'
import { useComponentId } from '@/composables/useComponentId'
const { showId, componentId } = useComponentId('PG-001')
const { t } = useI18n()
const router = useRouter()
const navigation = useNavigationStore()
const projectStore = useProjectStore()
const settingsStore = useSettingsStore()

// 筛选模式: all | favorites
const filterMode = ref<'all' | 'favorites'>('all')

// 分组筛选
const selectedGroupIds = ref<string[]>([])
const groupFilterRef = ref<InstanceType<typeof GroupFilter> | null>(null)

// 分页
const currentPage = ref(1)
const pageSize = computed(() => settingsStore.projectPageSize)

// 复合搜索
const searchQuery = ref('')

/** 解析复合搜索查询字符串，支持 group:xxx name:xxx language:xxx */
function parseSearchQuery(query: string): { group?: string; name?: string; language?: string; free?: string } {
  const result: { group?: string; name?: string; language?: string; free?: string } = {}
  const tokens = query.trim().split(/\s+/).filter(Boolean)
  const freeTokens: string[] = []

  for (const token of tokens) {
    const colonIdx = token.indexOf(':')
    if (colonIdx > 0) {
      const key = token.slice(0, colonIdx).toLowerCase()
      const value = token.slice(colonIdx + 1).toLowerCase()
      if (key === 'group') result.group = value
      else if (key === 'name') result.name = value
      else if (key === 'language') result.language = value
      else freeTokens.push(token)
    } else {
      freeTokens.push(token.toLowerCase())
    }
  }
  if (freeTokens.length > 0) result.free = freeTokens.join(' ')
  return result
}

// 按筛选模式 + 分组过滤
const scopeFilteredProjects = computed(() => {
  let list = projectStore.projects
  if (filterMode.value === 'favorites') {
    list = list.filter(p => p.favorite)
  }
  // 按分组筛选
  if (selectedGroupIds.value.length > 0) {
    list = list.filter(p => {
      const pGroups = p.groups || []
      return selectedGroupIds.value.some(gid => pGroups.includes(gid))
    })
  }
  return list
})

// 应用搜索过滤
const searchFilteredProjects = computed(() => {
  const parsed = parseSearchQuery(searchQuery.value)
  if (!searchQuery.value.trim()) return scopeFilteredProjects.value

  return scopeFilteredProjects.value.filter(p => {
    // group 过滤
    if (parsed.group && !(p.group || '').toLowerCase().includes(parsed.group)) return false
    // name 过滤
    if (parsed.name && !p.name.toLowerCase().includes(parsed.name)) return false
    // language 过滤
    if (parsed.language && !p.language.toLowerCase().includes(parsed.language)) return false
    // 自由文本过滤（匹配 name/group/language/path）
    if (parsed.free) {
      const searchText = `${p.name} ${p.group || ''} ${p.language} ${p.rootPath || p.path}`.toLowerCase()
      for (const word of parsed.free.split(' ')) {
        if (!searchText.includes(word)) return false
      }
    }
    return true
  })
})

// 分页后的项目列表
const pagedProjects = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return searchFilteredProjects.value.slice(start, start + pageSize.value)
})

// 总页数
const totalPages = computed(() => {
  return Math.ceil(searchFilteredProjects.value.length / pageSize.value)
})

// 当前页项目范围
const pageRange = computed(() => {
  const total = searchFilteredProjects.value.length
  if (total === 0) return { start: 0, end: 0, total: 0 }
  const start = (currentPage.value - 1) * pageSize.value + 1
  const end = Math.min(currentPage.value * pageSize.value, total)
  return { start, end, total }
})

// 切换筛选模式时重置页码
watch(filterMode, () => { currentPage.value = 1 })
watch(searchQuery, () => { currentPage.value = 1 })

function handleSelectProject(id: string) {
  projectStore.selectProject(id)
  router.push('/code')
  navigation.navigateTo('code')
}

async function handleImportProject() {
  if (projectStore.importing) return
  if (window.api && window.api.dialog) {
    const path = await window.api.dialog.openDirectory()
    if (path) {
      await projectStore.importProject(path)
      await projectStore.loadProjects()
    }
  }
}

onMounted(async () => {
  await projectStore.loadProjects()
})
</script>

<template>
  <div class="page-home">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <!-- 分组管理（覆盖整个默认视图） -->
    <div
      v-if="projectStore.activeTab?.kind === 'groupManager'"
      class="group-manager-panel"
    >
      <div class="group-manager-header">
        <h3 style="font-size:14px; font-weight:600; margin:0;">
          {{ t('group.manager') }}
        </h3>
        <button
          class="btn btn-ghost btn-sm"
          @click="projectStore.closeTab(projectStore.activeTabId!)"
        >
          <XMarkIcon class="w-4 h-4" />
          <span>{{ t('common.close') }}</span>
        </button>
      </div>
      <div class="group-manager-body">
        <GroupManager />
      </div>
    </div>

    <!-- 项目列表 -->
    <template v-else>
      <!-- 页面标题 -->
      <div style="margin-bottom:24px;">
        <h1 style="font-size:20px; font-weight:600; margin-bottom:4px;">
          TopoCode
        </h1>
        <p
          class="text-muted"
          style="font-size:12px;"
        >
          {{ t('project.subtitle') }}
        </p>
      </div>

      <!-- 筛选按钮 + 搜索 -->
      <div
        v-if="projectStore.projects.length > 0"
        style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; gap:8px; flex-wrap:wrap;"
      >
        <div style="display:flex; gap:4px; align-items:center;">
          <button
            :class="['btn', 'btn-sm', filterMode === 'all' ? 'btn-primary' : 'btn-ghost']"
            @click="filterMode = 'all'"
          >
            <Squares2X2Icon class="w-3.5 h-3.5" />
            <span>{{ t('project.allProjects') }}</span>
            <span
              class="badge badge-gray"
              style="font-size:9px; margin-left:2px;"
            >{{ projectStore.projects.length }}</span>
          </button>
          <button
            :class="['btn', 'btn-sm', filterMode === 'favorites' ? 'btn-primary' : 'btn-ghost']"
            @click="filterMode = 'favorites'"
          >
            <StarIcon class="w-3.5 h-3.5" />
            <span>{{ t('project.myFavorites') }}</span>
            <span
              class="badge badge-yellow"
              style="font-size:9px; margin-left:2px;"
            >{{ projectStore.projects.filter(p => p.favorite).length }}</span>
          </button>
          <!-- 分组筛选 -->
          <GroupFilter
            ref="groupFilterRef"
            @change="selectedGroupIds = $event"
          />
        </div>
        <div style="display:flex; gap:4px; align-items:center;">
          <!-- 每页数量选择 -->
          <span
            class="text-muted"
            style="font-size:10px; white-space:nowrap;"
          >{{ t('project.pageSize') }}</span>
          <select
            :value="pageSize"
            style="padding:2px 4px; font-size:10px; border:1px solid var(--border); border-radius:3px; background:var(--bg-primary); color:var(--text-primary); outline:none;"
            @change="settingsStore.setProjectPageSize(Number(($event.target as HTMLSelectElement).value))"
          >
            <option value="20">
              20
            </option>
            <option value="50">
              50
            </option>
            <option value="100">
              100
            </option>
          </select>
          <!-- 复合搜索输入框 -->
          <div style="position:relative;">
            <MagnifyingGlassIcon class="w-3.5 h-3.5 absolute left-2 top-1/2 -translate-y-1/2 text-muted" />
            <input
              v-model="searchQuery"
              :placeholder="t('project.searchProjects')"
              style="padding:3px 6px 3px 24px; font-size:10px; border:1px solid var(--border); border-radius:3px; background:var(--bg-primary); color:var(--text-primary); width:160px; outline:none;"
            >
          </div>
        </div>
      </div>

      <!-- 项目卡片网格（始终显示，导入卡片自动排在末尾） -->
      <div style="display:grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap:12px; margin-bottom:12px;">
        <ProjectCard
          v-for="project in pagedProjects"
          :key="project.id"
          :project="project"
          @select="handleSelectProject(project.id)"
        />
        <!-- 无匹配结果 -->
        <div
          v-if="pagedProjects.length === 0 && !searchQuery"
          style="grid-column: 1/-1; text-align:center; padding:24px; color:var(--text-muted); font-size:12px;"
        >
          {{ t('project.noFavorites') }}
        </div>
        <div
          v-else-if="pagedProjects.length === 0 && searchQuery"
          style="grid-column: 1/-1; text-align:center; padding:24px; color:var(--text-muted); font-size:12px;"
        >
          {{ t('project.noMatch') }}
        </div>
        <!-- 导入项目卡片（始终在网格末尾） -->
        <div
          class="import-card card"
          :class="{ 'importing': projectStore.importing }"
          @click="handleImportProject"
        >
          <div
            v-if="!projectStore.importing"
            class="import-card-body"
          >
            <PlusIcon class="w-8 h-8 import-card-icon" />
            <span class="import-card-label">{{ t('project.importProject') }}</span>
            <span class="import-card-hint">{{ t('project.importDirHint') }}</span>
          </div>
          <div
            v-else
            class="import-card-body"
          >
            <div class="import-card-progress">
              <div class="import-card-spinner" />
              <span class="import-card-label">{{ t('project.importing') }}</span>
              <span class="import-card-percent">{{ projectStore.importProgress }}%</span>
              <div
                class="progress-bar"
                style="width:80%; margin-top:8px;"
              >
                <div
                  class="progress-bar-fill bg-accent"
                  :style="{ width: (projectStore.importProgress || 0) + '%' }"
                />
              </div>
              <span
                v-if="projectStore.importStatus === 'scan'"
                class="import-card-hint"
              >{{ t('project.importScanning') }}</span>
              <span
                v-else-if="projectStore.importStatus === 'write'"
                class="import-card-hint"
              >{{ t('project.importWriting') }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 分页控件 -->
      <div
        v-if="totalPages > 1"
        class="pagination-bar"
      >
        <span
          class="text-muted"
          style="font-size:11px;"
        >
          {{ t('project.showing') }} {{ pageRange.start }}-{{ pageRange.end }} / {{ pageRange.total }}
        </span>
        <div class="pagination-buttons">
          <button
            class="btn btn-ghost btn-sm"
            :disabled="currentPage === 1"
            @click="currentPage--"
          >
            {{ t('project.prevPage') }}
          </button>
          <span style="font-size:11px; padding:0 8px;">
            {{ currentPage }} / {{ totalPages }}
          </span>
          <button
            class="btn btn-ghost btn-sm"
            :disabled="currentPage === totalPages"
            @click="currentPage++"
          >
            {{ t('project.nextPage') }}
          </button>
        </div>
      </div>

      <!-- 快速开始（无项目时显示提示） -->
      <div
        v-if="projectStore.projects.length === 0"
        class="quick-start-empty"
      >
        <RocketLaunchIcon class="w-12 h-12 text-accent" />
        <h2 style="font-size:16px; font-weight:600; margin-bottom:8px;">
          {{ t('project.quickStart') }}
        </h2>
        <p
          class="text-muted"
          style="font-size:12px; margin-bottom:16px;"
        >
          {{ t('project.quickStartDesc') }}
        </p>
        <p
          class="text-muted"
          style="font-size:11px;"
        >
          {{ t('project.menuImportHint') }}
        </p>
      </div>
    </template>
  </div>
</template>

<style scoped>
.page-home {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 32px;
  overflow: auto;
}

.group-manager-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.group-manager-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 16px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.group-manager-body {
  flex: 1;
  overflow: hidden;
}

.quick-start-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 40px 20px;
  text-align: center;
}

.pagination-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 0;
  border-top: 1px solid var(--border);
}

.pagination-buttons {
  display: flex;
  align-items: center;
  gap: 4px;
}

.import-card {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 160px;
  border: 2px dashed var(--border);
  border-radius: 8px;
  cursor: pointer;
  transition: border-color 0.2s, background 0.2s;
  user-select: none;
}

.import-card:hover {
  border-color: var(--accent);
  background: color-mix(in srgb, var(--accent) 5%, transparent);
}

.import-card.importing {
  cursor: default;
  border-color: var(--accent);
  background: color-mix(in srgb, var(--accent) 5%, transparent);
}

.import-card-body {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.import-card-body .import-card-hint {
  font-size: 11px;
  color: var(--text-muted);
  opacity: 0.7;
  margin-top: 2px;
}

.import-card-icon {
  color: var(--text-muted);
  transition: color 0.2s;
}

.import-card:hover .import-card-icon {
  color: var(--accent);
}

.import-card-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-muted);
}

.import-card:hover .import-card-label {
  color: var(--accent);
}

.import-card-percent {
  font-size: 16px;
  font-weight: 700;
  color: var(--accent);
}

.import-card-progress {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}

.import-card-hint {
  font-size: 11px;
  color: var(--text-muted);
}

.import-card-spinner {
  width: 24px;
  height: 24px;
  border: 2px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
