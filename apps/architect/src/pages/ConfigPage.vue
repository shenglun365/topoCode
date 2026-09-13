<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { CpuChipIcon, Cog6ToothIcon, ArrowDownTrayIcon, PlusIcon, TrashIcon, AdjustmentsHorizontalIcon, PencilSquareIcon } from '@heroicons/vue/24/outline'
import PageHeader from '@/components/PageHeader.vue'
import { useArchSpecStore } from '@/stores/spec-store'
import { useArchProjectStore } from '@/stores/project-store'
import { apiGet, apiPost, apiPut, apiDelete } from '@/services/api-client'
import { backendUp } from '@/services/backend'
import { semanticAssetService, type CodegraphStatus } from '@/services/semantic-asset-service'
import AgentExecutorsCard from '@/components/config/AgentExecutorsCard.vue'
import type { ArchLlmModel, ArchLlmModelsResult, ArchLlmImportResult } from '@/types'

const { t, te } = useI18n()

// ── 设置页子 tab ──
const TABS = [
  { key: 'instance', label: 'config.tabs.instance' },
  { key: 'executors', label: 'config.tabs.executors' },
  { key: 'roleModels', label: 'config.tabs.roleModels' },
  { key: 'other', label: 'config.tabs.other' },
] as const
const activeTab = ref<string>('instance')
const spec = useArchSpecStore()

const project = useArchProjectStore()
spec.load()


// ── 分析任务模型映射（原 M1 角色模型映射；per-call 生效，不写全局 llm 配置） ──
interface AgentRole { name: string; label: string; modelId: string; note?: string }
const roles = ref<AgentRole[]>([])
const rolesSaving = ref(false)
const rolesSavedAt = ref(0)

async function loadRoles() {
  try {
    const r = await apiGet<{ roles: AgentRole[] }>('/agent/roles')
    roles.value = r.roles ?? []
  } catch {
    roles.value = []
  }
}

// 角色文案走 i18n(按 name), 后端兜底
const roleLabel = (r: AgentRole) =>
  te(`config.roles.items.${r.name}.label`) ? t(`config.roles.items.${r.name}.label`) : r.label
const roleNote = (r: AgentRole) =>
  te(`config.roles.items.${r.name}.note`) ? t(`config.roles.items.${r.name}.note`) : (r.note || '')
const roleTrigger = (r: AgentRole) =>
  te(`config.roles.items.${r.name}.trigger`) ? t(`config.roles.items.${r.name}.trigger`) : ''

async function saveRoles() {
  rolesSaving.value = true
  try {
    const r = await apiPut<{ roles: AgentRole[] }>('/agent/roles', { roles: roles.value })
    roles.value = r.roles ?? []
    rolesSavedAt.value = Date.now()
    setTimeout(() => { rolesSavedAt.value = 0 }, 2000)
  } finally {
    rolesSaving.value = false
  }
}

loadRoles()


const granularityFields = [
  { key: 'estMinMin' as const },
  { key: 'estMinMax' as const },
  { key: 'acceptanceMax' as const },
  { key: 'p0SubsetMax' as const },
]
const granularity = reactive({
  estMinMin: 0,
  estMinMax: 0,
  acceptanceMax: 0,
  p0SubsetMax: 0,
})
watch(
  () => project.project?.config,
  (cfg) => {
    if (!cfg) return
    granularity.estMinMin = cfg.estMinMin
    granularity.estMinMax = cfg.estMinMax
    granularity.acceptanceMax = cfg.acceptanceMax
    granularity.p0SubsetMax = cfg.p0SubsetMax
  },
  { immediate: true },
)
function applyGranularity(key: keyof typeof granularity) {
  project.updateConfig({ [key]: granularity[key] })
}

// ==================== LLM 模型配置 ====================
const llmModels = ref<ArchLlmModel[]>([])
const llmModelId = ref('')
const importing = ref(false)
const importMsg = ref('')
const importError = ref('')
const showAddManual = ref(false)
const manualForm = reactive({ name: '', provider: '', model: '', url: '' })
const addingManual = ref(false)
// 编辑手动模型条目(配置成功后允许修改): editingManualId 非空 = 表单为编辑态
const editingManualId = ref('')
function startEditManual(m: ArchLlmModel) {
  editingManualId.value = m.id
  showAddManual.value = true
  manualForm.name = m.name
  manualForm.provider = m.provider || ''
  manualForm.model = m.model
  manualForm.url = m.url || ''
  nextTick(() => {
    document.getElementById('llm-manual-form')?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  })
}
function resetManualForm() {
  editingManualId.value = ''
  manualForm.name = ''
  manualForm.provider = ''
  manualForm.model = ''
  manualForm.url = ''
}

