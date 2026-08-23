<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { CheckCircleIcon } from '@heroicons/vue/24/outline'
import { ipc } from '@topo/web-core/services/ipc'
import type { UpdateRequest, VersionPreview } from '@topo/web-core/types/ipc'

const { t } = useI18n()

const props = defineProps<{ projectId: string }>()
const emit = defineEmits<{ close: []; updated: [] }>()

const requests = ref<UpdateRequest[]>([])
const loading = ref(false)
const error = ref('')
const busyId = ref('')

// 确认流程状态
const activeRequest = ref<UpdateRequest | null>(null)
const confirmMethod = ref<'pull' | 'worktree'>('pull')
const preview = ref<(VersionPreview & { projectId?: string; requestId?: string; branch?: string; head?: string }) | null>(null)
const stageSelection = ref<Record<string, boolean>>({})
const executing = ref(false)
const doneMsg = ref('')

const STAGES = [
  { key: 'ast', label: t('version.stageAst', 'AST 解析（必更）') },
  { key: 'graph', label: t('version.stageGraph', '调用/依赖/图节点（必更）') },
  { key: 'presummary', label: t('version.stagePresummary', '文件预摘要（建议）') },
  { key: 'community', label: t('version.stageCommunity', '组件语义/局部重划（可选）') },
  { key: 'llm', label: t('version.stageLlm', 'LLM 深度语义（可选）') },
]

const isMajor = computed(() => preview.value?.changeType === 'major')
async function load() {
  loading.value = true
  error.value = ''
  try {
    requests.value = await ipc.knowledge.pendingUpdates(props.projectId)
  } catch (e: any) {
    error.value = e?.message || t('version.loadFailed', '加载失败')
  } finally {
    loading.value = false
  }
}

function startConfirm(req: UpdateRequest) {
  activeRequest.value = req
  confirmMethod.value = 'pull'
  preview.value = null
  stageSelection.value = {}
  doneMsg.value = ''
}

async function doConfirm() {
  const req = activeRequest.value
  if (!req) return
  busyId.value = 'confirm'
  error.value = ''
  try {
    const p = await ipc.knowledge.updateConfirm(req.id, { method: confirmMethod.value })
    preview.value = p
    // 默认勾选：仅建议且已实现的环节（当前 ast/graph 必更已实现）
    const stages = p.stages || {}
    stageSelection.value = Object.fromEntries(
      Object.entries(stages).map(([k, v]: any) => [k, !!(v.suggested && v.implemented)])
    )
  } catch (e: any) {
    error.value = e?.message || t('version.confirmFailed', '确认失败')
  } finally {
    busyId.value = ''
  }
}

async function execute() {
  if (!preview.value || !activeRequest.value) return
  executing.value = true
  error.value = ''
  try {
    const result = await ipc.version.sync(props.projectId, {
      branch: preview.value.branch,
      head: preview.value.head,
      stages: stageSelection.value,
      requestId: activeRequest.value.id,
    })
    doneMsg.value = result.changed
      ? `${t('version.done', '更新完成')} ${result.version?.id || ''}`
      : t('version.noChange', '未检测到代码变化')
    await load()
    emit('updated')
  } catch (e: any) {
    error.value = e?.message || t('version.executeFailed', '执行失败')
  } finally {
    executing.value = false
  }
}

async function cancel(req: UpdateRequest) {
  try {
    await ipc.knowledge.updateCancel(req.id)
    await load()
  } catch (e: any) {
    error.value = e?.message || ''
  }
}

function close() {
  if (executing.value) return
  emit('close')
}

onMounted(load)

function statusLabel(s: string): string {
  return ({ pending: t('version.statusPending', '待处理'), confirmed: t('version.statusConfirmed', '已确认'), done: t('version.statusDone', '已完成'), cancelled: t('version.statusCancelled', '已取消') } as Record<string, string>)[s] || s
}
</script>

