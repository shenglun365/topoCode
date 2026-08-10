<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { FolderOpenIcon, ArrowDownTrayIcon } from '@heroicons/vue/24/outline'
import { useProjectStore } from '@/stores/project'

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
  const p = await (window as any).api?.dialog?.openDirectory()
  if (p) dirPath.value = p
}

async function pickLocalRepo() {
  const p = await (window as any).api?.dialog?.openDirectory()
  if (p) localRepoPath.value = p
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
  </Teleport>
</template>

<style scoped>
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
.import-source-card {
  width: 520px;
  max-width: 92vw;
  background: var(--bg-secondary, #1e1e2e);
  border: 1px solid var(--border);
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  max-height: 85vh;
}
.import-source-body {
  padding: 16px 20px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.mode-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}
.mode-card {
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 12px 10px;
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
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}
.mode-card-hint {
  display: block;
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 2px;
}
.field { display: flex; flex-direction: column; gap: 6px; }
.field-row { display: flex; align-items: center; gap: 8px; }
.field-row.two-col { display: flex; gap: 10px; }
.grow { flex: 1; }
.field-label { font-size: 12px; color: var(--text-secondary); }
.hint-warn {
  font-size: 11px;
  color: #d97706;
  background: color-mix(in srgb, #d97706 10%, transparent);
  border: 1px solid color-mix(in srgb, #d97706 35%, transparent);
  border-radius: 8px;
  padding: 8px 10px;
  line-height: 1.5;
}
.hint-info {
  font-size: 11px;
  color: var(--text-muted);
  line-height: 1.5;
}
.import-error {
  font-size: 12px;
  color: #ef4444;
  background: color-mix(in srgb, #ef4444 10%, transparent);
  border-radius: 8px;
  padding: 8px 10px;
}
.dialog-footer {
  padding: 12px 20px;
  border-top: 1px solid var(--border);
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
</style>
