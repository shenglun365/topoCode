<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import PageHeader from '@/components/PageHeader.vue'
import ImpactOverview from '@/components/baseline/ImpactOverview.vue'
import BaselineEvolutionPanel from '@/components/baseline/BaselineEvolutionPanel.vue'
import ImpactAnalysisView from '@/components/assets/ImpactAnalysisView.vue'
import MergeBaselineWorkspace from '@/components/assets/MergeBaselineWorkspace.vue'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()

// S4 菜单重构：基线管理单入口，页内双视图（基线=merge / 概览=impact）
// P3 瘦身裁决：影响分析视图改为「宏观概览」（统计+组件汇总图+版本历史），
// 图谱细节(组件/文件/符号粒度+演化时间轴)统一在资产地图 → 图谱。
const view = computed(() => (['impact', 'evolution'].includes(String(route.query.view)) ? String(route.query.view) : 'merge'))

function switchView(v: 'merge' | 'impact' | 'evolution') {
  router.replace({ query: { ...route.query, view: v } })
}
</script>

<template>
  <div class="p-5 space-y-4">
    <PageHeader
      :title="t('archMap.title')"
      :desc="t('archMap.desc')"
    />

    <!-- 视图切换：基线管理 / 宏观概览（菜单单入口，页内切换） -->
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
      <button
        class="btn btn-sm"
        :class="view === 'evolution' ? 'btn-blue' : 'btn-ghost'"
        @click="switchView('evolution')"
      >
        {{ t('nav.tree.evolution') }}
      </button>
    </div>

    <!-- 宏观概览: 变更统计 + 组件汇总图 + 版本历史 + 语义资产影响分析 -->
    <template v-if="view === 'impact'">
      <ImpactOverview />
      <ImpactAnalysisView />
    </template>

    <!-- 架构变更视图(需求 7)：基线开始 + 指定分支/head step 帧演化 -->
    <BaselineEvolutionPanel v-else-if="view === 'evolution'" />

    <!-- 合并基线视图 -->
    <MergeBaselineWorkspace v-else />
  </div>
</template>