async function loadLlm() {
  if (!(await backendUp())) return
  try {
    const data = await apiGet<ArchLlmModelsResult>('/llm/models')
    llmModels.value = data.models ?? []
    llmModelId.value = data.modelId ?? ''
  } catch {
    // backend not ready → show nothing
  }
}

async function importModels() {
  if (!(await backendUp())) return
  importing.value = true
  importMsg.value = ''
  importError.value = ''
  try {
    const data = await apiPost<ArchLlmImportResult>('/llm/models/import')
    llmModels.value = data.models ?? []
    importMsg.value = t('config.llm.importDone', {
      added: data.added,
      preserved: data.preserved,
    })
  } catch (e: any) {
    importError.value = e?.message || t('config.llm.importFail')
  } finally {
    importing.value = false
  }
}

async function selectActiveModel(id: string) {
  llmModelId.value = id
  if (await backendUp()) {
    apiPut<{ modelId: string }>('/llm/model', { modelId: id }).catch(() => {})
  }
}

async function addManual() {
  if (!manualForm.name.trim() || !manualForm.model.trim()) return
  addingManual.value = true
  try {
    if (editingManualId.value) {
      // 编辑态: 修改既有 manual 条目
      if (await backendUp()) {
        const row = await apiPut<ArchLlmModel>(`/llm/models/manual/${editingManualId.value}`, {
          name: manualForm.name.trim(),
          provider: manualForm.provider.trim() || 'custom',
          model: manualForm.model.trim(),
          url: manualForm.url.trim(),
        })
        const i = llmModels.value.findIndex((x) => x.id === editingManualId.value)
        if (i >= 0) llmModels.value[i] = row
      } else {
        const i = llmModels.value.findIndex((x) => x.id === editingManualId.value)
        if (i >= 0) {
          llmModels.value[i] = {
            ...llmModels.value[i],
            name: manualForm.name.trim(),
            provider: manualForm.provider.trim() || 'custom',
            model: manualForm.model.trim(),
            url: manualForm.url.trim(),
          }
        }
      }
      resetManualForm()
      showAddManual.value = false
      return
    }
    if (await backendUp()) {
      const row = await apiPost<ArchLlmModel>('/llm/models/manual', {
        name: manualForm.name.trim(),
        provider: manualForm.provider.trim() || 'custom',
        model: manualForm.model.trim(),
        url: manualForm.url.trim(),
      })
      llmModels.value = [row, ...llmModels.value]
    } else {
      llmModels.value.unshift({
        source: 'manual',
        id: `man-${Date.now()}`,
        name: manualForm.name.trim(),
        provider: manualForm.provider.trim() || 'custom',
        model: manualForm.model.trim(),
        url: manualForm.url.trim(),
      })
    }
    resetManualForm()
    showAddManual.value = false
  } finally {
    addingManual.value = false
  }
}

async function removeManualModel(id: string) {
  if (await backendUp()) {
    await apiDelete<{ id: string }>(`/llm/models/${id}`).catch(() => {})
  }
  llmModels.value = llmModels.value.filter((m) => m.id !== id)
}

loadLlm()

// ── architect 实例模型连通性测试(模型下沉实例, 逐条可测) ──
const llmProbing = ref<Record<string, string>>({})
async function probeLlm(m: ArchLlmModel) {
  llmProbing.value[m.id] = '…'
  try {
    const { apiPost } = await import('@/services/api-client')
    const d = await apiPost<{ status: string; detail: string }>('/llm/models/probe', { modelId: m.id })
    llmProbing.value[m.id] = `${d.status === 'ok' ? '✓' : '✗'} ${d.detail}`
  } catch (e: any) {
    llmProbing.value[m.id] = `✗ ${e?.message || e}`
  }
}

