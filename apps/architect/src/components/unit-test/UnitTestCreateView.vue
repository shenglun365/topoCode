<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowLeftIcon, PlayIcon } from '@heroicons/vue/24/outline'
import type { TestChannel } from '@/types'
import { useArchUnitTestStore } from '@/stores/unit-test-store'

const emit = defineEmits<{ created: []; back: [] }>()
const { t } = useI18n()
const store = useArchUnitTestStore()

const title = ref('')
const channel = ref<TestChannel>(store.defaultChannel)

async function create() {
  const s = await store.createSession({ title: title.value.trim() || t('unitTest.defaultTitle'), channel: channel.value })
  store.select(s.id)
  emit('created')
}
</script>

<template>
  <div class="h-full flex flex-col min-h-0">
    <div class="shrink-0 flex items-center gap-2 pb-3">
      <button
        class="btn btn-sm btn-ghost"
        @click="emit('back')"
      >
        <ArrowLeftIcon class="w-3.5 h-3.5" />{{ t('common.back') }}
      </button>
      <span class="text-sm font-semibold text-ctp-text">{{ t('unitTest.newSession') }}</span>
    </div>

    <div class="flex-1 min-h-0 overflow-auto">
      <div class="panel max-w-xl space-y-3">
        <div>
          <label class="text-[11px] text-ctp-overlay1">{{ t('unitTest.sessionTitle') }}</label>
          <input
            v-model="title"
            class="input mt-1"
            :placeholder="t('unitTest.sessionTitlePh')"
          >
        </div>

        <div>
          <label class="text-[11px] text-ctp-overlay1">{{ t('unitTest.channel.label') }}</label>
          <div class="mt-1.5 flex gap-1.5">
            <button
              v-for="c in (['agent', 'cli'] as const)"
              :key="c"
              class="flex-1 border rounded-lg p-3 text-left transition-colors"
              :class="channel === c ? 'border-ctp-blue ring-1 ring-ctp-blue/30 bg-ctp-blue/5' : 'border-ctp-surface1 hover:bg-ctp-surface0/50'"
              @click="channel = c"
            >
              <div class="text-sm font-medium text-ctp-text">{{ t(`unitTest.channel.${c}`) }}</div>
              <div class="text-[11px] text-ctp-overlay1 mt-0.5">{{ t(`unitTest.channel.${c}Desc`) }}</div>
            </button>
          </div>
        </div>

        <p class="text-[11px] text-ctp-overlay1">{{ t('unitTest.newSessionHint') }}</p>

        <div class="flex justify-end pt-2">
          <button
            class="btn btn-primary"
            :disabled="!title.trim()"
            @click="create"
          >
            <PlayIcon class="w-4 h-4" />{{ t('unitTest.createGo') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>