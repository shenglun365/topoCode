<script setup lang="ts">
import { ref, onMounted, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useSettingsStore } from '@/stores/settings'
import { useComponentId } from '@/composables/useComponentId'
import {
  PencilSquareIcon,
  DocumentTextIcon,
  ArrowPathIcon,
  PlusIcon,
  XMarkIcon,
} from '@heroicons/vue/24/outline'

const { showId, componentId } = useComponentId('ST-009')
const { t } = useI18n()
const settingsStore = useSettingsStore()

interface TemplateItem {
  id: string
  name: string
  mode: string
  module_type: string | null
  category: string
  is_builtin: number
  locale: string
  base_id?: string
  system_prompt?: string
  user_prompt_template?: string
  tools_json?: string
  tool_strategy?: string
  output_schema_json?: string
  output_example?: string
  variables_json?: string
}

const templates = ref<TemplateItem[]>([])
const loading = ref(false)
const filterLocale = ref(settingsStore.locale || 'zh-CN')
const filterMode = ref('')

// 只显示这 5 组模板（中英文各一条）
const VISIBLE_TEMPLATE_IDS = new Set([
  'report_overall_architecture',
  'community_analyze',
  'community_name',
  'diagram_regenerate_mermaid',
  'diagram_regenerate_plantuml',
])

const editDialog = ref(false)
const editing = ref<Partial<TemplateItem>>({})
const editMode = ref<'edit' | 'create'>('create')
const editTab = ref<'basic' | 'prompts' | 'schema' | 'advanced'>('basic')

const restoreDialog = ref(false)
const restoreLoading = ref(false)

async function loadTemplates() {
  loading.value = true
  try {
    const res = await window.api.promptTemplate.list({
      locale: filterLocale.value === 'all' ? undefined : filterLocale.value,
      mode: filterMode.value || undefined,
    })
    // 只保留允许的模板，其余隐藏但保留在数据库中
    const allTmpls = (res.templates || []) as TemplateItem[]
    templates.value = allTmpls.filter(t => {
      const baseId = (t as any).base_id || t.id.replace(/__.*$/, '')
      return VISIBLE_TEMPLATE_IDS.has(baseId)
    })
  } catch (e) {
    console.error('[TemplateManager] Failed to load templates:', e)
  } finally {
    loading.value = false
  }
}

function openEdit(tmpl: TemplateItem) {
  editing.value = { ...tmpl }
  editMode.value = 'edit'
  editDialog.value = true
}

function openCreate() {
  editing.value = {
    id: '',
    name: '',
    mode: 'chat',
    module_type: 'project_analysis',
    category: '',
    locale: filterLocale.value === 'all' ? 'zh-CN' : filterLocale.value,
    is_builtin: 0,
    system_prompt: '',
    user_prompt_template: '',
  }
  editMode.value = 'create'
  editDialog.value = true
}

async function saveTemplate() {
  if (!editing.value.name?.trim()) return
  try {
    if (editMode.value === 'create') {
      await window.api.promptTemplate.create({
        name: editing.value.name!,
        mode: editing.value.mode || 'chat',
        moduleType: editing.value.module_type || undefined,
        category: editing.value.category || 'general',
        locale: editing.value.locale || 'zh-CN',
        systemPrompt: editing.value.system_prompt,
        userPromptTemplate: editing.value.user_prompt_template,
        toolsJson: editing.value.tools_json,
        toolStrategy: editing.value.tool_strategy,
        outputSchemaJson: editing.value.output_schema_json,
        outputExample: editing.value.output_example,
        variablesJson: editing.value.variables_json,
      })
    } else {
      const params: Record<string, any> = { templateId: editing.value.id }
      if (editing.value.name !== undefined) params.name = editing.value.name
      if (editing.value.system_prompt !== undefined) params.system_prompt = editing.value.system_prompt
      if (editing.value.user_prompt_template !== undefined) params.user_prompt_template = editing.value.user_prompt_template
      if (editing.value.category !== undefined) params.category = editing.value.category
      if (editing.value.locale !== undefined) params.locale = editing.value.locale
      if (editing.value.tools_json !== undefined) params.tools_json = editing.value.tools_json
      if (editing.value.tool_strategy !== undefined) params.tool_strategy = editing.value.tool_strategy
      if (editing.value.output_schema_json !== undefined) params.output_schema_json = editing.value.output_schema_json
      if (editing.value.output_example !== undefined) params.output_example = editing.value.output_example
      if (editing.value.variables_json !== undefined) params.variables_json = editing.value.variables_json
      await window.api.promptTemplate.update(params)
    }
    editDialog.value = false
    await loadTemplates()
  } catch (e: any) {
    console.error('[TemplateManager] Save failed:', e)
    alert(e.message || String(e))
  }
}

