<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import AppTopbar from '@/components/layout/AppTopbar.vue'
import AppSidebar from '@/components/layout/AppSidebar.vue'
import StatusBar from '@/components/layout/StatusBar.vue'
import WorkflowStepper from '@/components/layout/WorkflowStepper.vue'
import { useArchProjectStore } from '@/stores/project-store'
import { useArchRequirementStore } from '@/stores/requirement-store'
import { useArchArchitectureStore } from '@/stores/architecture-store'
import { useArchTaskStore } from '@/stores/task-store'

const route = useRoute()
const project = useArchProjectStore()
const requirement = useArchRequirementStore()
const architecture = useArchArchitectureStore()
const task = useArchTaskStore()

const isWorkbench = computed(() => !!route.meta.workbench)
const showStepper = computed(() => !!route.meta.stepper)

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
  <div class="flex flex-col h-screen overflow-hidden">
    <AppTopbar />
    <div class="flex flex-1 min-h-0">
      <AppSidebar v-if="isWorkbench" />
      <main class="flex-1 min-w-0 flex flex-col bg-ctp-base">
        <template v-if="showStepper">
          <WorkflowStepper />
        </template>
        <div class="flex-1 min-h-0 overflow-auto">
          <router-view />
        </div>
      </main>
    </div>
    <StatusBar v-if="isWorkbench" />
  </div>
</template>