// ── 模型能力探测(分级适配): 工具协议/JSON/指令边界 → tier 档案 ──
const capProbing = ref<Record<string, string>>({})
const capProfiles = ref<Record<string, any>>({})
async function loadProfiles() {
  try {
    const d = await apiGet<{ profiles: any[] }>('/llm/model-profiles')
    capProfiles.value = Object.fromEntries((d.profiles ?? []).map((p: any) => [p.modelId, p]))
  } catch { /* 后端未就绪静默 */ }
}
loadProfiles()
async function capabilityProbe(m: ArchLlmModel) {
  capProbing.value[m.id] = '探测中…(~9 次小调用)'
  try {
    const { apiPost } = await import('@/services/api-client')
    const d = await apiPost<any>(`/llm/models/${m.id}/capability-probe`, {})
    if (d?.reachable === false) {
      capProbing.value[m.id] = `✗ ${d.summary || '模型不可达'}`
    } else {
      capProfiles.value = { ...capProfiles.value, [m.id]: d }
      capProbing.value[m.id] = `✓ ${d.summary || `tier ${d.tier}`}`
    }
  } catch (e: any) {
    capProbing.value[m.id] = `✗ ${e?.message || e}`
  }
}
async function setManualTier(m: ArchLlmModel, tier: number) {
  try {
    const { apiPut } = await import('@/services/api-client')
    const d = await apiPut<any>(`/llm/model-profiles/${m.id}`, { tier })
    capProfiles.value = { ...capProfiles.value, [m.id]: d }
  } catch { /* 静默 */ }
}
// ── 符号源(CodeGraph)开关：三档 + 状态(KV 持久化) ──
const cgStatus = ref<CodegraphStatus | null>(null)
const cgSaving = ref(false)
const cgSyncing = ref(false)
async function loadCgStatus() {
  cgStatus.value = await semanticAssetService.codegraphStatus() ?? null
}
async function runCgSync() {
  cgSyncing.value = true
  try {
    await semanticAssetService.symbolSync()
    void loadCgStatus()
  } catch { /* 失败提示由 api 层处理 */ } finally {
    cgSyncing.value = false
  }
}
const cgColdStarting = ref(false)
const cgColdStartMsg = ref('')
async function runCgColdStart() {
  cgColdStarting.value = true
  cgColdStartMsg.value = ''
  try {
    const r = await semanticAssetService.coldStart()
    cgColdStartMsg.value = r?.message || ''
    void loadCgStatus()
  } catch (e: any) {
    cgColdStartMsg.value = e?.message || String(e)
  } finally {
    cgColdStarting.value = false
  }
}
async function setCgMode(m: 'on' | 'off' | 'auto') {
  cgSaving.value = true
  try {
    if (await semanticAssetService.setCodegraphMode(m)) void loadCgStatus()
  } finally {
    cgSaving.value = false
  }
}
onMounted(() => { void loadCgStatus() })
</script>

