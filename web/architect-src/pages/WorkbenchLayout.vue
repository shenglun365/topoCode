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
  if (!project.loaded) {
    await project.load()
    if (project.project) {
      await Promise.all([requirement.load(), architecture.loadFromSnapshot(), task.load()])
    }
  }
})
</script>

<template>
  <router-view />
  <GuidePanel />
</template>
