<script setup lang="ts">

/** MS6-W4 自 ProjectCard 模板整块迁出(逐行未动)；状态经 WS_KEY 注入。 */

import { BookOpenIcon, FolderIcon } from '@heroicons/vue/24/outline'
import { languageBadge } from '@/utils/languageBadge'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useComponentId } from '@/composables/useComponentId'
import { useCardWs } from '../key'

const { t } = useI18n()
const { showId, componentId } = useComponentId('PR-002')
const props = defineProps<{ project: Record<string, any> }>()
const {
  allGroups,
  changesActiveTab,
  changesDialogVisible,
  changesError,
  changesLoading,
  changesResult,
  collectAllGroupIds,
  confirmDelete,
  confirmEditInfo,
  confirmPathChange,
  deletePct,
  deletePhaseLabel,
  editBranch,
  editHead,
  editLocalRepoPath,
  editNameInput,
  editRemoteUrl,
  flattenGroups,
  handleChangePath,
  handleCheckChanges,
  handleClearCache,
  handleDelete,
  handleDeleteBackup,
  handleOpenGroupManagerFromDialog,
  handleResetProject,
  handleResyncFromDialog,
  hideMenu,
  isDeleting,
  isResourceProject,
  isSample,
  menuPosition,
  menuVisible,
  onClearCacheDone,
  onVersionUpdated,
  pathConfirmMessage,
  pendingNewPath,
  pinnedWarning,
  pinnedWarningTimer,
  selectedGroupIds,
  showClearCacheDialog,
  showDeleteConfirm,
  showEditDialog,
  showMenu,
  showPathConfirm,
  showVersionUpdateDialog,
  startEditInfo,
  startVersionUpdate,
  toggleFavorite,
  toggleGroupSelect,
  togglePinned,
} = useCardWs()
const emit = defineEmits<{
  select: [project: any]
}>()