async function restoreDefaults() {
  restoreLoading.value = true
  try {
    const locale = filterLocale.value === 'all' ? undefined : filterLocale.value
    await window.api.promptTemplate.restoreDefaults({ locale })
    restoreDialog.value = false
    await loadTemplates()
  } catch (e: any) {
    console.error('[TemplateManager] Restore failed:', e)
    alert(e.message || String(e))
  } finally {
    restoreLoading.value = false
  }
}

const locales = [
  { value: 'all', key: 'settings.templateAllLocales' },
  { value: 'zh-CN', key: 'settings.simplifiedChinese' },
  { value: 'en-US', key: 'settings.english' },
]

const modes = [
  { value: '', key: 'settings.templateAllModes' },
  { value: 'chat', key: 'settings.templateModeChat' },
  { value: 'structured', key: 'settings.templateModeStructured' },
  { value: 'tools', key: 'settings.templateModeTools' },
]

const defaultTemplateLocale = ref('zh-CN')

async function loadDefaultLocale() {
  try {
    const res = await window.api.promptTemplate.getDefaultLocale()
    if (res?.locale) defaultTemplateLocale.value = res.locale
  } catch (_) {}
}

async function setDefaultTemplateLocale(locale: string) {
  try {
    await window.api.promptTemplate.setDefaultLocale({ locale })
    defaultTemplateLocale.value = locale
  } catch (e: any) {
    console.error('[TemplateManager] Failed to set default locale:', e)
  }
}

const editTabs = [
  { id: 'basic' as const, label: t('settings.templateTabBasic') },
  { id: 'prompts' as const, label: t('settings.templateTabPrompts') },
  { id: 'schema' as const, label: t('settings.templateTabSchema') },
  { id: 'advanced' as const, label: t('settings.templateTabAdvanced') },
]

watch(filterLocale, () => loadTemplates())
watch(filterMode, () => loadTemplates())

onMounted(() => {
  loadTemplates()
  loadDefaultLocale()
})
</script>