<template>
  <Teleport to="body">
    <div class="dialog-overlay" @click.self="close">
      <div class="dialog-card version-dialog">
        <div class="dialog-header">
          <span class="dialog-title">{{ t('version.title', 'KB 基线更新') }}</span>
          <button class="dialog-close" @click="close">&times;</button>
        </div>

        <div class="version-body">
          <div v-if="error" class="version-error">{{ error }}</div>
          <div v-if="doneMsg" class="version-done">
            <CheckCircleIcon class="w-4 h-4" />{{ doneMsg }}
          </div>

          <!-- 待更新标记列表 -->
          <div v-if="!activeRequest" class="req-list">
            <div v-if="loading" class="version-empty">{{ t('version.loading', '加载中...') }}</div>
            <div v-else-if="requests.length === 0" class="version-empty">
              {{ t('version.noRequests', '暂无待更新标记（architect 发起后在此确认）') }}
            </div>
            <div v-for="req in requests" :key="req.id" class="req-item">
              <div class="req-main">
                <div class="req-line">
                  <span class="req-branch">{{ req.branch || '-' }}</span>
                  <span class="req-head">{{ req.head?.slice(0, 12) || '' }}</span>
                  <span class="req-status" :class="req.status">{{ statusLabel(req.status) }}</span>
                </div>
                <div v-if="req.repoUrl || req.localRepoPath" class="req-repo">
                  {{ req.repoUrl || req.localRepoPath }}
                </div>
              </div>
              <div v-if="req.status === 'pending'" class="req-actions">
                <button class="btn btn-primary btn-sm" @click="startConfirm(req)">
                  {{ t('version.confirm', '确认') }}
                </button>
                <button class="btn btn-ghost btn-sm" @click="cancel(req)">
                  {{ t('common.cancel', '取消') }}
                </button>
              </div>
            </div>
          </div>

          <!-- 确认流程 -->
          <div v-else class="confirm-flow">
            <div v-if="!preview" class="confirm-method">
              <div class="confirm-method-title">{{ t('version.pullMethod', '拉取方式') }}</div>
              <label class="method-option">
                <input v-model="confirmMethod" type="radio" value="pull">
                <span>{{ t('version.methodPull', 'git pull（同分支前进）') }}</span>
              </label>
              <label class="method-option">
                <input v-model="confirmMethod" type="radio" value="worktree">
                <span>{{ t('version.methodWorktree', 'git worktree（切分支/多工作区）') }}</span>
              </label>
              <div class="confirm-actions">
                <button class="btn btn-ghost btn-sm" @click="activeRequest = null">
                  {{ t('common.back', '返回') }}
                </button>
                <button class="btn btn-primary btn-sm" :disabled="busyId === 'confirm'" @click="doConfirm">
                  {{ busyId === 'confirm' ? t('common.loading', '处理中...') : t('version.pullNow', '拉取并预览') }}
                </button>
              </div>
            </div>

            <div v-else class="preview">
              <div class="preview-head">
                <span class="preview-title">{{ t('version.preview', '变更预览') }}</span>
                <span v-if="isMajor" class="badge-major">{{ t('version.major', '分支切换/Major') }}</span>
                <span class="badge-risk" :class="preview.risk">{{ t(`version.risk.${preview.risk || 'low'}`, preview.risk || 'low') }}</span>
              </div>
              <div class="delta-cards">
                <div class="delta-card add">
                  <b>{{ preview.delta?.addedCount ?? 0 }}</b><span>{{ t('version.added', '新增') }}</span>
                </div>
                <div class="delta-card mod">
                  <b>{{ preview.delta?.modifiedCount ?? 0 }}</b><span>{{ t('version.modified', '修改') }}</span>
                </div>
                <div class="delta-card del">
                  <b>{{ preview.delta?.deletedCount ?? 0 }}</b><span>{{ t('version.deleted', '删除') }}</span>
                </div>
              </div>

              <div class="impact-line">
                {{ t('version.impact', '变更影响') }}：AST {{ preview.impact?.ast?.filesToParse ?? 0 }} 文件 · 图节点 {{ preview.impact?.graph?.nodeIdsAffected ?? 0 }} · 受影响社区 {{ preview.impact?.community?.affectedCommunities ?? 0 }}
              </div>

              <div class="stage-list">
                <div class="stage-title">{{ t('version.chooseStages', '选择更新环节') }}</div>
                <label v-for="s in STAGES" :key="s.key" class="stage-option">
                  <input v-model="stageSelection[s.key]" type="checkbox" :disabled="['ast', 'graph'].includes(s.key)">
                  <span>{{ s.label }}</span>
                </label>
                <div class="stage-note">{{ t('version.stageNote', 'AST/图节点为必更；组件环节默认不重划，由你根据变化量决定。') }}</div>
              </div>

              <div class="confirm-actions">
                <button class="btn btn-ghost btn-sm" @click="activeRequest = null">
                  {{ t('common.back', '返回') }}
                </button>
                <button class="btn btn-primary btn-sm" :disabled="executing" @click="execute">
                  {{ executing ? t('common.loading', '执行中...') : t('version.execute', '执行更新') }}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.version-dialog {
  width: calc(560px * var(--ui-scale, 1));
  max-width: 94vw;
  background: var(--bg-secondary, #1e1e2e);
  border: 1px solid var(--border);
  border-radius: calc(12px * var(--ui-scale, 1));
  display: flex;
  flex-direction: column;
  max-height: 86vh;
}
.version-body {
  padding: calc(16px * var(--ui-scale, 1)) calc(20px * var(--ui-scale, 1));
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: calc(12px * var(--ui-scale, 1));
}
.version-error {
  font-size: calc(12px * var(--ui-scale, 1));
  color: #ef4444;
  background: color-mix(in srgb, #ef4444 10%, transparent);
  border-radius: calc(8px * var(--ui-scale, 1));
  padding: calc(8px * var(--ui-scale, 1)) calc(10px * var(--ui-scale, 1));
}
.version-done {
  display: flex;
  align-items: center;
  gap: calc(6px * var(--ui-scale, 1));
  font-size: calc(12px * var(--ui-scale, 1));
  color: #10b981;
  background: color-mix(in srgb, #10b981 10%, transparent);
  border-radius: calc(8px * var(--ui-scale, 1));
  padding: calc(8px * var(--ui-scale, 1)) calc(10px * var(--ui-scale, 1));
}
.version-empty { text-align: center; color: var(--text-muted); font-size: calc(12px * var(--ui-scale, 1)); padding: calc(20px * var(--ui-scale, 1)) 0; }
.req-list { display: flex; flex-direction: column; gap: calc(8px * var(--ui-scale, 1)); }
.req-item {
  border: 1px solid var(--border);
  border-radius: calc(10px * var(--ui-scale, 1));
  padding: calc(10px * var(--ui-scale, 1)) calc(12px * var(--ui-scale, 1));
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: calc(10px * var(--ui-scale, 1));
}
.req-line { display: flex; align-items: center; gap: calc(8px * var(--ui-scale, 1)); font-size: calc(12px * var(--ui-scale, 1)); }
.req-branch { font-weight: 600; color: var(--text-primary); }
.req-head { font-family: var(--font-mono); color: var(--text-muted); }
.req-status { font-size: calc(11px * var(--ui-scale, 1)); padding: 1px calc(6px * var(--ui-scale, 1)); border-radius: calc(4px * var(--ui-scale, 1)); }
.req-status.pending { background: #d97706; color: #fff; }
.req-status.confirmed { background: #2563eb; color: #fff; }
.req-status.done { background: #10b981; color: #fff; }
.req-status.cancelled { background: var(--border); color: var(--text-muted); }
.req-repo { font-size: calc(11px * var(--ui-scale, 1)); color: var(--text-muted); margin-top: calc(2px * var(--ui-scale, 1)); }
.req-actions { display: flex; gap: calc(6px * var(--ui-scale, 1)); flex-shrink: 0; }
.confirm-method, .preview { display: flex; flex-direction: column; gap: calc(12px * var(--ui-scale, 1)); }
.confirm-method-title, .stage-title, .preview-title { font-size: calc(13px * var(--ui-scale, 1)); font-weight: 600; color: var(--text-primary); }
.method-option, .stage-option { display: flex; align-items: center; gap: calc(8px * var(--ui-scale, 1)); font-size: calc(13px * var(--ui-scale, 1)); color: var(--text-secondary); }
.confirm-actions { display: flex; justify-content: flex-end; gap: calc(8px * var(--ui-scale, 1)); }
.preview-head { display: flex; align-items: center; gap: calc(8px * var(--ui-scale, 1)); }
.badge-major { font-size: calc(11px * var(--ui-scale, 1)); background: #d97706; color: #fff; padding: 1px calc(6px * var(--ui-scale, 1)); border-radius: calc(4px * var(--ui-scale, 1)); }
.badge-risk { font-size: calc(11px * var(--ui-scale, 1)); padding: 1px calc(6px * var(--ui-scale, 1)); border-radius: calc(4px * var(--ui-scale, 1)); }
.badge-risk.high { background: #ef4444; color: #fff; }
.badge-risk.medium { background: #d97706; color: #fff; }
.badge-risk.low { background: #10b981; color: #fff; }
.delta-cards { display: grid; grid-template-columns: repeat(3, 1fr); gap: calc(8px * var(--ui-scale, 1)); }
.delta-card {
  border: 1px solid var(--border);
  border-radius: calc(8px * var(--ui-scale, 1));
  padding: calc(8px * var(--ui-scale, 1));
  display: flex;
  flex-direction: column;
  align-items: center;
}
.delta-card b { font-size: calc(18px * var(--ui-scale, 1)); }
.delta-card span { font-size: calc(11px * var(--ui-scale, 1)); color: var(--text-muted); }
.delta-card.add b { color: #10b981; }
.delta-card.mod b { color: #d97706; }
.delta-card.del b { color: #ef4444; }
.impact-line { font-size: calc(12px * var(--ui-scale, 1)); color: var(--text-secondary); }
.stage-list { display: flex; flex-direction: column; gap: calc(6px * var(--ui-scale, 1)); border-top: 1px solid var(--border); padding-top: calc(10px * var(--ui-scale, 1)); }
.stage-note { font-size: calc(11px * var(--ui-scale, 1)); color: var(--text-muted); }
</style>