// 存储空间统计（主库缓存列，由 project.list 一次返回，避免逐项目开库）
const storageTotal = computed(() => {
  const s = props.project.storage
  return s?.total ?? 0
})

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(1024))
  return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`
}

function getStatusBadge(status: string): string {
  const map: Record<string, string> = { synced: 'badge-green', syncing: 'badge-blue', error: 'badge-red' }
  return map[status] || 'badge-gray'
}

function getStatusText(status: string): string {
  const map: Record<string, string> = { synced: '已同步', syncing: '同步中', error: '同步失败' }
  return map[status] || status
}

function formatTime(timeStr: string | null): string {
  if (!timeStr) return '-'
  return new Date(timeStr).toLocaleString()
}
</script>
<template>
  <div
    class="project-card card card-clickable"
    :class="{ 'card-pinned': project.pinned }"
    style="position: relative;"
    @click="emit('select', project)"
    @contextmenu="showMenu"
  >
    <!-- 删除进度覆盖层 -->
    <div
      v-if="isDeleting"
      class="delete-overlay"
      @click.stop
    >
      <div class="delete-overlay-title">{{ t('project.deleting') }}</div>
      <div class="progress-bar delete-overlay-bar">
        <div
          class="progress-bar-fill"
          :style="{ width: deletePct + '%' }"
        />
      </div>
      <div class="delete-overlay-phase">{{ deletePhaseLabel }} · {{ deletePct }}%</div>
    </div>
    <!-- 置顶（左上）/收藏（右上）：小图标，减轻对标题/操作按钮的遮挡 -->
    <ArrowUpOnSquareIcon
      v-if="project.pinned"
      class="card-pin-left w-3 h-3 text-accent"
      :title="t('project.pinnedBadge')"
    />
    <StarIcon
      v-if="project.favorite"
      class="card-fav-right w-3 h-3 text-yellow-400"
      :title="t('project.favorited')"
    />
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <!-- 头部: 名称 + 语言 + 菜单按钮 -->
    <div
      class="flex justify-between items-center"
      style="margin-bottom:calc(8px * var(--ui-scale, 1));"
    >
      <div
        class="flex items-center gap-2"
        style="min-width:0;"
      >
        <component
          :is="isResourceProject ? BookOpenIcon : FolderIcon"
          class="w-4 h-4 shrink-0"
          :class="isResourceProject ? 'text-green-500' : 'text-accent'"
        />
        <span style="font-weight:600; font-size:calc(13px * var(--ui-scale, 1)); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
          {{ project.name }}
        </span>
        <!-- 分组 badge -->
        <span
          v-if="project.group"
          class="badge badge-purple"
          style="font-size:calc(8px * var(--ui-scale, 1));"
        >{{ project.group }}</span>
        <!-- 示例 badge -->
        <span
          v-if="isSample"
          class="badge badge-blue"
          style="font-size:calc(8px * var(--ui-scale, 1));"
        >{{ t('common.new') }}</span>
        <!-- 状态提示 -->
        <ExclamationTriangleIcon
          v-if="project.needsResync"
          class="w-3.5 h-3.5 text-yellow-500"
          :title="t('project.needsResync')"
        />
        <ExclamationTriangleIcon
          v-else-if="project.hasFileChanges"
          class="w-3.5 h-3.5 text-orange-500"
          :title="t('project.hasFileChanges')"
        />
      </div>
      <div class="flex items-center gap-1">
        <span :class="`badge ${languageBadge(project.language) || 'badge-gray'}`">
          {{ project.language }}
        </span>
        <!-- 操作按钮 -->
        <button
          class="btn btn-ghost btn-icon btn-sm card-menu-btn"
          @click.stop="showMenu($event)"
        >
          <EllipsisVerticalIcon class="w-4 h-4" />
        </button>
      </div>
    </div>

    <!-- 路径 -->
    <div
      class="text-muted font-mono"
      style="font-size:calc(11px * var(--ui-scale, 1)); margin-bottom:calc(4px * var(--ui-scale, 1)); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;"
    >
      {{ project.rootPath || project.path }}
    </div>

    <div
      class="flex justify-between"
      style="font-size:calc(11px * var(--ui-scale, 1)); color:var(--text-muted);"
    >
      <span>{{ project.fileCount }} {{ t('file.files') }}</span>
      <span
        v-if="storageTotal > 0"
        :title="t('project.storageSize')"
      >{{ formatBytes(storageTotal) }}</span>
      <span>{{ formatTime(project.lastSync) }}</span>
    </div>

    <!-- 进度条 -->
    <div
      class="progress-bar"
      style="margin-top:calc(8px * var(--ui-scale, 1));"
    >
      <div
        class="progress-bar-fill"
        :style="{ width: project.status === 'synced' ? '100%' : '65%' }"
        :class="{ 'bg-success': project.status === 'synced' }"
      />
    </div>

    <div
      class="flex justify-between items-center"
      style="font-size:calc(10px * var(--ui-scale, 1)); color:var(--text-muted); margin-top:calc(4px * var(--ui-scale, 1));"
    >
      <span>
        {{ project.status === 'synced' ? t('project.analysisComplete') : t('project.analysisInProgress') }}
      </span>
      <span
        v-if="project.hasFileChanges"
        class="badge"
        style="background:#f59e0b;color:#fff;font-size:calc(7px * var(--ui-scale, 1));"
      >{{ t('project.filesChanged') }}</span>
      <span
        :class="`badge ${getStatusBadge(project.status)}`"
        style="font-size:calc(8px * var(--ui-scale, 1));"
      >
        {{ getStatusText(project.status) }}
      </span>
    </div>

    <!-- 右键菜单 -->
    <Teleport to="body">
      <div
        v-if="menuVisible"
        class="context-menu"
        :style="{ left: menuPosition.x + 'px', top: menuPosition.y + 'px' }"
        @click.stop
        @mouseleave="hideMenu"
      >
        <!-- 收藏/置顶 -->
        <div
          class="context-menu-item"
          @click="toggleFavorite"
        >
          <StarIcon :class="['w-4 h-4', project.favorite ? 'text-yellow-400' : '']" />
          <span>{{ project.favorite ? t('project.unfavorite') : t('project.favorite') }}</span>
        </div>
        <div
          class="context-menu-item"
          @click="togglePinned"
        >
          <span class="menu-icon-text">{{ project.pinned ? '✕' : '↑' }}</span>
          <span>{{ project.pinned ? t('project.unpin') : t('project.pin') }}</span>
        </div>
        <div class="context-menu-divider" />
        <!-- 修改信息 -->
        <div
          class="context-menu-item"
          @click="startEditInfo"
        >
          <PencilIcon class="w-4 h-4" />
          <span>{{ t('project.editInfo') }}</span>
        </div>
        <!-- 修改路径 -->
        <div
          v-if="!isResourceProject"
          class="context-menu-item"
          @click="handleChangePath"
        >
          <PencilIcon class="w-4 h-4" />
          <span>{{ t('project.changePath') }}</span>
        </div>
        <!-- 检查变更 -->
        <div
          v-if="!isResourceProject"
          class="context-menu-item"
          @click="handleCheckChanges"
        >
          <MagnifyingGlassIcon class="w-4 h-4" />
          <span>{{ t('project.checkChanges') }}</span>
        </div>
        <!-- KB 基线更新 -->
        <div
          v-if="!isResourceProject"
          class="context-menu-item"
          @click="startVersionUpdate"
        >
          <ArrowPathIcon class="w-4 h-4" />
          <span>{{ t('version.title') }}</span>
        </div>
        <!-- 资源项目操作 -->
        <template v-if="isResourceProject">
          <div class="context-menu-divider" />
          <div
            class="context-menu-item"
            @click="handleResetProject"
          >
            <ArrowPathIcon class="w-4 h-4" />
            <span>{{ t('project.resetProject') }}</span>
          </div>
          <div
            class="context-menu-item"
            @click="handleDeleteBackup"
          >
            <ArchiveBoxXMarkIcon class="w-4 h-4" />
            <span>{{ t('project.deleteBackup') }}</span>
          </div>
          <div class="context-menu-divider" />
        </template>
        <!-- 清除缓存 -->
        <div
          v-if="!isSample && !isResourceProject"
          class="context-menu-item context-menu-item-warning"
          @click="handleClearCache"
        >
          <ArchiveBoxXMarkIcon class="w-4 h-4" />
          <span>{{ t('project.clearCache') }}</span>
        </div>
        <div class="context-menu-divider" />
        <!-- 删除 -->
        <div
          v-if="!isSample"
          class="context-menu-item context-menu-item-danger"
          @click="handleDelete"
        >
          <TrashIcon class="w-4 h-4" />
          <span>{{ t('common.delete') }}</span>
        </div>
      </div>
    </Teleport>

    <!-- 点击卡片其他区域关闭菜单 -->
    <div
      v-if="menuVisible"
      class="context-menu-backdrop"
      @click="hideMenu"
    />

    <!-- 删除确认弹窗 -->
    <ConfirmDialog
      v-model:visible="showDeleteConfirm"
      :title="t('common.delete')"
      :message="t('common.confirmDelete')"
      variant="danger"
      @confirm="confirmDelete"
    />

    <!-- 清除缓存 - 选择数据项弹窗 -->
    <ClearCacheDialog
      v-if="showClearCacheDialog"
      :project-id="project.id"
      @close="onClearCacheDone"
    />

    <!-- 修改信息弹窗 -->
    <ConfirmDialog
      v-model:visible="showEditDialog"
      :title="t('project.editInfo')"
      variant="info"
      @confirm="confirmEditInfo"
    >
      <template #message>
        <div class="edit-info-dialog">
          <div class="edit-info-field">
            <label class="edit-info-label">{{ t('project.projectName') }}</label>
            <input
              v-model="editNameInput"
              class="edit-info-input"
              :placeholder="t('project.projectNamePlaceholder')"
              autofocus
              @keydown.enter="confirmEditInfo"
            >
          </div>

          <!-- 版本基线：远端/本地仓库、分支、head -->
          <div class="edit-info-section">
            <div class="edit-info-field">
              <label class="edit-info-label">{{ t('project.remoteUrl') }}</label>
              <input
                v-model="editRemoteUrl"
                class="edit-info-input"
                :placeholder="t('project.remoteUrlPlaceholder')"
              >
            </div>
            <div class="edit-info-field">
              <label class="edit-info-label">{{ t('project.localRepoPath') }}</label>
              <input
                v-model="editLocalRepoPath"
                class="edit-info-input"
                :placeholder="t('project.localRepoPathPlaceholder')"
              >
            </div>
            <div class="edit-info-row">
              <div class="edit-info-field grow">
                <label class="edit-info-label">{{ t('project.branch') }}</label>
                <input
                  v-model="editBranch"
                  class="edit-info-input"
                  :placeholder="t('project.branchPlaceholder')"
                >
              </div>
              <div class="edit-info-field grow">
                <label class="edit-info-label">{{ t('project.head') }}</label>
                <input
                  v-model="editHead"
                  class="edit-info-input"
                  :placeholder="t('project.headPlaceholder')"
                >
              </div>
            </div>
          </div>

          <div class="edit-info-field">
            <label class="edit-info-label">{{ t('project.editGroups') }}</label>
            <div
              v-if="allGroups.length === 0"
              class="edit-info-no-groups"
            >
              <span class="text-muted">{{ t('project.noGroupsAvailable') }}</span>
              <button
                class="edit-info-set-groups-btn"
                @click="handleOpenGroupManagerFromDialog"
              >
                {{ t('group.setGroups') }}
              </button>
            </div>
            <div
              v-else
              class="edit-info-group-list"
            >
              <label
                v-for="group in flattenGroups(allGroups)"
                :key="group.id"
                class="edit-info-group-item"
              >
                <input
                  type="checkbox"
                  :checked="selectedGroupIds.includes(group.id)"
                  @change="toggleGroupSelect(group.id)"
                >
                <span :style="{ paddingLeft: (group.depth || 0) * 12 + 'px' }">{{ group.name }}</span>
              </label>
            </div>
          </div>
        </div>
      </template>
    </ConfirmDialog>

    <!-- 路径变更确认弹窗 -->
    <ConfirmDialog
      v-model:visible="showPathConfirm"
      :title="t('project.changePath')"
      :message="pathConfirmMessage"
      variant="warning"
      :confirm-label="t('project.confirmUpdate')"
      @confirm="confirmPathChange"
    />

    <!-- KB 基线更新弹窗 -->
    <VersionUpdateDialog
      v-if="showVersionUpdateDialog"
      :project-id="project.id"
      @close="showVersionUpdateDialog = false"
      @updated="onVersionUpdated"
    />
  </div>

  <Teleport to="body">
    <div
      v-if="pinnedWarning"
      class="projectcard-toast"
    >
      {{ t('project.maxPinnedReached') }}
    </div>
  </Teleport>

  <Teleport to="body">
    <div
      v-if="changesDialogVisible"
      class="dialog-overlay"
      @click.self="!changesLoading && (changesDialogVisible = false)"
    >
      <div class="changes-dialog">
        <div class="changes-dialog-header">
          <span class="changes-dialog-title">          {{ t('project.changes.title') }} — {{ project.name || project.rootPath || project.path }}</span>
          <button
            v-if="!changesLoading"
            class="btn-close"
            @click="changesDialogVisible = false"
          >
            <XMarkIcon class="w-4 h-4" />
          </button>
        </div>

        <div
          v-if="changesLoading"
          class="changes-dialog-loading"
        >
          <div class="spinner" />
          <span>{{ t('project.changes.scanning') }}</span>
        </div>

        <div
          v-else-if="changesError"
          class="changes-dialog-body"
        >
          <div class="changes-dialog-error">
            <ExclamationTriangleIcon class="w-5 h-5 text-warning" />
            <span>{{ changesError }}</span>
          </div>
          <div class="changes-dialog-actions">
            <button
              class="btn btn-primary btn-sm"
              @click="changesDialogVisible = false"
            >
              {{ t('common.close') }}
            </button>
          </div>
        </div>

        <div
          v-else-if="changesResult && !changesResult.hasChanges"
          class="changes-dialog-body"
        >
          <div
            v-if="changesResult.note === 'fetch-failed'"
            class="changes-note"
          >{{ t('project.changes.noteFetchFailed') }}</div>
          <div
            v-else-if="changesResult.note === 'mirror-missing'"
            class="changes-note"
          >{{ t('project.changes.noteMirrorMissing') }}</div>
          <div
            v-if="changesResult.sourceHead || changesResult.mirrorHead"
            class="changes-heads font-mono"
          >
            {{ t('project.changes.headsInfo', { source: (changesResult.sourceHead || '—').slice(0, 8), mirror: (changesResult.mirrorHead || '—').slice(0, 8) }) }}
          </div>
          <div class="changes-dialog-ok">
            <CheckIcon class="w-5 h-5 text-success" />
            <span>{{ t('project.noChanges') }}</span>
          </div>
          <div class="changes-dialog-actions">
            <button
              class="btn btn-primary btn-sm"
              @click="changesDialogVisible = false"
            >
              {{ t('common.close') }}
            </button>
          </div>
        </div>

        <div
          v-else-if="changesResult && changesResult.hasChanges"
          class="changes-dialog-body"
        >
          <div
            v-if="changesResult.note === 'diff-failed'"
            class="changes-note"
          >{{ t('project.changes.noteDiffFailed') }}</div>
          <div
            v-if="changesResult.sourceHead || changesResult.mirrorHead"
            class="changes-heads font-mono"
          >
            {{ t('project.changes.headsInfo', { source: (changesResult.sourceHead || '—').slice(0, 8), mirror: (changesResult.mirrorHead || '—').slice(0, 8) }) }}
          </div>
          <div class="changes-tabs">
            <button
              class="changes-tab"
              :class="{ active: changesActiveTab === 'modified' }"
              @click="changesActiveTab = 'modified'"
            >
              {{ t('project.changes.modified', { count: changesResult.modified.length }) }}
            </button>
            <button
              class="changes-tab"
              :class="{ active: changesActiveTab === 'added' }"
              @click="changesActiveTab = 'added'"
            >
              {{ t('project.changes.added', { count: changesResult.added.length }) }}
            </button>
            <button
              class="changes-tab"
              :class="{ active: changesActiveTab === 'deleted' }"
              @click="changesActiveTab = 'deleted'"
            >
              {{ t('project.changes.deleted', { count: changesResult.deleted.length }) }}
            </button>
          </div>
          <div class="changes-file-list">
            <div
              v-for="fp in changesResult[changesActiveTab]"
              :key="fp"
              class="changes-file-row"
            >
              <DocumentPlusIcon
                v-if="changesActiveTab === 'added'"
                class="w-3.5 h-3.5 text-success flex-shrink-0"
              />
              <DocumentMinusIcon
                v-else-if="changesActiveTab === 'deleted'"
                class="w-3.5 h-3.5 text-danger flex-shrink-0"
              />
              <PencilIcon
                v-else
                class="w-3.5 h-3.5 text-warning flex-shrink-0"
              />
              <span class="changes-file-path">{{ fp }}</span>
            </div>
            <div
              v-if="changesResult[changesActiveTab].length === 0"
              class="changes-file-empty"
            >
              {{ t('project.changes.noChanges') }}
            </div>
          </div>
          <div class="changes-dialog-actions">
            <button
              class="btn btn-ghost btn-sm"
              @click="changesDialogVisible = false"
            >
              {{ t('common.close') }}
            </button>
            <button
              class="btn btn-primary btn-sm"
              @click="handleResyncFromDialog"
            >
              {{ t('project.resyncConfirm') }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>
<style scoped>
.project-card {
  padding: calc(14px * var(--ui-scale, 1));
  position: relative;
  min-height: calc(140px * var(--ui-scale, 1));
}

.project-card.card-pinned {
  border: 1px solid var(--accent);
}

.bg-success .progress-bar-fill {
  background: var(--success);
}

.card-menu-btn {
  opacity: 0;
  transition: opacity 0.15s;
}

.project-card:hover .card-menu-btn {
  opacity: 1;
}

.rename-input {
  width: 100%;
  padding: calc(8px * var(--ui-scale, 1)) calc(12px * var(--ui-scale, 1));
  border: 1px solid var(--border);
  border-radius: calc(6px * var(--ui-scale, 1));
  background: var(--bg-primary);
  color: var(--text-primary);
  font-size: calc(13px * var(--ui-scale, 1));
  font-family: inherit;
  outline: none;
  margin-top: calc(8px * var(--ui-scale, 1));
}

.rename-input:focus {
  border-color: var(--accent);
}

.edit-info-dialog {
  width: 100%;
}

.edit-info-section {
  margin-bottom: calc(12px * var(--ui-scale, 1));
  padding: calc(10px * var(--ui-scale, 1)) calc(12px * var(--ui-scale, 1));
  border: 1px dashed var(--border);
  border-radius: calc(8px * var(--ui-scale, 1));
}

.edit-info-row {
  display: flex;
  gap: calc(10px * var(--ui-scale, 1));
}

.edit-info-row .grow {
  flex: 1;
  min-width: 0;
}

.edit-info-field {
  margin-bottom: calc(12px * var(--ui-scale, 1));
}

.edit-info-field:last-child {
  margin-bottom: 0;
}

.edit-info-label {
  display: block;
  font-size: calc(12px * var(--ui-scale, 1));
  font-weight: 500;
  color: var(--text-secondary);
  margin-bottom: calc(6px * var(--ui-scale, 1));
}

.edit-info-input {
  width: 100%;
  padding: calc(8px * var(--ui-scale, 1)) calc(12px * var(--ui-scale, 1));
  border: 1px solid var(--border);
  border-radius: calc(6px * var(--ui-scale, 1));
  background: var(--bg-primary);
  color: var(--text-primary);
  font-size: calc(13px * var(--ui-scale, 1));
  font-family: inherit;
  outline: none;
}

.edit-info-input:focus {
  border-color: var(--accent);
}

.edit-info-no-groups {
  display: flex;
  align-items: center;
  gap: calc(8px * var(--ui-scale, 1));
  padding: calc(8px * var(--ui-scale, 1)) 0;
}

.edit-info-set-groups-btn {
  padding: calc(4px * var(--ui-scale, 1)) calc(10px * var(--ui-scale, 1));
  font-size: calc(11px * var(--ui-scale, 1));
  background: var(--accent);
  color: #fff;
  border: none;
  border-radius: calc(4px * var(--ui-scale, 1));
  cursor: pointer;
  white-space: nowrap;
}

.edit-info-set-groups-btn:hover {
  opacity: 0.9;
}

.edit-info-group-list {
  max-height: calc(160px * var(--ui-scale, 1));
  overflow-y: auto;
  border: 1px solid var(--border);
  border-radius: calc(6px * var(--ui-scale, 1));
  padding: calc(4px * var(--ui-scale, 1));
}

.edit-info-group-item {
  display: flex;
  align-items: center;
  gap: calc(6px * var(--ui-scale, 1));
  padding: calc(4px * var(--ui-scale, 1)) calc(8px * var(--ui-scale, 1));
  font-size: calc(12px * var(--ui-scale, 1));
  color: var(--text-primary);
  cursor: pointer;
  border-radius: calc(4px * var(--ui-scale, 1));
}

.edit-info-group-item:hover {
  background: var(--bg-hover);
}

.edit-info-group-item input[type="checkbox"] {
  accent-color: var(--accent);
}
</style>