<template>
  <div class="template-manager">
    <span v-if="showId" class="cmp-id">{{ componentId }}</span>
    <h2 style="font-size:16px; font-weight:600; margin-bottom:16px;">
      {{ t('settings.templateManager') }}
    </h2>

    <!-- 默认模板语言设置 -->
    <div class="default-locale-bar">
      <span class="default-locale-label">{{ t('settings.templateDefaultLocaleLabel') }}</span>
      <select
        class="select"
        :value="defaultTemplateLocale"
        @change="setDefaultTemplateLocale(($event.target as HTMLSelectElement).value)"
      >
        <option value="zh-CN">{{ t('settings.simplifiedChinese') }}</option>
        <option value="en-US">{{ t('settings.english') }}</option>
      </select>
    </div>

    <!-- 工具栏 -->
    <div class="toolbar">
      <div class="filters">
        <select v-model="filterLocale" class="select">
          <option v-for="loc in locales" :key="loc.value" :value="loc.value">
            {{ t(loc.key) }}
          </option>
        </select>
        <select v-model="filterMode" class="select">
          <option v-for="m in modes" :key="m.value" :value="m.value">
            {{ t(m.key) }}
          </option>
        </select>
      </div>
      <div class="actions">
        <button class="btn btn-ghost btn-sm" @click="restoreDialog = true">
          <ArrowPathIcon class="w-4 h-4" />
          <span>{{ t('settings.templateRestoreDefaults') }}</span>
        </button>
        <button class="btn btn-primary btn-sm" @click="openCreate">
          <PlusIcon class="w-4 h-4" />
          <span>{{ t('settings.templateCreate') }}</span>
        </button>
      </div>
    </div>

    <!-- 模板列表 -->
    <div v-if="loading" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="templates.length === 0" class="empty-state">
      <DocumentTextIcon class="icon" />
      <div class="title">{{ t('settings.templateEmpty') }}</div>
    </div>
    <div v-else class="template-list">
      <div v-for="tmpl in templates" :key="tmpl.id" class="template-item">
        <div class="template-info">
          <div class="template-name">{{ tmpl.name }}</div>
          <div class="template-meta">
            <span class="badge badge-mode">{{ tmpl.mode }}</span>
            <span v-if="tmpl.module_type" class="badge badge-module">{{ tmpl.module_type }}</span>
            <span v-if="tmpl.category" class="badge badge-category">{{ tmpl.category }}</span>
            <span class="badge badge-locale">{{ tmpl.locale }}</span>
            <span v-if="tmpl.is_builtin" class="badge badge-builtin">{{ t('settings.templateBuiltin') }}</span>
          </div>
        </div>
        <div class="template-actions">
          <button class="btn btn-ghost btn-xs" @click="openEdit(tmpl)">
            <PencilSquareIcon class="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>

    <!-- 编辑/新建弹窗 -->
    <Teleport to="body">
      <div v-if="editDialog" class="modal-overlay">
        <div class="modal template-edit-modal">
          <div class="modal-header">
            <div style="display:flex; flex-direction:column; gap:4px;">
              <span class="modal-title">
                {{ editMode === 'create' ? t('settings.templateCreate') : t('settings.templateEdit') }}
              </span>
              <span class="modal-hint">{{ t('settings.templateEditHint') }}</span>
            </div>
            <button class="btn btn-ghost btn-xs" @click="editDialog = false">
              <XMarkIcon class="w-4 h-4" />
            </button>
          </div>

          <!-- 子 Tab 切换 -->
          <div class="edit-tabs">
            <button
              v-for="tab in editTabs"
              :key="tab.id"
              class="edit-tab"
              :class="{ active: editTab === tab.id }"
              @click="editTab = tab.id"
            >{{ tab.label }}</button>
          </div>

          <div class="modal-body">
            <!-- 基本信息 -->
            <div v-show="editTab === 'basic'" class="tab-content">
              <div class="form-grid-2">
                <div class="form-group">
                  <label class="form-label">{{ t('settings.templateName') }}</label>
                  <input v-model="editing.name" class="input" />
                </div>
                <div class="form-group">
                  <label class="form-label">{{ t('settings.templateMode') }}</label>
                  <select v-model="editing.mode" class="select">
                    <option value="chat">chat</option>
                    <option value="structured">structured</option>
                    <option value="tools">tools</option>
                  </select>
                </div>
                <div class="form-group">
                  <label class="form-label">{{ t('settings.templateModuleType') }}</label>
                  <select v-model="editing.module_type" class="select">
                    <option value="">{{ t('common.none') }}</option>
                    <option value="project_analysis">project_analysis</option>
                    <option value="project_resource">project_resource</option>
                    <option value="knowledge_base">knowledge_base</option>
                    <option value="ai_assistant">ai_assistant</option>
                  </select>
                </div>
                <div class="form-group">
                  <label class="form-label">{{ t('settings.templateCategory') }}</label>
                  <input v-model="editing.category" class="input" />
                </div>
                <div class="form-group">
                  <label class="form-label">{{ t('settings.templateLocale') }}</label>
                  <select v-model="editing.locale" class="select">
                    <option value="zh-CN">zh-CN</option>
                    <option value="en-US">en-US</option>
                  </select>
                </div>
              </div>
            </div>

            <!-- 提示词 -->
            <div v-show="editTab === 'prompts'" class="tab-content">
              <div class="form-group">
                <label class="form-label">{{ t('settings.templateSystemPrompt') }}</label>
                <textarea v-model="editing.system_prompt" class="textarea textarea-code" rows="10"></textarea>
              </div>
              <div class="form-group">
                <label class="form-label">{{ t('settings.templateUserPrompt') }}</label>
                <textarea v-model="editing.user_prompt_template" class="textarea textarea-code" rows="10"></textarea>
              </div>
            </div>

            <!-- Schema -->
            <div v-show="editTab === 'schema'" class="tab-content">
              <div class="form-group">
                <label class="form-label">{{ t('settings.templateOutputSchema') }}</label>
                <textarea v-model="editing.output_schema_json" class="textarea textarea-code" rows="10"></textarea>
              </div>
              <div class="form-group">
                <label class="form-label">{{ t('settings.templateOutputExample') }}</label>
                <textarea v-model="editing.output_example" class="textarea textarea-code" rows="6"></textarea>
              </div>
            </div>

            <!-- 高级 -->
            <div v-show="editTab === 'advanced'" class="tab-content">
              <div class="form-group">
                <label class="form-label">{{ t('settings.templateVariables') }}</label>
                <textarea v-model="editing.variables_json" class="textarea textarea-code" rows="8"></textarea>
              </div>
              <div class="form-group">
                <label class="form-label">{{ t('settings.templateToolsJson') }}</label>
                <textarea v-model="editing.tools_json" class="textarea textarea-code" rows="4"></textarea>
              </div>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn btn-ghost btn-sm" @click="editDialog = false">
              {{ t('common.cancel') }}
            </button>
            <button class="btn btn-primary btn-sm" @click="saveTemplate">
              {{ t('common.save') }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- 恢复默认弹窗 -->
    <Teleport to="body">
      <div v-if="restoreDialog" class="modal-overlay">
        <div class="modal">
          <div class="modal-header">
            <span class="modal-title">{{ t('settings.templateRestoreDefaults') }}</span>
            <button class="btn btn-ghost btn-xs" @click="restoreDialog = false">
              <XMarkIcon class="w-4 h-4" />
            </button>
          </div>
          <div class="modal-body">
            <p>{{ t('settings.templateRestoreConfirm') }}</p>
          </div>
          <div class="modal-footer">
            <button class="btn btn-ghost btn-sm" @click="restoreDialog = false">
              {{ t('common.cancel') }}
            </button>
            <button class="btn btn-primary btn-sm" :disabled="restoreLoading" @click="restoreDefaults">
              <ArrowPathIcon v-if="restoreLoading" class="w-4 h-4 animate-spin" />
              <span>{{ t('common.confirm') }}</span>
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.template-manager {
  max-width: 900px;
}
.default-locale-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  margin-bottom: 14px;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 8px;
}
.default-locale-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-primary);
  white-space: nowrap;
}
.default-locale-bar .select {
  width: auto;
  min-width: 140px;
  padding: 6px 10px;
  font-size: 12px;
}
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  gap: 12px;
  flex-wrap: wrap;
}
.filters {
  display: flex;
  gap: 8px;
}
.actions {
  display: flex;
  gap: 8px;
}
.template-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: 8px;
  margin-bottom: 8px;
  background: var(--bg-primary);
  transition: box-shadow 0.15s;
}
.template-item:hover {
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
}
.template-info {
  flex: 1;
  min-width: 0;
}
.template-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 5px;
}
.template-meta {
  display: flex;
  gap: 5px;
  flex-wrap: wrap;
}
.template-actions {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
  margin-left: 12px;
}
.badge {
  font-size: 10px;
  padding: 2px 8px;
  border-radius: 4px;
  white-space: nowrap;
  font-weight: 500;
  line-height: 1.4;
}
.badge-mode {
  background: var(--accent);
  color: #fff;
}
.badge-module {
  background: var(--bg-secondary);
  color: var(--text-secondary);
  border: 1px solid var(--border);
}
.badge-category {
  background: var(--bg-secondary);
  color: var(--text-secondary);
  border: 1px solid var(--border);
}
.badge-locale {
  background: #dbeafe;
  color: #1e40af;
}
.badge-builtin {
  background: #dcfce7;
  color: #166534;
}

