<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import PageHeader from '@/components/PageHeader.vue'
import ChangeSummaryBar from '@/components/assets/ChangeSummaryBar.vue'
import ChangeMapView from '@/components/assets/ChangeMapView.vue'
import ImpactAnalysisView from '@/components/assets/ImpactAnalysisView.vue'
import MergeBaselineWorkspace from '@/components/assets/MergeBaselineWorkspace.vue'
import { useArchProjectStore } from '@/stores/project-store'
import { useArchStagingStore } from '@/stores/staging-store'
import { computeArchChange } from '@/services/arch-change-service'
import type { ArchChangeReport } from '@/services/arch-change-service'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const project = useArchProjectStore()
const staging = useArchStagingStore()
staging.load()

// S4 菜单重构：基线管理单入口，页内双视图（基线=merge / 影响=impact）
const view = computed(() => (route.query.view === 'impact' ? 'impact' : 'merge'))

function switchView(v: 'merge' | 'impact') {
  router.replace({ query: { ...route.query, view: v } })
}

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

    <!-- 视图切换：基线管理 / 影响分析（菜单单入口，页内切换） -->
    <div class="flex items-center gap-1.5">
      <button
        class="btn btn-sm"
        :class="view === 'merge' ? 'btn-blue' : 'btn-ghost'"
        @click="switchView('merge')"
      >
        {{ t('nav.tree.mergeBaseline') }}
      </button>
      <button
        class="btn btn-sm"
        :class="view === 'impact' ? 'btn-blue' : 'btn-ghost'"
        @click="switchView('impact')"
      >
        {{ t('nav.tree.impact') }}
      </button>
    </div>

    <!-- 架构变更视图: 累计变更影响概要 + 详细变更地图 + A6 整体基线变更分析 -->
    <template v-if="view === 'impact'">
      <ChangeSummaryBar :report="report" />
      <ChangeMapView :report="report" />
      <ImpactAnalysisView />
    </template>

    <!-- 合并基线视图 -->
    <MergeBaselineWorkspace v-else />
  </div>
</template>