<template>
  <div class="p-5 space-y-4">
    <PageHeader
      :title="t('config.title')"
      :desc="t('config.desc')"
    />

    <!-- 子 tab 导航 -->
    <div class="flex flex-wrap gap-1.5">
      <button
        v-for="tb in TABS"
        :key="tb.key"
        class="btn !py-1.5 !px-4 !text-xs"
        :class="activeTab === tb.key ? 'btn-primary' : 'btn-ghost'"
        @click="activeTab = tb.key"
      >{{ t(tb.label) }}</button>
    </div>

    <!-- ═══ tab: 其他配置(其他 + 资产锁 + CodeGraph 同属此 tab, 分散两处 v-show) ═══ -->
    <div v-show="activeTab === 'other'" class="space-y-4">
      <div class="panel overflow-hidden">
        <div class="panel-header">
          <span class="flex items-center gap-2">
            <Cog6ToothIcon class="w-4 h-4 text-ctp-lavender" />{{ t('config.otherConfig') }}
          </span>
        </div>
        <div class="p-3 space-y-3 text-xs">
          <div class="border border-ctp-surface0 rounded-lg p-3">
            <div class="flex items-center gap-2">
              <span class="text-ctp-overlay1">{{ t('config.specVersion') }}</span>
              <span class="chip bg-ctp-mauve/15 text-ctp-mauve font-mono">{{ spec.spec?.version ?? '—' }}</span>
              <span class="text-ctp-overlay1 ml-2">{{ t('config.rulesCount') }}</span>
              <span class="chip bg-ctp-surface0 text-ctp-subtext1">{{ spec.ruleCount }}</span>
            </div>
          </div>
          <div class="border border-ctp-surface0 rounded-lg p-3">
            <div class="flex items-center justify-between mb-2">
              <div class="text-ctp-overlay1">
                {{ t('config.granularity') }}
              </div>
              <span class="text-[10px] text-ctp-overlay0">{{ t('config.granularityHint') }}</span>
            </div>
            <div class="grid grid-cols-2 gap-2">
              <label
                v-for="f in granularityFields"
                :key="f.key"
                class="flex items-center justify-between gap-2"
              >
                <span class="text-ctp-subtext0 text-[11px]">{{ t(`config.${f.key}`) }}</span>
                <input
                  v-model.number="granularity[f.key]"
                  type="number"
                  class="input !w-20 !py-1 !text-xs text-right"
                  @change="applyGranularity(f.key)"
                >
              </label>
            </div>
          </div>
          <div class="border border-ctp-surface0 rounded-lg p-3">
            <div class="text-ctp-overlay1 mb-1">
              {{ t('config.project') }}
            </div>
            <div class="font-mono text-ctp-sapphire truncate">
              {{ project.project?.rootPath ?? '—' }}
            </div>
            <div class="flex items-center gap-2 mt-1">
              <span class="chip bg-ctp-surface0 text-ctp-subtext1">{{ project.project?.branch ?? '—' }}</span>
              <span class="chip bg-ctp-surface0 text-ctp-subtext1 font-mono">{{ project.project?.baselineId ?? '—' }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ═══ tab: Architect 实例设置(模型) ═══ -->
    <div v-show="activeTab === 'instance'">
    <div class="panel overflow-hidden">
      <div class="panel-header">
        <span class="flex items-center gap-2">
          <Cog6ToothIcon class="w-4 h-4 text-ctp-sapphire" />{{ t('config.llm.title') }}
        </span>
        <span class="flex items-center gap-2">
          <span class="text-[11px] text-ctp-overlay1">
            {{ llmModels.length }}
          </span>
          <button
            class="btn btn-primary !py-1 !px-3 !text-xs"
            :disabled="importing"
            @click="importModels"
          >
            <ArrowDownTrayIcon class="w-3.5 h-3.5" />
            {{ importing ? t('config.llm.importing') : t('config.llm.import') }}
          </button>
          <button
            class="btn !py-1 !px-3 !text-xs"
            @click="showAddManual = !showAddManual"
          >
            <PlusIcon class="w-3.5 h-3.5" />{{ t('config.llm.addManual') }}
          </button>
        </span>
      </div>
      <div class="p-3 text-xs space-y-2">
        <div class="text-[11px] text-ctp-overlay0">{{ t('config.llm.desc') }}</div>
        <div v-if="importMsg" class="chip bg-ctp-green/15 text-ctp-green">{{ importMsg }}</div>
        <div v-if="importError" class="chip bg-ctp-red/15 text-ctp-red">{{ importError }}</div>

        <form
          v-if="showAddManual"
          class="border border-ctp-surface0 rounded-lg p-2.5 space-y-2"
          @submit.prevent="addManual"
        >
          <div v-if="editingManualId" class="text-[11px] text-ctp-blue">
            {{ t('config.llm.editingManual') }}
          </div>
          <div class="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <label class="flex flex-col gap-0.5">
              <span class="text-[11px] text-ctp-overlay1">{{ t('config.llm.manualName') }}</span>
              <input v-model="manualForm.name" class="input !py-1 !text-xs">
            </label>
            <label class="flex flex-col gap-0.5">
              <span class="text-[11px] text-ctp-overlay1">{{ t('config.llm.manualProvider') }}</span>
              <input v-model="manualForm.provider" class="input !py-1 !text-xs" placeholder="custom">
            </label>
            <label class="flex flex-col gap-0.5">
              <span class="text-[11px] text-ctp-overlay1">{{ t('config.llm.manualModel') }}</span>
              <input v-model="manualForm.model" class="input !py-1 !text-xs">
            </label>
            <label class="flex flex-col gap-0.5">
              <span class="text-[11px] text-ctp-overlay1">{{ t('config.llm.manualUrl') }}</span>
              <input v-model="manualForm.url" class="input !py-1 !text-xs">
            </label>
          </div>
          <button
            type="submit"
            class="btn btn-primary !px-3 !py-1 !text-xs"
            :disabled="addingManual || !manualForm.name || !manualForm.model"
          >{{ editingManualId ? t('config.llm.saveManual') : t('config.llm.addManual') }}</button>
          <button
            v-if="editingManualId"
            type="button"
            class="btn btn-ghost !px-3 !py-1 !text-xs"
            @click="resetManualForm(); showAddManual = false"
          >{{ t('common.cancel') }}</button>
        </form>

        <div
          v-if="!llmModels.length"
          class="text-[11px] text-ctp-overlay0 py-3 text-center"
        >{{ t('config.llm.noModels') }}</div>

        <div class="divide-y divide-ctp-surface0">
          <div
            v-for="m in llmModels"
            :key="m.id"
            class="flex items-center gap-3 py-2"
          >
            <input
              type="radio"
              :name="'llm-active'"
              class="accent-ctp-sapphire"
              :checked="llmModelId === m.id"
              :value="m.id"
              @change="selectActiveModel(m.id)"
            >
            <div class="min-w-0">
              <div class="flex items-center gap-2">
                <span class="font-mono text-ctp-text truncate">{{ m.name }}</span>
                <span
                  class="chip"
                  :class="m.source === 'manual' ? 'bg-ctp-yellow/15 text-ctp-yellow' : 'bg-ctp-blue/15 text-ctp-blue'"
                >{{ t(`config.llm.source.${m.source}`) }}</span>
                <span v-if="m.isDefault" class="chip bg-ctp-green/15 text-ctp-green">default</span>
              </div>
              <div class="text-[11px] text-ctp-subtext0 truncate">
                <span class="font-mono text-ctp-overlay1">{{ m.provider }}</span>
                <span class="mx-1">·</span>
                <span class="font-mono"> {{ m.model }}</span>
                <span v-if="m.url" class="text-ctp-overlay0"> · {{ m.url }}</span>
              </div>
            </div>
            <div class="flex-1" />
            <span
              v-if="capProfiles[m.id]"
              class="chip !text-[10px] bg-ctp-mauve/15 text-ctp-mauve font-mono"
              :title="capProfiles[m.id]?.summary || ''"
            >t{{ capProfiles[m.id].tier }}</span>
            <select
              v-if="capProfiles[m.id]"
              class="bg-ctp-surface0 text-[10px] rounded px-1 py-0.5 text-ctp-subtext0"
              :value="capProfiles[m.id].tier"
              title="手工调整能力档位(0=27B+ … 4=1-3B; 手工设定优先于探测)"
              @change="setManualTier(m, +($event.target as HTMLSelectElement).value)"
            >
              <option v-for="i in 5" :key="i" :value="i - 1">t{{ i - 1 }}</option>
            </select>
            <span
              v-if="capProbing[m.id]"
              class="text-[10px] font-mono max-w-[260px] truncate"
              :class="capProbing[m.id].startsWith('✓') ? 'text-ctp-green' : 'text-ctp-overlay0'"
              :title="capProbing[m.id]"
            >{{ capProbing[m.id] }}</span>
            <button
              class="btn !py-0 !px-2 !text-[10px]"
              :title="t('config.llm.capProbeTip')"
              @click="capabilityProbe(m)"
            >{{ t('config.llm.capProbe') }}</button>
            <button
              class="btn !py-0 !px-2 !text-[10px]"
              @click="probeLlm(m)"
            >{{ t('config.executors.modelProbe') }}</button>
            <button
              v-if="m.source === 'manual'"
              class="btn !py-0.5 !px-2 !text-[11px]"
              :title="t('config.llm.editManual')"
              @click="startEditManual(m)"
            >
              <PencilSquareIcon class="w-3 h-3" />{{ t('config.llm.editManualBtn') }}
            </button>
            <button
              v-if="m.source === 'manual'"
              class="btn !py-0.5 !px-2 !text-[11px] text-ctp-red"
              :title="t('config.llm.deleteManual')"
              @click="removeManualModel(m.id)"
            >
              <TrashIcon class="w-3 h-3" />{{ t('config.llm.delete') }}
            </button>
          </div>
        </div>
        <div class="flex gap-4 text-[10px] text-ctp-overlay0">
          <span class="flex items-center gap-1">
            <span class="text-ctp-blue">{{ t('config.llm.source.imported') }}</span>
            : {{ t('config.llm.importedNote') }}
          </span>
          <span class="flex items-center gap-1">
            <span class="text-ctp-yellow">{{ t('config.llm.source.manual') }}</span>
            : {{ t('config.llm.manualNote') }}
          </span>
        </div>
      </div>
    </div>
    </div>

    <!-- ═══ tab: Coding Agent 执行器 ═══ -->
    <div v-show="activeTab === 'executors'" class="space-y-4">
      <AgentExecutorsCard />

    </div>



    <!-- ═══ tab: 角色模型映射 ═══ -->
    <div v-show="activeTab === 'roleModels'">
    <div class="panel overflow-hidden">
      <div class="panel-header">
        <span class="flex items-center gap-2">
          <AdjustmentsHorizontalIcon class="w-4 h-4 text-ctp-mauve" />{{ t('config.roles.title') }}
        </span>
        <button
          class="btn btn-xs btn-blue"
          :disabled="rolesSaving"
          @click="saveRoles"
        >
          {{ rolesSaving ? t('config.roles.saving') : (rolesSavedAt ? t('config.roles.saved') : t('config.roles.save')) }}
        </button>
      </div>
      <div class="divide-y divide-ctp-surface0">
        <div
          v-for="r in roles"
          :key="r.name"
          class="flex items-center gap-3 px-4 py-2.5 text-xs"
        >
          <span class="w-20 font-semibold text-ctp-text shrink-0">{{ roleLabel(r) }}</span>
          <span class="flex-1 text-[10px] leading-snug">
            <span class="text-ctp-overlay1">{{ roleNote(r) }}</span>
            <span
              v-if="roleTrigger(r)"
              class="ml-1 inline-block rounded bg-ctp-peach/15 px-1.5 py-px align-baseline text-ctp-peach"
            >⚡ {{ t('config.roles.triggerLabel') }}{{ roleTrigger(r) }}</span>
          </span>
          <select v-model="r.modelId" class="input !py-1 !px-2 !text-[11px] w-64 font-mono">
            <option value="">{{ t('config.roles.modelPlaceholder') }}</option>
            <option
              v-if="r.modelId && !llmModels.some((m) => m.id === r.modelId)"
              :value="r.modelId"
            >{{ r.modelId }}（{{ t('config.roles.modelMissing') }}）</option>
            <option v-for="m in llmModels" :key="m.id" :value="m.id">
              {{ m.name }}（{{ m.model }}@{{ m.url }}）
            </option>
          </select>
        </div>
      </div>
      <p class="px-4 pb-3 text-[10px] text-ctp-overlay0 leading-relaxed">
        {{ t('config.roles.hint') }}
      </p>
    </div>
    </div>

    <!-- ═══ tab: 其他配置(续)——符号源 ═══ -->
    <div v-show="activeTab === 'other'" class="space-y-4">

      <!-- 符号源(CodeGraph)开关：语义提取的符号数据来源 -->
      <div class="panel overflow-hidden">
      <div class="panel-header">
        <span class="flex items-center gap-2">
          <AdjustmentsHorizontalIcon class="w-4 h-4 text-ctp-teal" />{{ t('config.cg.title') }}
        </span>
        <span v-if="cgStatus" class="text-[11px] text-ctp-overlay1">
          <span :class="cgStatus.cli ? 'text-ctp-green' : 'text-ctp-peach'">{{ cgStatus.cli ? t('config.cg.cliOk') : t('config.cg.cliMissing') }}</span>
          <span v-if="cgStatus.cliPath" class="font-mono" :title="cgStatus.cliPath"> · {{ cgStatus.cliPath.split('/').slice(-1)[0] }}</span>
          <span class="mx-1 text-ctp-overlay0">·</span>
          <span class="text-ctp-overlay0">{{ { env: t('config.cg.srcEnv'), kv: t('config.cg.srcKv'), default: t('config.cg.srcDefault') }[cgStatus.source] }}</span>
          <span v-if="cgStatus.native?.nodes" class="text-ctp-overlay0"> · {{ t('config.cg.nativeNodes') }}: {{ cgStatus.native.nodes.toLocaleString() }}</span>
          <span v-if="cgStatus.mergeStats" class="text-ctp-overlay0 font-mono" :title="t('config.cg.hintAuto')">
            · ∪{{ (cgStatus.mergeStats.cgNodes ?? 0).toLocaleString() }} +{{ Math.max((cgStatus.mergeStats.cgNodes ?? 0) - (cgStatus.mergeStats.cgMapped ?? 0), 0).toLocaleString() }}<template v-if="cgStatus.mergeStats.lineDrift"> ⚠{{ cgStatus.mergeStats.lineDrift }}</template>
          </span>
          <span v-if="cgStatus.state?.stale" class="text-ctp-yellow"> · {{ t('config.cg.stale') }} ({{ cgStatus.state.staleCount }})</span>
        </span>
      </div>
      <div v-if="cgStatus?.state" class="px-4 py-2 flex items-center gap-2 text-[11px] border-t border-ctp-surface0">
        <span v-if="!cgStatus.state.lastHead" class="text-ctp-overlay0">{{ t('config.cg.baselineNone') }}</span>
        <span v-else-if="cgStatus.state.stale" class="text-ctp-yellow">
          {{ t('config.cg.baselineStale') }} <span class="font-mono">{{ cgStatus.state.lastHead.slice(0, 8) }}</span> → <span class="font-mono">{{ cgStatus.state.head.slice(0, 8) }}</span>
          <span v-if="cgStatus.state.staleCount"> ({{ t('config.cg.baselineFiles') }} {{ cgStatus.state.staleCount }})</span>
        </span>
        <span v-else class="text-ctp-green">{{ t('config.cg.baselineFresh') }} <span class="font-mono">{{ cgStatus.state.head.slice(0, 8) }}</span></span>
        <span v-if="cgStatus.state.dirty" class="text-ctp-overlay0"> · {{ t('config.cg.dirty') }} {{ cgStatus.state.dirty }}</span>
        <button
          v-if="cgStatus.state.lastHead && cgStatus.state.stale"
          class="btn !py-1 !px-3 !text-xs ml-auto"
          :disabled="cgSyncing"
          @click="runCgSync"
        >{{ cgSyncing ? t('config.cg.syncing') : t('config.cg.syncNow') }}</button>
      </div>
      <div v-if="cgStatus && !cgStatus.corePid" class="px-4 py-2 flex items-center gap-2 text-[11px] border-t border-ctp-surface0">
        <span class="text-ctp-peach">{{ t('config.cg.noCoreProject') }}</span>
        <button
          class="btn !py-1 !px-3 !text-xs ml-auto"
          :disabled="cgColdStarting"
          @click="runCgColdStart"
        >{{ cgColdStarting ? t('config.cg.coldStarting') : t('config.cg.coldStart') }}</button>
      </div>
      <p v-if="cgColdStartMsg" class="px-4 pb-2 text-[10px] text-ctp-overlay0 leading-relaxed">{{ cgColdStartMsg }}</p>
      <p v-if="cgStatus?.state?.stale" class="px-4 pb-2 text-[10px] text-ctp-overlay0 leading-relaxed">
        {{ t('config.cg.syncHint') }}
      </p>
      <div class="px-4 py-3 flex items-center gap-2">
        <button
          v-for="m in (['on', 'auto', 'off'] as const)" :key="m"
          class="btn !py-1 !px-3 !text-xs"
          :class="cgStatus?.mode === m ? 'btn-primary' : 'btn-ghost'"
          :disabled="cgSaving || cgStatus?.source === 'env'"
          @click="setCgMode(m)"
        >{{ t(`config.cg.mode${m[0].toUpperCase()}${m.slice(1)}`) }}</button>
        <span v-if="cgStatus?.source === 'env'" class="text-[10px] text-ctp-peach">{{ t('config.cg.envLocked') }}</span>
      </div>
      <p class="px-4 pb-3 text-[10px] text-ctp-overlay0 leading-relaxed">
        {{ cgStatus?.mode === 'off' ? t('config.cg.hintOff') : cgStatus?.mode === 'on' ? t('config.cg.hintOn') : t('config.cg.hintAuto') }}
      </p>
      </div>
    </div>
  </div>
</template>
