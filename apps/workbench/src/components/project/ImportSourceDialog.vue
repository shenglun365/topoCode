<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { FolderOpenIcon, ArrowDownTrayIcon } from '@heroicons/vue/24/outline'
import { useProjectStore } from '@/stores/project'
import ServerDirPickerDialog from './ServerDirPickerDialog.vue'

const { t } = useI18n()
const projectStore = useProjectStore()

const emit = defineEmits<{ close: []; imported: [projectId: string] }>()

type ImportMode = 'static' | 'git-local' | 'git-remote'

const mode = ref<ImportMode>('static')
const dirPath = ref('')
const localRepoPath = ref('')
const repoUrl = ref('')
const branch = ref('')
const head = ref('')
const error = ref('')
const busy = ref(false)

// 服务端目录浏览器（Web 替代 Electron dialog 选目录）
const pickerVisible = ref(false)
const pickerTarget = ref<'dir' | 'localRepo'>('dir')

const MODES: Array<{ value: ImportMode; label: string; hint: string }> = [
  { value: 'static', label: t('project.importModeStatic', '独立源码目录'), hint: t('project.importModeStaticHint', '从本地目录导入') },
  { value: 'git-local', label: t('project.importModeGitLocal', '本地 Git 仓库'), hint: t('project.importModeGitLocalHint', '克隆本地仓库到源码缓存') },
  { value: 'git-remote', label: t('project.importModeGitRemote', '远程 Git 仓库'), hint: t('project.importModeGitRemoteHint', '克隆远程仓库到源码缓存') },
]

const canImport = computed(() => {
  if (busy.value) return false
  if (mode.value === 'static') return !!dirPath.value
  if (mode.value === 'git-local') return !!localRepoPath.value
  return !!repoUrl.value
})

async function pickDirectory() {
  pickerTarget.value = 'dir'
  pickerVisible.value = true
}

async function pickLocalRepo() {
  pickerTarget.value = 'localRepo'
  pickerVisible.value = true
}

function onPickerSaved(path: string) {
  if (pickerTarget.value === 'localRepo') {
    localRepoPath.value = path
  } else {
    dirPath.value = path
  }
}

async function doImport() {
  if (!canImport.value) return
  error.value = ''
  busy.value = true
  try {
    let path = ''
    const opts: any = { mode: mode.value, branch: branch.value, head: head.value }
    if (mode.value === 'static') {
      path = dirPath.value
    } else if (mode.value === 'git-local') {
      path = localRepoPath.value
      opts.local_repo_path = localRepoPath.value
    } else {
      opts.repo_url = repoUrl.value
    }
    const project = await projectStore.importProject(path, opts)
    if (!project) {
      error.value = t('project.importDuplicate', '项目已存在或导入失败')
    } else {
      emit('imported', project.id)
      emit('close')
    }
  } catch (e: any) {
    error.value = e?.message || t('project.importFailed', '导入失败')
  } finally {
    busy.value = false
  }
}

function close() {
  if (busy.value) return
  emit('close')
}
</script>

<template>
  <Teleport to="body">
    <div class="dialog-overlay" @click.self="close">
      <div class="dialog-card import-source-card">
        <div class="dialog-header">
          <span class="dialog-title">{{ t('project.importProject') }}</span>
          <button class="dialog-close" @click="close">&times;</button>
        </div>

        <div class="import-source-body">
          <!-- 模式选择 -->
          <div class="mode-grid">
            <button
              v-for="m in MODES"
              :key="m.value"
              class="mode-card"
              :class="{ active: mode === m.value }"
              @click="mode = m.value"
            >
              <span class="mode-card-label">{{ m.label }}</span>
              <span class="mode-card-hint">{{ m.hint }}</span>
            </button>
          </div>

          <!-- static：独立静态目录提示 -->
          <div
            v-if="mode === 'static'"
            class="field"
          >
            <label class="field-label">{{ t('project.sourceDir', '源码目录') }}</label>
            <div class="field-row">
              <input
                v-model="dirPath"
                class="input"
                :placeholder="t('project.sourceDirPlaceholder', '选择源码目录')"
              >
              <button class="btn btn-ghost btn-sm" @click="pickDirectory">
                <FolderOpenIcon class="w-4 h-4" />{{ t('project.browse', '浏览') }}
              </button>
            </div>
            <div class="hint-warn">
              {{ t('project.staticDirAdvice', '建议使用独立的静态源码目录：不要选择工程目录、不要选择 git 本地仓库目录、不要选择会被频繁改动的目录。') }}
            </div>
          </div>

          <!-- git-local -->
          <div
            v-else-if="mode === 'git-local'"
            class="field"
          >
            <label class="field-label">{{ t('project.localRepo', '本地仓库路径') }}</label>
            <div class="field-row">
              <input
                v-model="localRepoPath"
                class="input"
                :placeholder="t('project.localRepoPlaceholder', '选择本地 git 仓库目录')"
              >
              <button class="btn btn-ghost btn-sm" @click="pickLocalRepo">
                <FolderOpenIcon class="w-4 h-4" />{{ t('project.browse', '浏览') }}
              </button>
            </div>
            <div class="hint-info">
              {{ t('project.gitLocalAdvice', '将从该仓库克隆到源码缓存目录，独立于原仓库。') }}
            </div>
          </div>

          <!-- git-remote -->
          <div
            v-else
            class="field"
          >
            <label class="field-label">{{ t('project.remoteRepo', '远端仓库地址') }}</label>
            <div class="field-row">
              <input
                v-model="repoUrl"
                class="input"
                :placeholder="t('project.remoteRepoPlaceholder', 'https://github.com/user/repo.git 或 git@...')"
              >
              <ArrowDownTrayIcon class="w-4 h-4 text-muted" />
            </div>
          </div>

          <!-- 分支/head（git 模式） -->
          <template v-if="mode !== 'static'">
            <div class="field-row two-col">
              <div class="field grow">
                <label class="field-label">{{ t('project.branch', '分支（可选）') }}</label>
                <input
                  v-model="branch"
                  class="input"
                  :placeholder="t('project.branchPlaceholder', '默认分支')"
                >
              </div>
              <div class="field grow">
                <label class="field-label">{{ t('project.head', '提交版本 head（可选）') }}</label>
                <input
                  v-model="head"
                  class="input"
                  :placeholder="t('project.headPlaceholder', '默认最新')"
                >
              </div>
            </div>
          </template>

          <div
            v-if="error"
            class="import-error"
          >{{ error }}</div>
        </div>

        <div class="dialog-footer">
          <button class="btn btn-ghost btn-sm" @click="close">{{ t('common.cancel') }}</button>
          <button
            class="btn btn-primary btn-sm"
            :disabled="!canImport"
            @click="doImport"
          >
            {{ busy ? t('project.importing') : t('project.importStart', '开始导入') }}
          </button>
        </div>
      </div>
    </div>

    <ServerDirPickerDialog
      v-if="pickerVisible"
      @close="pickerVisible = false"
      @saved="onPickerSaved"
    />
  </Teleport>
