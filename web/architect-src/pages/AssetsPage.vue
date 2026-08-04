<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import ModuleWorkspace from '@/components/assets/ModuleWorkspace.vue'
import SpecWorkspace from '@/components/assets/SpecWorkspace.vue'

const route = useRoute()

const tab = ref<'modules' | 'spec'>(route.query.tab === 'spec' ? 'spec' : 'modules')

watch(
  () => route.query.tab,
  (q) => {
    tab.value = q === 'spec' ? 'spec' : 'modules'
  },
)
</script>

<template>
  <div class="p-5">
    <ModuleWorkspace v-if="tab === 'modules'" />
    <SpecWorkspace v-else-if="tab === 'spec'" />
  </div>
</template>
