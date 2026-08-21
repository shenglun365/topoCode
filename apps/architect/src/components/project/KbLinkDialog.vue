<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { BookOpenIcon, XMarkIcon } from '@heroicons/vue/24/outline'
import type { KbProject } from '@/types'
import { useArchProjectStore } from '@/stores/project-store'

const props = defineProps<{ matchResult?: unknown }>()
const emit = defineEmits<{ close: [] }>()

const { t } = useI18n()
const project = useArchProjectStore()

const error = ref('')
const linkingId = ref<string | null>(null)
const selectedId = ref<string | null>(null)

const selectable = (p: KbProject) => p.gitLinked && p.hasBaseline

/** match 接口已返回结构(local/remote 数组)；容错：非数组视为未返回。 */
const hasResult = computed(() => {
  const r = props.matchResult as { local?: unknown; remote?: unknown } | null | undefined
  return !!r && (Array.isArray(r.local) || Array.isArray(r.remote))
})

/** 本地仓库匹配组(已过滤)。 */
const localList = computed<KbProject[]>(() =>
  ((props.matchResult as { local?: KbProject[] } | null | undefined)?.local || []).filter(selectable),
)
/** 远程仓库匹配组(已过滤)。 */
const remoteList = computed<KbProject[]>(() =>
  ((props.matchResult as { remote?: KbProject[] } | null | undefined)?.remote || []).filter(selectable),
)

/** 当前选中的候选(本地/远程两组中的一项)。 */
const selected = computed<KbProject | null>(() => {
  const all = [...localList.value, ...remoteList.value]
  return all.find((p) => p.id === selectedId.value) || null
})

function readError(e: unknown): string {
  return e instanceof Error && e.message ? e.message : t('overview.noProject.bindFailed')
}

function confirm() {
  if (selected.value) {
    linkingId.value = selected.value.id
    project.linkKb(selected.value.id)
      .then(() => emit('close'))
      .catch((e: unknown) => { error.value = readError(e) })
      .finally(() => { linkingId.value = null })
  }
}
</script>

<template>
  <div
    class="fixed inset-0 z-50 flex items-center justify-center bg-ctp-base/70 backdrop-blur-sm"
    @click.self="emit('close')"
  >
    <div class="panel w-full max-w-lg p-5">
      <div class="flex items-center justify-between mb-1">
        <div class="flex items-center gap-2">
          <BookOpenIcon class="w-5 h-5 text-ctp-blue" />
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
        v-if="error"
        class="flex items-center gap-2 text-xs text-ctp-red border border-ctp-red/30 bg-ctp-red/5 rounded-md px-3 py-2 mb-3"
      >
        <span class="flex-1">{{ error }}</span>
      </div>

      <template v-if="hasResult">
        <!-- 本地仓库查找组 -->
        <div class="mb-4">
          <div class="flex items-center justify-between mb-1.5">
            <span class="text-xs font-medium text-ctp-subtext1 flex items-center gap-1.5">
              {{ t('overview.matchLocalTitle') }}
              <span class="chip bg-ctp-surface0 text-ctp-overlay1">{{ localList.length }}</span>
            </span>
            <span
              v-if="!localList.length"
              class="text-[11px] text-ctp-overlay1"
            >{{ t('overview.matchLocalNone') }}</span>
          </div>
          <ul
            v-if="localList.length"
            class="space-y-1.5 max-h-44 overflow-y-auto"
          >
            <li
              v-for="p in localList"
              :key="p.id"
              class="flex items-center gap-2.5 border rounded-lg px-2.5 py-2 cursor-pointer transition-colors"
              :class="selectedId === p.id ? 'border-ctp-blue/60 bg-ctp-blue/5' : 'border-ctp-surface0 hover:bg-ctp-surface0/50'"
              @click="selectedId = p.id"
            >
              <input
                type="radio"
                name="kb-match"
                :checked="selectedId === p.id"
                class="accent-ctp-blue shrink-0"
                @change="selectedId = p.id"
              />
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
            </li>
          </ul>
        </div>

        <!-- 远程仓库查找组 -->
        <div class="mb-2">
          <div class="flex items-center justify-between mb-1.5">
            <span class="text-xs font-medium text-ctp-subtext1 flex items-center gap-1.5">
              {{ t('overview.matchRemoteTitle') }}
              <span class="chip bg-ctp-surface0 text-ctp-overlay1">{{ remoteList.length }}</span>
            </span>
            <span
              v-if="!remoteList.length"
              class="text-[11px] text-ctp-overlay1"
            >{{ t('overview.matchRemoteNone') }}</span>
          </div>
          <ul
            v-if="remoteList.length"
            class="space-y-1.5 max-h-44 overflow-y-auto"
          >
            <li
              v-for="p in remoteList"
              :key="p.id"
              class="flex items-center gap-2.5 border rounded-lg px-2.5 py-2 cursor-pointer transition-colors"
              :class="selectedId === p.id ? 'border-ctp-blue/60 bg-ctp-blue/5' : 'border-ctp-surface0 hover:bg-ctp-surface0/50'"
              @click="selectedId = p.id"
            >
              <input
                type="radio"
                name="kb-match"
                :checked="selectedId === p.id"
                class="accent-ctp-blue shrink-0"
                @change="selectedId = p.id"
              />
              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-2">
                  <span class="text-sm font-medium text-ctp-text truncate">{{ p.name }}</span>
                  <span
                    v-if="p.currentVersionId"
                    class="chip bg-ctp-mauve/15 text-ctp-mauve shrink-0"
                  >{{ t('overview.noProject.baseline') }} {{ p.currentVersionId }}</span>
                </div>
                <p class="text-[11px] text-ctp-overlay1 truncate font-mono mt-0.5">
                  {{ p.remoteUrl || p.rootPath }}
                </p>
              </div>
            </li>
          </ul>
        </div>
      </template>

      <div class="flex justify-end gap-2 mt-4">
        <button
          class="btn btn-ghost text-xs"
          @click="emit('close')"
        >
          {{ t('common.cancel') }}
        </button>
        <button
          class="btn btn-blue text-xs"
          :disabled="!selected || linkingId !== null"
          @click="confirm()"
        >
          {{ linkingId !== null ? t('common.loading') : t('common.confirm') }}
        </button>
      </div>
    </div>
  </div>
</template>