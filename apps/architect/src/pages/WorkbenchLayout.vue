<script setup lang="ts">
import { onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useArchProjectStore } from '@/stores/project-store'
import { useArchRequirementStore } from '@/stores/requirement-store'
import { useArchArchitectureStore } from '@/stores/architecture-store'
import { useArchTaskStore } from '@/stores/task-store'
import GuidePanel from '@/components/project/GuidePanel.vue'
import ConversationDock from '@/components/chat/ConversationDock.vue'

const route = useRoute()
const project = useArchProjectStore()
/** 资产地图页自带 inline 停靠会话栏 → 该页不渲染全局悬浮形态。 */
const showFloatingDock = () => route.path !== '/workbench/asset-mgmt'
const requirement = useArchRequirementStore()
const architecture = useArchArchitectureStore()
const task = useArchTaskStore()

onMounted(async () => {
  await project.load()
  if (project.project) {
    for (const load of [requirement.load, architecture.loadFromSnapshot, task.load]) {
      await load().catch((err) => console.error('[arch] 初始化加载失败', err))
    }
  }
})
</script>

<template>
  <router-view />
  <ConversationDock v-if="showFloatingDock()" />
  <GuidePanel />
</template>
