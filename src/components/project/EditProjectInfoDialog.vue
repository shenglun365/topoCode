<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

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
.group-item {
  display: flex; align-items: center; gap: 6px; padding: 5px 8px;
  border-radius: 4px; cursor: pointer; font-size: 12px;
}
.group-item:hover { background: var(--bg-hover); }
.group-item.selected { background: var(--bg-active); }
.group-check { width: 16px; text-align: center; font-size: 11px; color: var(--accent); }
</style>
