<script setup lang="ts">
import { onMounted } from 'vue'
import { useArchProjectStore } from '@/stores/project-store'
import { useArchRequirementStore } from '@/stores/requirement-store'
import { useArchArchitectureStore } from '@/stores/architecture-store'
import { useArchTaskStore } from '@/stores/task-store'
import GuidePanel from '@/components/project/GuidePanel.vue'

const project = useArchProjectStore()
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
  <GuidePanel />
</template>
