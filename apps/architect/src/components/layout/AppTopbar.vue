<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  CommandLineIcon,
  LanguageIcon,
  ChevronDownIcon,
  CheckIcon,
  ChevronUpDownIcon,
} from '@heroicons/vue/24/outline'
import StarLogoMark from '@/components/common/StarLogoMark.vue'
import { useArchProjectStore } from '@/stores/project-store'
import { useArchSettingsStore, FONT_SCALES } from '@/stores/settings-store'
import type { Locale } from '@/types'

const router = useRouter()
const { t, locale } = useI18n()
const project = useArchProjectStore()
const settings = useArchSettingsStore()

const fontMenuOpen = ref(false)

function toggleLocale() {
  const next: Locale = locale.value === 'zh-CN' ? 'en-US' : 'zh-CN'
  settings.setLocale(next)
}

function goOverview() {
  router.push('/overview')
}

function setFontScale(scale: number) {
  settings.setFontScale(scale)
  fontMenuOpen.value = false
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

    <div class="relative">
      <button
        class="btn btn-ghost"
        :title="t('app.fontScale')"
        @click="fontMenuOpen = !fontMenuOpen"
      >
        <ChevronUpDownIcon class="w-4 h-4" />
        <span class="text-xs">{{ Math.round(settings.fontScale * 100) }}%</span>
        <ChevronDownIcon class="w-3 h-3" />
      </button>

      <div
        v-if="fontMenuOpen"
        class="fixed inset-0 z-40"
        @click="fontMenuOpen = false"
        @contextmenu.prevent="fontMenuOpen = false"
      />
      <div
        v-if="fontMenuOpen"
        class="absolute right-0 top-full mt-1 z-50 w-28 rounded-md border border-ctp-surface0 bg-ctp-mantle shadow-lg py-1"
      >
        <button
          v-for="s in FONT_SCALES"
          :key="s"
          class="flex items-center justify-between w-full px-3 py-1.5 text-sm text-ctp-subtext1 hover:bg-ctp-surface0 hover:text-ctp-text"
          :class="s === settings.fontScale ? 'text-ctp-text font-medium' : ''"
          @click="setFontScale(s)"
        >
          <span>{{ Math.round(s * 100) }}%</span>
          <CheckIcon
            v-if="s === settings.fontScale"
            class="w-3.5 h-3.5 text-ctp-green"
          />
        </button>
      </div>
    </div>

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