</template>

<style scoped>
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
.import-source-card {
  width: calc(520px * var(--ui-scale, 1));
  max-width: 92vw;
  background: var(--bg-secondary, #1e1e2e);
  border: 1px solid var(--border);
  border-radius: calc(12px * var(--ui-scale, 1));
  display: flex;
  flex-direction: column;
  max-height: 85vh;
}
.import-source-body {
  padding: calc(16px * var(--ui-scale, 1)) calc(20px * var(--ui-scale, 1));
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: calc(14px * var(--ui-scale, 1));
}
.mode-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: calc(8px * var(--ui-scale, 1));
}
.mode-card {
  border: 1px solid var(--border);
  border-radius: calc(10px * var(--ui-scale, 1));
  padding: calc(12px * var(--ui-scale, 1)) calc(10px * var(--ui-scale, 1));
  cursor: pointer;
  background: var(--bg-tertiary, transparent);
  text-align: left;
  transition: all 0.15s;
}
.mode-card:hover { border-color: var(--accent); }
.mode-card.active {
  border-color: var(--accent);
  background: color-mix(in srgb, var(--accent) 12%, transparent);
}
.mode-card-label {
  display: block;
  font-size: calc(13px * var(--ui-scale, 1));
  font-weight: 600;
  color: var(--text-primary);
}
.mode-card-hint {
  display: block;
  font-size: calc(11px * var(--ui-scale, 1));
  color: var(--text-muted);
  margin-top: calc(2px * var(--ui-scale, 1));
}
.field { display: flex; flex-direction: column; gap: calc(6px * var(--ui-scale, 1)); }
.field-row { display: flex; align-items: center; gap: calc(8px * var(--ui-scale, 1)); }
.field-row.two-col { display: flex; gap: calc(10px * var(--ui-scale, 1)); }
.grow { flex: 1; }
.field-label { font-size: calc(12px * var(--ui-scale, 1)); color: var(--text-secondary); }
.hint-warn {
  font-size: calc(11px * var(--ui-scale, 1));
  color: #d97706;
  background: color-mix(in srgb, #d97706 10%, transparent);
  border: 1px solid color-mix(in srgb, #d97706 35%, transparent);
  border-radius: calc(8px * var(--ui-scale, 1));
  padding: calc(8px * var(--ui-scale, 1)) calc(10px * var(--ui-scale, 1));
  line-height: 1.5;
}
.hint-info {
  font-size: calc(11px * var(--ui-scale, 1));
  color: var(--text-muted);
  line-height: 1.5;
}
.import-error {
  font-size: calc(12px * var(--ui-scale, 1));
  color: #ef4444;
  background: color-mix(in srgb, #ef4444 10%, transparent);
  border-radius: calc(8px * var(--ui-scale, 1));
  padding: calc(8px * var(--ui-scale, 1)) calc(10px * var(--ui-scale, 1));
}
.dialog-footer {
  padding: calc(12px * var(--ui-scale, 1)) calc(20px * var(--ui-scale, 1));
  border-top: 1px solid var(--border);
  display: flex;
  justify-content: flex-end;
  gap: calc(10px * var(--ui-scale, 1));
}
</style>
