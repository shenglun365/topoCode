<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAppDialog } from '@/composables/useAppDialog'

const { t } = useI18n()
const { state, finish } = useAppDialog()
const inputRef = ref<HTMLInputElement | null>(null)
const confirmBtnRef = ref<HTMLButtonElement | null>(null)

watch(
  () => state.current,
  async (cur) => {
    if (!cur) return
    await nextTick()
    if (cur.kind === 'prompt') inputRef.value?.focus()
    else confirmBtnRef.value?.focus()
  },
)

function onKeydown(e: KeyboardEvent) {
  if (!state.current) return
  if (e.key === 'Enter') {
    e.preventDefault()
    ok()
  } else if (e.key === 'Escape') {
    e.preventDefault()
    cancel()
  }
}

function ok() {
  const cur = state.current
  if (!cur) return
  finish(cur.kind === 'prompt' ? state.draft : true)
}

function cancel() {
  finish(state.current?.kind === 'prompt' ? null : false)
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="state.current"
      class="fixed inset-0 z-[200] flex items-center justify-center bg-black/45 p-4"
      @keydown="onKeydown"
      @click.self="cancel()"
    >
      <div
        class="w-[24rem] max-w-full rounded-xl border border-ctp-surface0 bg-ctp-mantle p-4 shadow-2xl"
        role="dialog"
        aria-modal="true"
      >
        <p class="whitespace-pre-wrap text-sm leading-relaxed text-ctp-text">{{ state.current.message }}</p>
        <input
          v-if="state.current.kind === 'prompt'"
          ref="inputRef"
          v-model="state.draft"
          class="input mt-3 w-full text-xs"
          @keydown.enter.prevent="ok()"
        >
        <div class="mt-4 flex justify-end gap-2">
          <button class="btn btn-ghost text-xs" @click="cancel()">{{ t('common.cancel') }}</button>
          <button
            ref="confirmBtnRef"
            class="btn text-xs"
            :class="state.current.kind === 'confirm' && state.current.danger ? 'btn-red' : 'btn-blue'"
            @click="ok()"
          >{{ state.current.kind === 'alert' ? t('common.confirm')
             : (state.current.kind === 'confirm' && state.current.confirmText) || t('common.confirm') }}</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
