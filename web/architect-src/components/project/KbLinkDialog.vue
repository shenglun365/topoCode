<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowPathIcon, CodeBracketIcon, XMarkIcon } from '@heroicons/vue/24/outline'
import type { KbProject } from '@/types'
import { projectService } from '@/services/project-service'
import { useArchProjectStore } from '@/stores/project-store'

const emit = defineEmits<{ close: [] }>()

const { t } = useI18n()
const project = useArchProjectStore()

const kbList = ref<KbProject[]>([])
const loading = ref(false)
const error = ref('')
const linkingId = ref<string | null>(null)

const selectable = (p: KbProject) => p.gitLinked && p.hasBaseline

function readError(e: unknown): string {
  return e instanceof Error && e.message ? e.message : t('overview.noProject.bindFailed')
}

async function loadKb() {
  loading.value = true
  error.value = ''
  try {
    kbList.value = await projectService.listKbProjects()
  } catch {
    error.value = t('overview.noProject.kbError')
  } finally {
    loading.value = false
  }
}

async function link(p: KbProject) {
  linkingId.value = p.id
  try {
    await project.linkKb(p.id)
    emit('close')
  } catch (e) {
    error.value = readError(e)
  } finally {
    linkingId.value = null
  }
}

onMounted(loadKb)
</script>

<template>
  <div
    class="fixed inset-0 z-50 flex items-center justify-center bg-ctp-base/70 backdrop-blur-sm"
    @click.self="emit('close')"
  >
    <div class="panel w-full max-w-lg p-5">
      <div class="flex items-center justify-between mb-1">
        <div class="flex items-center gap-2">
          <CodeBracketIcon class="w-5 h-5 text-ctp-blue" />
          <h2 class="text-base font-medium text-ctp-text">
            {{ t('overview.linkKbTitle') }}
          </h2>
        </div>
        <button
          class="text-ctp-overlay1 hover:text-ctp-text"
          @click="emit('close')"
        >
          <XMarkIcon class="w-5 h-5" />
        </button>
      </div>
      <p class="text-xs text-ctp-subtext0 mb-3">
        {{ t('overview.linkKbDesc') }}
      </p>

      <div
        v-if="loading"
        class="text-xs text-ctp-subtext0 py-4"
      >
        {{ t('app.loading') }}
      </div>

      <div
        v-else-if="error"
        class="flex items-center gap-2 text-xs text-ctp-red border border-ctp-red/30 bg-ctp-red/5 rounded-md px-3 py-2"
      >
        <span class="flex-1">{{ error }}</span>
        <button
          class="btn btn-ghost !py-1 text-xs"
          @click="loadKb"
        >
          <ArrowPathIcon class="w-3 h-3" />{{ t('common.refresh') }}
        </button>
      </div>

      <div
        v-else-if="!selectable(kbList).length"
        class="text-xs text-ctp-subtext0 py-3"
      >
        {{ t('overview.noProject.kbRouteEmpty') }}
      </div>

      <ul
        v-else
        class="space-y-2 max-h-72 overflow-y-auto"
      >
        <li
          v-for="p in selectable(kbList)"
          :key="p.id"
          class="flex items-center gap-3 border border-ctp-surface0 rounded-lg px-3 py-2"
        >
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2">
              <span class="text-sm font-medium text-ctp-text truncate">{{ p.name }}</span>
              <span
                v-if="p.currentVersionId"
                class="chip bg-ctp-mauve/15 text-ctp-mauve shrink-0"
              >{{ t('overview.noProject.baseline') }} {{ p.currentVersionId }}</span>
            </div>
            <p class="text-[11px] text-ctp-overlay1 truncate font-mono mt-0.5">
              {{ p.rootPath }}
            </p>
          </div>
          <button
            class="btn btn-blue text-xs shrink-0"
            :disabled="linkingId === p.id"
            @click="link(p)"
          >
            {{ linkingId === p.id ? t('common.loading') : t('overview.linkKb') }}
          </button>
        </li>
      </ul>

      <div class="flex justify-end mt-4">
        <button
          class="btn btn-ghost text-xs"
          @click="emit('close')"
        >
          {{ t('common.cancel') }}
        </button>
      </div>
    </div>
  </div>
</template>
