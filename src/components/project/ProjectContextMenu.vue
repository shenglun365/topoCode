<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { PencilIcon, TrashIcon, MagnifyingGlassIcon, ArchiveBoxXMarkIcon } from '@heroicons/vue/24/outline'
import { StarIcon } from '@heroicons/vue/24/solid'

const { t } = useI18n()

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
  width: 190px;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 8px;
  box-shadow: 0 4px 16px rgba(0,0,0,0.3);
  padding: 6px;
  font-size: 12px;
}
.context-menu-item {
  display: flex; align-items: center; gap: 8px;
  padding: 7px 10px; border-radius: 6px; cursor: pointer;
  color: var(--text-primary); transition: background 0.12s;
}
.context-menu-item:hover { background: var(--bg-hover); }
.context-menu-item-warning { color: var(--warning); }
.context-menu-item-danger { color: var(--error); }
.context-menu-divider { height: 1px; background: var(--border); margin: 4px 6px; }
.menu-icon-text { width: 16px; text-align: center; font-size: 14px; }
.context-menu-backdrop {
  position: fixed; inset: 0; z-index: 9998;
}
</style>
