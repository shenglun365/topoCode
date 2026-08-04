<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { CommandLineIcon, LanguageIcon } from '@heroicons/vue/24/outline'
import StarLogoMark from '@web/components/StarLogoMark.vue'
import { useArchProjectStore } from '@/stores/project-store'
import { useArchSettingsStore } from '@/stores/settings-store'
import type { Locale } from '@/types'

const router = useRouter()
const { t, locale } = useI18n()
const project = useArchProjectStore()
const settings = useArchSettingsStore()

function toggleLocale() {
  const next: Locale = locale.value === 'zh-CN' ? 'en-US' : 'zh-CN'
  settings.setLocale(next)
}

function goOverview() {
  router.push('/overview')
}
</script>

<template>
  <header class="h-12 shrink-0 flex items-center gap-3 px-4 bg-ctp-mantle border-b border-ctp-surface0">
    <button
      class="flex items-center gap-2 group"
      @click="goOverview"
    >
      <StarLogoMark :size="24" :clickable="false" />
      <div class="text-left leading-tight">
        <div class="text-sm font-semibold text-ctp-text">
          {{ t('app.name') }}
        </div>
        <div class="text-[10px] text-ctp-subtext0 hidden md:block">
          {{ t('app.tagline') }}
        </div>
      </div>
    </button>

    <div
      v-if="project.project"
      class="flex items-center gap-2 ml-3 px-3 py-1 rounded-md bg-ctp-surface0/60 min-w-0"
    >
      <span class="text-sm text-ctp-text shrink-0">{{ project.project.name }}</span>
      <span
        class="hidden lg:inline-flex items-center gap-1 text-xs text-ctp-subtext1 font-mono truncate max-w-[280px]"
        :title="project.project.rootPath"
      >
        <CommandLineIcon class="w-3 h-3 shrink-0" />{{ project.project.rootPath }}
      </span>
    </div>

    <div class="flex-1" />

    <button
      class="btn btn-ghost"
      :title="locale === 'zh-CN' ? 'English' : '中文'"
      @click="toggleLocale"
    >
      <LanguageIcon class="w-4 h-4" />
      <span class="text-xs">{{ locale === 'zh-CN' ? '中' : 'EN' }}</span>
    </button>
  </header>
</template>
