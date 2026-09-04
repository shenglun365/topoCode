<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { CommandLineIcon } from '@heroicons/vue/24/outline'
import StarLogoMark from '@/components/common/StarLogoMark.vue'
import { AppToolbar, ModelSettingsDropdown } from '@topo/web-core/shell'
import type { ModelSettingsProvider } from '@topo/web-core/shell'
import { useArchProjectStore } from '@/stores/project-store'
import { useArchSettingsStore } from '@/stores/settings-store'
import { apiGet, apiPut } from '@/services/api-client'
import type { ArchLlmModelsResult } from '@/types'

const router = useRouter()
const { t } = useI18n()
const project = useArchProjectStore()
const settings = useArchSettingsStore()

/** P4：architect 独立模型库 + max-tokens（输出上限，M2=B）。 */
const modelProvider: ModelSettingsProvider = {
  async listModels() {
    const data = await apiGet<ArchLlmModelsResult>('/llm/models')
    return data.models.map((m) => ({ id: m.id, name: m.name }))
  },
  async saveModel(modelId) {
    await apiPut('/llm/model', { modelId })
  },
  async saveContext(tokens) {
    await apiPut('/llm/max-tokens', { maxTokens: tokens })
  },
}

function goOverview() {
  router.push('/overview')
}

function onLocale(l: string) {
  settings.setLocale(l as 'zh-CN' | 'en-US')
}

function onFontSize(v: number) {
  settings.setFontSize(v)
}
</script>

<template>
  <AppToolbar
    app-key="architect"
    :font-size="settings.fontSize"
    :font-targets="['root']"
    :help-href="'/'"
    @update:font-size="onFontSize"
    @update:locale="onLocale"
  >
    <template #brand>
      <button class="flex items-center gap-2 group" @click="goOverview" type="button">
        <StarLogoMark :size="24" :clickable="false" />
      </button>
    </template>
    <template #title>
      <div class="text-left leading-tight">
        <div class="text-sm font-semibold text-ctp-text">
          {{ t('app.name') }}
        </div>
        <div class="text-[10px] text-ctp-subtext0 hidden md:block">
          {{ t('app.tagline') }}
        </div>
      </div>
    </template>
    <template #project>
      <div
        v-if="project.project"
        class="flex items-center gap-2 px-3 py-1 rounded-md bg-ctp-surface0/60 min-w-0"
      >
        <span class="text-sm text-ctp-text shrink-0">{{ project.project.name }}</span>
        <span
          class="hidden lg:inline-flex items-center gap-1 text-xs text-ctp-subtext1 font-mono truncate max-w-[280px]"
          :title="project.project.rootPath"
        >
          <CommandLineIcon class="w-3 h-3 shrink-0" />{{ project.project.rootPath }}
        </span>
      </div>
    </template>
    <template #tools>
      <ModelSettingsDropdown
        app-key="architect"
        :provider="modelProvider"
        :context-options="[2048, 4096, 8192, 16384, 32768]"
        :context-label="t('app.contextLimit')"
      />
    </template>
  </AppToolbar>
</template>
