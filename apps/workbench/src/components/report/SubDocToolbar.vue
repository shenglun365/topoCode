<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowLeftIcon, ArrowPathIcon, GlobeAltIcon, PencilIcon } from '@heroicons/vue/24/outline'
import { useComponentId } from '@topo/web-core/composables/useComponentId'

const props = defineProps<{
  title: string
  canOpenInBrowser: boolean
  /** 社区文档上下文允许点击标题改名（写 name_manual，人工名优先级最高） */
  canRename?: boolean
}>()

const emit = defineEmits<{
  close: []
  refresh: []
  'open-browser': []
  edit: []
  rename: [name: string]
}>()

const { t } = useI18n()
const { showId, componentId } = useComponentId('ST-001')

const editingTitle = ref(false)
const titleDraft = ref('')

watch(() => props.title, () => {
  editingTitle.value = false
  titleDraft.value = ''
})

function startRename() {
  if (!props.canRename || editingTitle.value) return
  titleDraft.value = props.title || ''
  editingTitle.value = true
}

function commitRename() {
  if (!editingTitle.value) return
  const next = titleDraft.value.trim()
  editingTitle.value = false
  if (next && next !== (props.title || '').trim()) emit('rename', next)
}

function cancelRename() {
  editingTitle.value = false
  titleDraft.value = ''
}
</script>

<template>
  <span
    v-if="showId"
    class="cmp-id"
  >{{ componentId }}</span>
  <div class="subdoc-toolbar">
    <div class="toolbar-left">
      <button
        class="btn btn-ghost btn-sm"
        @click="emit('close')"
      >
        <ArrowLeftIcon class="w-4 h-4" />
        <span>{{ t('report.backToReport') }}</span>
      </button>
      <input
        v-if="editingTitle"
        v-model="titleDraft"
        class="doc-title-input"
        :placeholder="t('report.renamePlaceholder')"
        @keydown.enter.prevent="commitRename"
        @keydown.esc.prevent="cancelRename"
        @blur="commitRename"
      />
      <span
        v-else
        class="doc-title"
        :class="{ 'doc-title-editable': canRename }"
        :title="canRename ? t('report.renameHint') : title"
        @click="startRename"
      >{{ title }}</span>
    </div>
    <div class="toolbar-right">
      <button
        class="btn btn-ghost btn-sm"
        @click="emit('refresh')"
      >
        <ArrowPathIcon class="w-3.5 h-3.5" />
        <span>{{ t('common.refresh') }}</span>
      </button>
      <button
        v-if="canOpenInBrowser"
        class="btn btn-ghost btn-sm"
        @click="emit('open-browser')"
      >
        <GlobeAltIcon class="w-4 h-4" />
        <span>{{ t('settings.openInBrowser') }}</span>
      </button>
      <button
        class="btn btn-ghost btn-sm"
        @click="emit('edit')"
      >
        <PencilIcon class="w-3.5 h-3.5" />
        <span>{{ t('common.edit') }}</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.subdoc-toolbar {
  display: flex; align-items: center; justify-content: space-between;
  padding: calc(6px * var(--ui-scale, 1)) calc(12px * var(--ui-scale, 1)); border-bottom: 1px solid var(--border);
  background: var(--bg-secondary); gap: calc(8px * var(--ui-scale, 1));
}
.toolbar-left { display: flex; align-items: center; gap: calc(8px * var(--ui-scale, 1)); min-width: 0; }
.toolbar-right { display: flex; align-items: center; gap: calc(4px * var(--ui-scale, 1)); }
.doc-title { font-size: calc(13px * var(--ui-scale, 1)); font-weight: 600; color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.doc-title-editable { cursor: text; border-bottom: 1px dashed var(--border); padding-bottom: 1px; }
.doc-title-input {
  font-size: calc(13px * var(--ui-scale, 1)); font-weight: 600; color: var(--text-primary);
  background: var(--bg-primary); border: 1px solid var(--border); border-radius: 4px;
  padding: 2px 6px; min-width: 120px; max-width: 280px; outline: none;
}
.doc-title-input:focus { border-color: var(--accent, var(--text-primary)); }
</style>
