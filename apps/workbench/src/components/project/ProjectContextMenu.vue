<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { PencilIcon, TrashIcon, MagnifyingGlassIcon, ArchiveBoxXMarkIcon } from '@heroicons/vue/24/outline'
import { StarIcon } from '@heroicons/vue/24/solid'
import { useComponentId } from '@topo/web-core/composables/useComponentId'

const { t } = useI18n()
const { showId, componentId } = useComponentId('PC-001')

const props = defineProps<{
  visible: boolean
  position: { x: number; y: number }
  isFavorited: boolean
  isPinned: boolean
  isSample: boolean
}>()

const emit = defineEmits<{
  close: []
  'toggle-favorite': []
  'toggle-pinned': []
  'edit-info': []
  'change-path': []
  'check-changes': []
  'clear-cache': []
  delete: []
}>()
</script>

<template>
  <span
    v-if="showId"
    class="cmp-id"
  >{{ componentId }}</span>
  <Teleport to="body">
    <div
      v-if="visible"
      class="context-menu"
      :style="{ left: position.x + 'px', top: position.y + 'px' }"
      @click.stop
      @mouseleave="emit('close')"
    >
      <div
        class="context-menu-item"
        @click="emit('toggle-favorite')"
      >
        <StarIcon :class="['w-4 h-4', isFavorited ? 'text-yellow-400' : '']" />
        <span>{{ isFavorited ? t('project.unfavorite') : t('project.favorite') }}</span>
      </div>
      <div
        class="context-menu-item"
        @click="emit('toggle-pinned')"
      >
        <span class="menu-icon-text">{{ isPinned ? '✕' : '↑' }}</span>
        <span>{{ isPinned ? t('project.unpin') : t('project.pin') }}</span>
      </div>
      <div class="context-menu-divider" />
      <div
        class="context-menu-item"
        @click="emit('edit-info')"
      >
        <PencilIcon class="w-4 h-4" />
        <span>{{ t('project.editInfo') }}</span>
      </div>
      <div
        class="context-menu-item"
        @click="emit('change-path')"
      >
        <PencilIcon class="w-4 h-4" />
        <span>{{ t('project.changePath') }}</span>
      </div>
      <div
        class="context-menu-item"
        @click="emit('check-changes')"
      >
        <MagnifyingGlassIcon class="w-4 h-4" />
        <span>{{ t('project.checkChanges') }}</span>
      </div>
      <div class="context-menu-divider" />
      <div
        v-if="!isSample"
        class="context-menu-item context-menu-item-warning"
        @click="emit('clear-cache')"
      >
        <ArchiveBoxXMarkIcon class="w-4 h-4" />
        <span>{{ t('project.clearCache') }}</span>
      </div>
      <div class="context-menu-divider" />
      <div
        v-if="!isSample"
        class="context-menu-item context-menu-item-danger"
        @click="emit('delete')"
      >
        <TrashIcon class="w-4 h-4" />
        <span>{{ t('common.delete') }}</span>
      </div>
    </div>
  </Teleport>

  <div
    v-if="visible"
    class="context-menu-backdrop"
    @click="emit('close')"
  />
</template>

<style scoped>
.context-menu {
  position: fixed;
  z-index: 9999;
  width: calc(190px * var(--ui-scale, 1));
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: calc(8px * var(--ui-scale, 1));
  box-shadow: 0 4px 16px rgba(0,0,0,0.3);
  padding: calc(6px * var(--ui-scale, 1));
  font-size: calc(12px * var(--ui-scale, 1));
}
.context-menu-item {
  display: flex; align-items: center; gap: calc(8px * var(--ui-scale, 1));
  padding: calc(7px * var(--ui-scale, 1)) calc(10px * var(--ui-scale, 1)); border-radius: calc(6px * var(--ui-scale, 1)); cursor: pointer;
  color: var(--text-primary); transition: background 0.12s;
}
.context-menu-item:hover { background: var(--bg-hover); }
.context-menu-item-warning { color: var(--warning); }
.context-menu-item-danger { color: var(--error); }
.context-menu-divider { height: 1px; background: var(--border); margin: calc(4px * var(--ui-scale, 1)) calc(6px * var(--ui-scale, 1)); }
.menu-icon-text { width: calc(16px * var(--ui-scale, 1)); text-align: center; font-size: calc(14px * var(--ui-scale, 1)); }
.context-menu-backdrop {
  position: fixed; inset: 0; z-index: 9998;
}
</style>
