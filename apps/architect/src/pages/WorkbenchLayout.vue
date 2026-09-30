<script setup lang="ts">
import { onMounted } from 'vue'
import { useArchProjectStore } from '@/stores/project-store'
import { useArchRequirementStore } from '@/stores/requirement-store'
import { useArchArchitectureStore } from '@/stores/architecture-store'
import GuidePanel from '@/components/project/GuidePanel.vue'
import ChangeWatch from '@/components/common/ChangeWatch.vue'

const project = useArchProjectStore()
const requirement = useArchRequirementStore()
const architecture = useArchArchitectureStore()

onMounted(async () => {
  await project.load()
  if (project.project) {
    for (const load of [requirement.load, architecture.loadFromSnapshot]) {
      await load().catch((err) => console.error('[arch] 初始化加载失败', err))
    }
  }
})
</script>

<template>
  <router-view />
  <!-- 对话栏只在 会话管理/资产管理 两页内嵌渲染(ConversationDock inline),
       其余功能大项不再显示会话框与会话气泡(悬浮 dock 已移除)。 -->
  <GuidePanel />
  <!-- 生命周期感知(批5)：代码变更轮询提示(需求 5/2-F) -->
  <ChangeWatch />
</template>
