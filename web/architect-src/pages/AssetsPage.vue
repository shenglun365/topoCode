<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import ModuleWorkspace from '@/components/assets/ModuleWorkspace.vue'
import SpecWorkspace from '@/components/assets/SpecWorkspace.vue'
import SemanticAssetsView from '@/components/assets/SemanticAssetsView.vue'

const { t } = useI18n()
const route = useRoute()

type AssetTab = 'modules' | 'spec' | 'semantic'

const tab = ref<AssetTab>(route.query.tab === 'spec' ? 'spec' : route.query.tab === 'semantic' ? 'semantic' : 'modules')

watch(
  () => route.query.tab,
  (q) => {
    tab.value = q === 'spec' ? 'spec' : q === 'semantic' ? 'semantic' : 'modules'
  },
)

const tabs = computed(() => [
  { id: 'modules' as const, label: t('assetsPage.tab.modules') },
  { id: 'spec' as const, label: t('assetsPage.tab.spec') },
  { id: 'semantic' as const, label: t('assetsPage.tab.semantic') },
])
</script>

<template>
  <div class="p-5 space-y-3">
    <div class="flex items-center gap-2">
      <button
        v-for="tb in tabs"
        :key="tb.id"
        class="btn btn-sm"
        :class="tab === tb.id ? 'btn-blue' : 'btn-ghost'"
        @click="tab = tb.id"
      >
        {{ tb.label }}
      </button>
    </div>
    <ModuleWorkspace v-if="tab === 'modules'" />
    <SpecWorkspace v-else-if="tab === 'spec'" />
    <SemanticAssetsView v-else-if="tab === 'semantic'" />
  </div>
</template>
