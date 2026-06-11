<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { XMarkIcon, CheckIcon } from '@heroicons/vue/24/outline'

interface FilterNode {
  id: string
  label: string
  nodeCount?: number
}

const props = defineProps<{
  nodes: FilterNode[]
  hiddenIds: Set<string>
  visible: boolean
}>()

const emit = defineEmits<{
  'update:hiddenIds': [ids: Set<string>]
  'update:visible': [visible: boolean]
  'close': []
}>()

const { t } = useI18n()

const search = ref('')

const filtered = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return props.nodes
  return props.nodes.filter(n =>
    n.label.toLowerCase().includes(q) ||
    n.id.toLowerCase().includes(q)
  )
})

function isHidden(id: string): boolean {
  return props.hiddenIds.has(id)
}

function toggle(id: string) {
  const next = new Set(props.hiddenIds)
  if (next.has(id)) {
    next.delete(id)
  } else {
    next.add(id)
  }
  emit('update:hiddenIds', next)
}

function selectAll() {
  emit('update:hiddenIds', new Set())
}

function deselectAll() {
  emit('update:hiddenIds', new Set(props.nodes.map(n => n.id)))
}

function invert() {
  const next = new Set<string>()
  for (const n of props.nodes) {
    if (!props.hiddenIds.has(n.id)) {
      next.add(n.id)
    }
  }
  emit('update:hiddenIds', next)
}

watch(search, () => {})
</script>

<template>
  <div v-if="visible" class="nfp-overlay" @click.self="emit('close')">
    <div class="nfp-panel">
      <div class="nfp-header">
        <span class="nfp-title">{{ t('report.nodeFilter', '节点筛选') }}</span>
        <button class="nfp-close" @click="emit('close')">
          <XMarkIcon class="w-3.5 h-3.5" />
        </button>
      </div>
      <div class="nfp-search">
        <input
          v-model="search"
          type="text"
          :placeholder="t('report.searchCommunity', '搜索...')"
          class="nfp-search-input"
        />
      </div>
      <div class="nfp-actions">
        <button class="nfp-action-btn" @click="selectAll">
          <CheckIcon class="w-3 h-3" /> {{ t('report.selectAll', '全选') }}
        </button>
        <button class="nfp-action-btn" @click="deselectAll">{{ t('report.invertSelect', '取消') }}</button>
        <button class="nfp-action-btn" @click="invert">{{ t('report.invert', '反选') }}</button>
        <span class="nfp-count">{{ props.hiddenIds.size }}/{{ props.nodes.length }} {{ t('report.hidden', '隐藏') }}</span>
      </div>
      <div class="nfp-list">
        <label
          v-for="n in filtered"
          :key="n.id"
          class="nfp-item"
          :class="{ hidden: isHidden(n.id) }"
        >
          <input
            type="checkbox"
            :checked="!isHidden(n.id)"
            @change="toggle(n.id)"
          />
          <span class="nfp-label">{{ n.label.length > 20 ? n.label.slice(0, 20) + '\u2026' : n.label }}</span>
          <span v-if="n.nodeCount" class="nfp-count-badge">{{ n.nodeCount }}</span>
        </label>
      </div>
    </div>
  </div>
</template>

<style scoped>
.nfp-overlay { position: absolute; top: 0; right: 0; z-index: 50; }
.nfp-panel {
  width: 260px; max-height: 400px; display: flex; flex-direction: column;
  background: var(--bg-primary); border: 1px solid var(--border);
  border-radius: 0.5rem; box-shadow: 0 4px 12px rgba(0,0,0,0.3); overflow: hidden;
}
.nfp-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 0.4rem 0.6rem; background: var(--bg-secondary);
  border-bottom: 1px solid var(--border); flex-shrink: 0;
}
.nfp-title { font-size: 0.8rem; font-weight: 600; color: var(--text-primary); }
.nfp-close {
  display: flex; align-items: center; padding: 0.1rem;
  background: none; border: none; color: var(--text-muted); cursor: pointer;
  border-radius: 0.25rem;
}
.nfp-close:hover { color: var(--text-primary); background: var(--bg-tertiary); }

.nfp-search { padding: 0.35rem 0.5rem; flex-shrink: 0; }
.nfp-search-input {
  width: 100%; padding: 0.2rem 0.4rem; font-size: 0.7rem; box-sizing: border-box;
  background: var(--bg-secondary); border: 1px solid var(--border);
  border-radius: 0.25rem; color: var(--text-primary); outline: none;
}
.nfp-search-input:focus { border-color: var(--accent); }

.nfp-actions {
  display: flex; align-items: center; gap: 0.35rem;
  padding: 0.25rem 0.5rem; border-bottom: 1px solid var(--border); flex-shrink: 0; flex-wrap: wrap;
}
.nfp-action-btn {
  display: flex; align-items: center; gap: 0.15rem;
  padding: 0.1rem 0.4rem; font-size: 0.65rem; color: var(--text-muted);
  background: var(--bg-secondary); border: 1px solid var(--border);
  border-radius: 0.25rem; cursor: pointer; transition: all 0.15s;
}
.nfp-action-btn:hover { color: var(--text-primary); border-color: var(--accent); }
.nfp-count { font-size: 0.65rem; color: var(--text-muted); margin-left: auto; }

.nfp-list { flex: 1; overflow-y: auto; padding: 0.25rem 0; }
.nfp-item {
  display: flex; align-items: center; gap: 0.35rem;
  padding: 0.15rem 0.5rem; cursor: pointer; transition: background 0.1s;
}
.nfp-item:hover { background: var(--bg-secondary); }
.nfp-item.hidden { opacity: 0.45; }
.nfp-item input[type="checkbox"] { width: 12px; height: 12px; margin: 0; cursor: pointer; accent-color: var(--accent, #7c3aed); }
.nfp-label { font-size: 0.7rem; color: var(--text-primary); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.nfp-count-badge { font-size: 0.6rem; color: var(--text-muted); font-family: var(--font-mono); background: var(--bg-tertiary); border-radius: 0.2rem; padding: 0.02rem 0.25rem; flex-shrink: 0; }
</style>
