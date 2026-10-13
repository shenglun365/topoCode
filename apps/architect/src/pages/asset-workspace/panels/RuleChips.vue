<template>
  <div class="relative flex shrink-0 items-center gap-1">
    <!-- 已挂规约 chips: hover 全文 / 点击编辑 / × 卸载 -->
    <span
      v-for="r in attached"
      :key="r.ruleId"
      class="chip group inline-flex max-w-[14rem] cursor-pointer items-center gap-1 !text-[9px] bg-ctp-yellow/15 text-ctp-yellow hover:bg-ctp-yellow/25"
      :title="r.content"
      @click.stop="emit('locateRule', r.ruleId)"
    >
      <span class="truncate">{{ r.title }}</span>
      <button
        class="text-ctp-overlay0 hover:text-ctp-red"
        :title="t('guard.detachHint')"
        @click.stop="detachRule(r.ruleId)"
      >×</button>
    </span>
    <!-- 挂规约: 下拉多选(已挂置灰) + 新建入口 -->
    <button
      ref="btnRef"
      class="inline-flex items-center rounded p-0.5 text-ctp-overlay0 hover:text-ctp-teal hover:bg-ctp-surface0"
      :title="t('guard.attachHint')"
      @click.stop="toggle"
    >
      <PlusCircleIcon class="h-3.5 w-3.5" />
    </button>
    <Teleport to="body">
      <div
        v-if="open"
        class="fixed inset-0 z-40"
        @click="open = false"
      />
      <div
        v-if="open"
        class="z-50 w-72 rounded-lg border border-ctp-surface1 bg-ctp-mantle p-1.5 shadow-xl"
        :style="pos"
      >
        <p
          v-if="!coreRules.rules.value.length"
          class="px-2 py-2 text-center text-[11px] text-ctp-overlay0"
        >{{ t('guard.noRules') }}</p>
        <label
          v-for="r in coreRules.rules.value"
          :key="r.id"
          class="flex cursor-pointer items-center gap-1.5 rounded px-1.5 py-1 text-[11px] hover:bg-ctp-surface0"
          :title="r.content"
        >
          <input
            type="checkbox"
            class="accent-ctp-yellow"
            :checked="attachedIds.has(r.id)"
            @change="toggleRule(r)"
          >
          <span class="min-w-0 flex-1 truncate text-ctp-text">{{ r.title }}</span>
          <span
            v-if="r.source === 'skill'"
            class="chip shrink-0 !text-[8px] bg-ctp-mauve/15 text-ctp-mauve"
          >⚡</span>
        </label>
        <div class="mt-1 border-t border-ctp-surface0 pt-1">
          <button
            class="w-full rounded px-1.5 py-1 text-left text-[11px] text-ctp-teal hover:bg-ctp-surface0"
            @click.stop="emit('newRule'); open = false"
          >{{ t('guard.newRuleInline') }}</button>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
/**
 * 挂载规约 chips(2610 重构): 目标行右侧——已挂清单 + 规约库多选挂载。
 * 挂载即核心; 卸载/挂载即时生效(守护 effective 单源)。
 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { PlusCircleIcon } from '@heroicons/vue/24/solid'
import type { useCoreRules } from '../useCoreRules'

const props = defineProps<{
  targetType: string
  targetId: string
  title: string
  coreRules: ReturnType<typeof useCoreRules>
}>()
const emit = defineEmits<{ locateRule: [ruleId: string]; newRule: [] }>()
const { t } = useI18n()

const open = ref(false)
const pos = ref<Record<string, string>>({})
const btnRef = ref<HTMLElement | null>(null)

const attached = computed(() =>
  props.coreRules.effectiveOf(props.targetType, props.targetId)?.rules ?? [])
const attachedIds = computed(() => new Set(attached.value.map((r) => r.ruleId)))

async function toggle() {
  open.value = !open.value
  if (open.value) {
    // 先按按钮位置定位(浮层 teleport 到 body, 无定位则游离文档流末尾)
    const rect = btnRef.value?.getBoundingClientRect()
    if (rect) {
      pos.value = {
        position: 'fixed',
        top: `${Math.min(rect.bottom + 4, Math.max(8, window.innerHeight - 280))}px`,
        left: `${Math.max(8, Math.min(rect.right - 288, window.innerWidth - 296))}px`,
      }
    }
    if (!props.coreRules.loaded.value) await props.coreRules.refresh()
  }
}

async function toggleRule(r: { id: string }) {
  if (attachedIds.value.has(r.id)) {
    await props.coreRules.detach(props.targetType, props.targetId, r.id)
  } else {
    await props.coreRules.attach(props.targetType, props.targetId, r.id, props.title)
  }
}

async function detachRule(ruleId: string) {
  await props.coreRules.detach(props.targetType, props.targetId, ruleId)
}
</script>
