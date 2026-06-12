<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useComponentId } from '@/composables/useComponentId'

const { t } = useI18n()

const props = defineProps<{
  visible: boolean
  projectName: string
  projectId: string
  currentGroupIds: string[]
  groups: { id: string; name: string; children?: { id: string; name: string }[] }[]
}>()

const emit = defineEmits<{
  close: []
  confirm: [payload: { newName: string; newGroupIds: string[] }]
  'open-group-manager': []
}>()

const editNameInput = ref(props.projectName)
const selectedGroupIds = ref<string[]>([])
const { showId, componentId } = useComponentId('EP-001')

watch(() => props.visible, (val) => {
  if (val) {
    editNameInput.value = props.projectName
    selectedGroupIds.value = [...props.currentGroupIds]
  }
})

function flattenGroups(nodes: typeof props.groups): typeof props.groups {
  const flat: typeof props.groups = []
  for (const node of nodes) {
    flat.push(node)
    if (node.children) flat.push(...flattenGroups(node.children))
  }
  return flat
}

function toggleGroupSelect(id: string) {
  const idx = selectedGroupIds.value.indexOf(id)
  if (idx >= 0) selectedGroupIds.value.splice(idx, 1)
  else selectedGroupIds.value.push(id)
}

function handleConfirm() {
  const newName = editNameInput.value.trim()
  if (!newName) return
  emit('confirm', { newName, newGroupIds: selectedGroupIds.value })
}
</script>

<template>
  <span
    v-if="showId"
    class="cmp-id"
  >{{ componentId }}</span>
  <Teleport to="body">
    <div
      v-if="visible"
      class="dialog-overlay"
      @click.self="emit('close')"
    >
      <div
        class="dialog"
        style="width:400px;"
      >
        <div class="dialog-header">
          <h3>{{ t('project.editInfo') }}</h3>
          <button
            class="btn btn-ghost btn-sm"
            @click="emit('close')"
          >
            &times;
          </button>
        </div>
        <div class="dialog-body">
          <div class="form-field">
            <label class="field-label">{{ t('project.name') }}</label>
            <input
              v-model="editNameInput"
              type="text"
              class="field-input"
              style="width:100%;"
            >
          </div>
          <div
            class="form-field"
            style="margin-top:12px;"
          >
            <label class="field-label">{{ t('project.groups') }}</label>
            <div style="max-height:200px; overflow-y:auto; border:1px solid var(--border); border-radius:6px; padding:4px;">
              <div
                v-for="node in flattenGroups(groups)"
                :key="node.id"
                class="group-item"
                :class="{ selected: selectedGroupIds.includes(node.id) }"
                @click="toggleGroupSelect(node.id)"
              >
                <span class="group-check">{{ selectedGroupIds.includes(node.id) ? '✓' : '' }}</span>
                <span>{{ node.name }}</span>
              </div>
            </div>
            <button
              class="btn btn-ghost btn-xs"
              style="margin-top:4px;"
              @click="emit('open-group-manager')"
            >
              {{ t('project.manageGroups') }}
            </button>
          </div>
        </div>
        <div class="dialog-footer">
          <button
            class="btn btn-ghost"
            @click="emit('close')"
          >
            {{ t('common.cancel') }}
          </button>
          <button
            class="btn btn-primary"
            @click="handleConfirm"
          >
            {{ t('common.confirm') }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.dialog {
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  max-height: 80vh;
  box-shadow: 0 8px 32px rgba(0,0,0,0.2);
}

.dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
}

.dialog-header h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.dialog-body {
  padding: 16px;
  overflow-y: auto;
}

.dialog-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid var(--border);
}

.form-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.field-label {
  font-size: 11px;
  font-weight: 500;
  color: var(--text-secondary);
}

.field-input {
  padding: 6px 10px;
  font-size: 12px;
  color: var(--text-primary);
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: 6px;
  outline: none;
  box-sizing: border-box;
}

.field-input:focus {
  border-color: var(--accent);
}

.group-item {
  display: flex; align-items: center; gap: 6px; padding: 5px 8px;
  border-radius: 4px; cursor: pointer; font-size: 12px;
}
.group-item:hover { background: var(--bg-hover); }
.group-item.selected { background: var(--bg-active); }
.group-check { width: 16px; text-align: center; font-size: 11px; color: var(--accent); }
</style>