/* 基本信息表单网格 — 两列 */
.form-grid-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px 20px;
}
.form-grid-2 .form-group {
  margin-bottom: 0;
}

/* 弹窗背景 */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
}

.modal {
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg, 8px);
  max-width: 100%;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.template-edit-modal {
  width: 740px;
  max-height: 86vh;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.4);
}

.modal-header {
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
}
.modal-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}
.modal-hint {
  font-size: 11px;
  color: var(--text-muted);
  line-height: 1.4;
}
.modal-body {
  padding: 20px;
  overflow-y: auto;
  flex: 1;
}
.modal-footer {
  padding: 12px 20px;
  border-top: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-shrink: 0;
}

/* 子 Tab 切换条 */
.edit-tabs {
  display: flex;
  border-bottom: 1px solid var(--border);
  padding: 0 20px;
  background: var(--bg-secondary);
  flex-shrink: 0;
}
.edit-tab {
  padding: 10px 20px;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-muted);
  cursor: pointer;
  border-bottom: 2px solid transparent;
  background: none;
  border-top: none;
  border-left: none;
  border-right: none;
  transition: all 0.15s;
  margin-bottom: -1px;
}
.edit-tab:hover {
  color: var(--text-primary);
  background: var(--bg-hover);
}
.edit-tab.active {
  color: var(--accent);
  border-bottom-color: var(--accent);
}

.tab-content {
  padding: 4px 0;
}

/* 表单 */
.form-group {
  margin-bottom: 16px;
}
.form-label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 6px;
  letter-spacing: 0.02em;
}
.input, .select, .textarea {
  width: 100%;
  padding: 8px 12px;
  font-size: 13px;
  color: var(--text-primary);
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: 6px;
  outline: none;
  transition: border-color 0.15s, box-shadow 0.15s;
  box-sizing: border-box;
}
.input:focus, .select:focus, .textarea:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 20%, transparent);
}
.textarea {
  resize: vertical;
  font-family: inherit;
  line-height: 1.5;
}
.textarea-code {
  font-family: 'SF Mono', 'Fira Code', 'Cascadia Code', 'Consolas', monospace;
  font-size: 12px;
  line-height: 1.6;
  tab-size: 2;
}
.select {
  cursor: pointer;
  appearance: auto;
}

.empty-state {
  text-align: center;
  padding: 40px 20px;
  color: var(--text-muted);
}
.empty-state .icon {
  width: 48px;
  height: 48px;
  margin: 0 auto 12px;
  opacity: 0.4;
}
.loading {
  text-align: center;
  padding: 40px;
  color: var(--text-muted);
}
</style>
