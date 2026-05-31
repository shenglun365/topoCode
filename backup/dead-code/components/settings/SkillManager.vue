<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useSettingsStore } from '@/stores/settings'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('ST-003')
const { t } = useI18n()
const settingsStore = useSettingsStore()

async function toggleSkill(id: string, enabled: boolean) {
  await settingsStore.updateSkill({ id, enabled })
}
</script>

<template>
  <div class="skill-manager">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <div style="margin-bottom:16px;">
      <h2 style="font-size:16px; font-weight:600; margin-bottom:2px;">
        {{ t('settings.skillManagement') }}
      </h2>
      <p
        class="text-muted"
        style="font-size:12px;"
      >
        {{ t('settings.skillDesc') }}
      </p>
    </div>

    <!-- SKILL 列表 -->
    <div
      v-for="skill in settingsStore.skills"
      :key="skill.id"
      class="card"
      style="padding:14px; margin-bottom:10px;"
    >
      <div style="display:flex; justify-content:space-between; align-items:flex-start;">
        <div style="flex:1;">
          <div style="font-size:13px; font-weight:500; margin-bottom:4px;">
            {{ skill.name }}
          </div>
          <div
            class="text-muted"
            style="font-size:11px;"
          >
            {{ skill.description }}
          </div>
        </div>
        <label
          class="toggle"
          style="flex-shrink:0; margin-left:12px;"
        >
          <input
            type="checkbox"
            :checked="skill.enabled"
            @change="toggleSkill(skill.id, !skill.enabled)"
          >
          <span class="toggle-slider" />
        </label>
      </div>
    </div>
  </div>
</template>

<style scoped>
.skill-manager {
  max-width: 600px;
}
</style>
