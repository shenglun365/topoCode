<template>
  <div class="right-panel-tabs">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <div class="tab-bar">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        class="tab-btn"
        :class="{ active: activeTab === tab.key }"
        @click="emit('tab-change', { tab: tab.key })"
      >
        <component
          :is="tab.icon"
          class="w-4 h-4"
        />
        <span class="tab-label">{{ tab.label }}</span>
      </button>
    </div>

    <div class="tab-content">
      <!-- 代码解析 Tab -->
      <div
        v-if="activeTab === 'code'"
        class="code-parse-tab"
      >
        <div
          v-if="!selectedFile"
          class="empty-state"
        >
          <CodeBracketIcon class="w-12 h-12 empty-icon" />
          <p class="empty-text">
            {{ t('coder.selectFileToParse') }}
          </p>
        </div>
        <div
          v-else
          class="file-tree-preview"
        >
          <div class="file-header">
            <DocumentTextIcon class="w-4 h-4" />
            <span class="file-name">{{ selectedFile }}</span>
          </div>
          <div class="parse-info">
            <div class="info-row">
              <span class="info-label">{{ t('coder.fileType') }}:</span>
              <span class="info-value">{{ getFileType(selectedFile) }}</span>
            </div>
            <div class="info-row">
              <span class="info-label">{{ t('coder.lineCount') }}:</span>
              <span class="info-value">{{ lineCount }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 知识库 Tab -->
      <div
        v-else-if="activeTab === 'knowledge'"
        class="knowledge-tab"
      >
        <div
          v-if="knowledgeDocs.length === 0"
          class="empty-state"
        >
          <BookOpenIcon class="w-12 h-12 empty-icon" />
          <p class="empty-text">
            {{ t('coder.noRelatedKnowledge') }}
          </p>
        </div>
        <div
          v-else
          class="knowledge-list"
        >
          <div
            v-for="doc in knowledgeDocs"
            :key="doc.id"
            class="knowledge-item"
            @click="openDoc(doc.id)"
          >
            <DocumentTextIcon class="w-4 h-4 knowledge-icon" />
            <div class="knowledge-info">
              <span class="knowledge-title">{{ doc.title }}</span>
              <span class="knowledge-desc">{{ doc.description }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Spec Tab -->
      <div
        v-else-if="activeTab === 'spec'"
        class="spec-tab"
      >
        <div
          v-if="specs.length === 0"
          class="empty-state"
        >
          <DocumentTextIcon class="w-12 h-12 empty-icon" />
          <p class="empty-text">
            {{ t('coder.noSpecs') }}
          </p>
        </div>
        <div
          v-else
          class="spec-list"
        >
          <SpecCard
            v-for="spec in specs"
            :key="spec.id"
            :spec="spec"
            @view="viewSpec"
            @edit="editSpec"
          />
        </div>
      </div>

      <!-- 任务配置 Tab -->
      <div
        v-else-if="activeTab === 'task'"
        class="task-config-tab"
      >
        <div class="config-form">
          <div class="form-group">
            <label class="form-label">{{ t('coder.taskName') }}</label>
            <input
              v-model="taskConfig.name"
              type="text"
              class="form-input"
              :placeholder="t('coder.taskNamePlaceholder')"
            >
          </div>
          <div class="form-group">
            <label class="form-label">{{ t('coder.taskType') }}</label>
            <select
              v-model="taskConfig.type"
              class="form-select"
            >
              <option value="analysis">
                {{ t('coder.taskTypeAnalysis') }}
              </option>
              <option value="design">
                {{ t('coder.taskTypeDesign') }}
              </option>
              <option value="refactor">
                {{ t('coder.taskTypeRefactor') }}
              </option>
            </select>
          </div>
          <div class="form-group">
            <label class="form-label">{{ t('coder.agentSelect') }}</label>
            <select
              v-model="taskConfig.agent"
              class="form-select"
            >
              <option value="">
                {{ t('coder.defaultAgent') }}
              </option>
              <option
                v-for="agent in agents"
                :key="agent.id"
                :value="agent.id"
              >
                {{ agent.name }}
              </option>
            </select>
          </div>
          <button
            class="submit-btn"
            @click="submitConfig"
          >
            {{ t('coder.submitTask') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  CodeBracketIcon,
  BookOpenIcon,
  DocumentTextIcon,
  Cog6ToothIcon,
} from '@heroicons/vue/24/outline'
import SpecCard from './SpecCard.vue'
import type { SpecDoc } from './SpecCard.vue'
import type { KnowledgeDoc, AgentConfigItem } from '@/types/ipc'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('CD-004')
const { t } = useI18n()

const props = defineProps<{
  activeTab: string
  selectedFile?: string
  knowledgeDocs?: KnowledgeDoc[]
  specs?: SpecDoc[]
  agents?: AgentConfigItem[]
}>()

const emit = defineEmits<{
  'tab-change': [tab: string]
  'open-doc': [docId: string]
  'view-spec': [specId: string]
  'edit-spec': [specId: string]
  'submit-task': [config: Record<string, string>]
}>()

const tabs = [
  { key: 'code', label: t('coder.codeParse'), icon: CodeBracketIcon },
  { key: 'knowledge', label: t('coder.knowledge'), icon: BookOpenIcon },
  { key: 'spec', label: t('coder.spec'), icon: DocumentTextIcon },
  { key: 'task', label: t('coder.taskConfig'), icon: Cog6ToothIcon },
]

const taskConfig = ref({
  name: '',
  type: 'analysis',
  agent: '',
})

const lineCount = computed(() => Math.floor(Math.random() * 500) + 50)

function getFileType(filename: string): string {
  const ext = filename.split('.').pop()?.toLowerCase() || ''
  const types: Record<string, string> = {
    ts: 'TypeScript',
    js: 'JavaScript',
    py: 'Python',
    go: 'Go',
    java: 'Java',
    rs: 'Rust',
  }
  return types[ext] || ext.toUpperCase()
}

function openDoc(docId: string) {
  emit('open-doc', docId)
}

function viewSpec(specId: string) {
  emit('view-spec', specId)
}

function editSpec(specId: string) {
  emit('edit-spec', specId)
}

function submitConfig() {
  emit('submit-task', taskConfig.value)
}
</script>

<style scoped lang="scss">
.right-panel-tabs {
  @apply flex flex-col h-full;
}

.tab-bar {
  @apply flex border-b border-[--border] bg-[--bg-secondary];
}

.tab-btn {
  @apply flex items-center gap-1.5 px-3 py-2 text-xs text-[--text-secondary] border-b-2 border-transparent hover:text-[--text-primary] hover:border-[--accent] transition-colors flex-1 justify-center;

  &.active {
    @apply text-[--accent] border-[--accent];
  }
}

.tab-label {
  @apply hidden sm:block;
}

.tab-content {
  @apply flex-1 overflow-y-auto p-3;
}

.empty-state {
  @apply flex flex-col items-center justify-center h-full text-center;
}

.empty-icon {
  @apply text-[--text-muted] mb-2;
}

.empty-text {
  @apply text-xs text-[--text-muted];
}

.file-tree-preview {
  @apply bg-[--bg-tertiary] rounded-lg p-3;
}

.file-header {
  @apply flex items-center gap-2 mb-2;
}

.file-name {
  @apply text-xs font-medium text-[--text-primary];
}

.parse-info {
  @apply flex flex-col gap-1;
}

.info-row {
  @apply flex justify-between text-xs;
}

.info-label {
  @apply text-[--text-muted];
}

.info-value {
  @apply text-[--text-secondary];
}

.knowledge-list {
  @apply flex flex-col gap-2;
}

.knowledge-item {
  @apply flex items-start gap-2 p-2 rounded bg-[--bg-tertiary] hover:bg-[--bg-hover] cursor-pointer transition-colors;
}

.knowledge-icon {
  @apply text-[--accent] mt-0.5;
}

.knowledge-info {
  @apply flex-1 min-w-0;
}

.knowledge-title {
  @apply block text-xs font-medium text-[--text-primary] truncate;
}

.knowledge-desc {
  @apply block text-xs text-[--text-muted] truncate;
}

.spec-list {
  @apply flex flex-col gap-3;
}

.config-form {
  @apply flex flex-col gap-3;
}

.form-group {
  @apply flex flex-col gap-1;
}

.form-label {
  @apply text-xs text-[--text-secondary];
}

.form-input {
  @apply w-full px-3 py-2 text-xs rounded bg-[--bg-tertiary] border border-[--border] text-[--text-primary] focus:border-[--accent] focus:outline-none;
}

.form-select {
  @apply w-full px-3 py-2 text-xs rounded bg-[--bg-tertiary] border border-[--border] text-[--text-primary] focus:border-[--accent] focus:outline-none;
}

.submit-btn {
  @apply w-full px-3 py-2 text-xs rounded bg-[--accent] text-white hover:bg-[--accent-hover] transition-colors;
}
</style>
