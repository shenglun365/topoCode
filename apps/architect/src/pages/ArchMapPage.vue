<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import PageHeader from '@/components/PageHeader.vue'
import ChangeSummaryBar from '@/components/assets/ChangeSummaryBar.vue'
import ChangeMapView from '@/components/assets/ChangeMapView.vue'
import MergeBaselineWorkspace from '@/components/assets/MergeBaselineWorkspace.vue'
import { useArchProjectStore } from '@/stores/project-store'
import { useArchStagingStore } from '@/stores/staging-store'
import { computeArchChange } from '@/services/arch-change-service'
import type { ArchChangeReport } from '@/services/arch-change-service'

const { t } = useI18n()
const route = useRoute()
const project = useArchProjectStore()
const staging = useArchStagingStore()
staging.load()

const view = computed(() => (route.query.view === 'merge' ? 'merge' : 'impact'))

const report = ref<ArchChangeReport | null>(null)
watch(
  () => [project.snapshots, view.value, staging.model?.affectedComponents] as const,
  async () => {
    if (view.value !== 'impact') return
    report.value = await computeArchChange('snap-v0', 'snap-v1', staging.model?.affectedComponents ?? [])
  },
  { immediate: true },
)
</script>

<template>
  <div class="p-5 space-y-4">
    <PageHeader
      :title="t('archMap.title')"
      :desc="t('archMap.desc')"
    />

    <!-- 架构变更视图: 累计变更影响概要 + 详细变更地图 -->
    <template v-if="view === 'impact'">
      <ChangeSummaryBar :report="report" />
      <ChangeMapView :report="report" />
    </template>

    <!-- 合并基线视图 -->
    <MergeBaselineWorkspace v-else />
  </div>
</template>
