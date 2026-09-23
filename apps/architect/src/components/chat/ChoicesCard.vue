<script setup lang="ts">
import { computed, reactive } from 'vue'
import { assembleReply, groupKey, requiredMissing } from '@/services/choices-reply'
import type { ChoiceGroup } from '@/services/choices-reply'

/**
 * 结构化问询卡(cv-247) — 卡片词汇表 choices 的前端通用渲染器。
 *
 * 交互模型(用户裁决): 每题三态——点选选项 / 自定义输入(恒驻, 输入即覆盖
 * 点选) / 跳过(显式表达「弃权也是答案」); 开放题组(无 options)纯输入;
 * 全局补充恒在; 模板可整体弃用——对话输入区自由回复(宿主发送后本卡置已答)。
 * 回复组装=普通文本消息(与手打等价), 走既有发送通道, 零新协议。
 */
const props = defineProps<{
  payload: { title?: string; groups?: ChoiceGroup[]; note?: string }
  disabled?: boolean
}>()
const emit = defineEmits<{ (e: 'reply', text: string): void }>()

const groups = computed(() => props.payload?.groups ?? [])
const gid = (g: ChoiceGroup, i: number) => groupKey(g, i)

// 三态互斥: selections(点选) / customs(自定义) / skipped(跳过)
const selections = reactive<Record<string, string>>({})
const customs = reactive<Record<string, string>>({})
const skipped = reactive<Record<string, boolean>>({})
const extra = reactive({ note: '' })
const answered = reactive({ done: false })

function pick(gidv: string, optId: string) {
  if (props.disabled || answered.done || skipped[gidv]) return
  selections[gidv] = selections[gidv] === optId ? '' : optId
  customs[gidv] = ''
  skipped[gidv] = false
}
function onCustom(gidv: string) {
  if (customs[gidv]?.trim()) {
    selections[gidv] = ''
    skipped[gidv] = false
  }
}
function toggleSkip(gidv: string) {
  if (props.disabled || answered.done) return
  skipped[gidv] = !skipped[gidv]
  if (skipped[gidv]) {
    selections[gidv] = ''
    customs[gidv] = ''
  }
}

const missingCount = computed(() => requiredMissing(groups.value, {
  selections, customs, skipped, note: extra.note }))

const replyText = computed(() => assembleReply(groups.value, {
  selections, customs, skipped, note: extra.note }))

function sendReply() {
  if (props.disabled || answered.done || !replyText.value) return
  answered.done = true
  emit('reply', replyText.value)
}

/** 宿主通知: 本卡经其它通道(输入区自由回复)已被消化 → 置已答态。 */
function markAnswered() {
  answered.done = true
}
defineExpose({ markAnswered })
</script>

<template>
  <div
    class="mt-1 rounded-lg border bg-ctp-mantle/60 px-3 py-2.5 text-[12px]"
    :class="answered.done ? 'border-ctp-surface0 opacity-75' : 'border-ctp-surface1'"
  >
    <div class="mb-1.5 flex items-center gap-2">
      <span class="font-semibold text-ctp-text">{{ payload.title || '请确认以下问题' }}</span>
      <span
        v-if="answered.done"
        class="chip !text-[9px] bg-ctp-green/15 text-ctp-green"
      >已回复</span>
    </div>

    <div
      v-for="(g, i) in groups"
      :key="gid(g, i)"
      class="mb-2 rounded-md bg-ctp-base/40 px-2.5 py-2"
      :class="skipped[gid(g, i)] ? 'opacity-50' : ''"
    >
      <div class="mb-1.5 flex items-start gap-2">
        <span class="flex-1 leading-relaxed text-ctp-subtext1">
          <span class="text-ctp-overlay1">{{ i + 1 }}.</span>
          <span class="font-medium text-ctp-text">{{ g.label || '' }}</span>
          <span v-if="g.label && g.question"> —— </span>{{ g.question || '' }}
          <span
            v-if="g.required"
            class="ml-1 text-[10px] text-ctp-peach"
            title="建议回答"
          >*</span>
        </span>
        <button
          class="chip !text-[9px] shrink-0 transition-colors"
          :class="skipped[gid(g, i)]
            ? 'bg-ctp-yellow/20 text-ctp-yellow'
            : 'bg-ctp-surface0/60 text-ctp-overlay0 hover:text-ctp-subtext1'"
          :disabled="disabled || answered.done"
          data-test="choices-skip"
          @click="toggleSkip(gid(g, i))"
        >{{ skipped[gid(g, i)] ? '已跳过' : '跳过' }}</button>
      </div>

      <div v-if="(g.options ?? []).length" class="mb-1.5 space-y-1">
        <button
          v-for="o in g.options"
          :key="o.id ?? o.label"
          class="flex w-full items-center gap-2 rounded border px-2 py-1 text-left transition-colors"
          :class="selections[gid(g, i)] === (o.id ?? o.label)
            ? 'border-ctp-blue/60 bg-ctp-blue/10 text-ctp-text'
            : 'border-ctp-surface0 text-ctp-subtext1 hover:border-ctp-overlay0'"
          :disabled="disabled || answered.done || skipped[gid(g, i)]"
          data-test="choices-option"
          @click="pick(gid(g, i), o.id ?? o.label)"
        >
          <span
            class="inline-block h-3 w-3 shrink-0 rounded-full border"
            :class="selections[gid(g, i)] === (o.id ?? o.label)
              ? 'border-ctp-blue bg-ctp-blue' : 'border-ctp-overlay0'"
          />
          <span class="font-mono text-[10px] text-ctp-overlay1">{{ o.id }}</span>
          <span>{{ o.label }}</span>
          <span v-if="o.hint" class="text-[10px] text-ctp-overlay0">{{ o.hint }}</span>
          <span
            v-if="o.recommended"
            class="chip !text-[9px] bg-ctp-green/15 text-ctp-green"
          >推荐</span>
        </button>
      </div>

      <!-- 自定义输入: 选择题恒驻; 开放题组整组即输入 -->
      <input
        v-model="customs[gid(g, i)]"
        class="w-full rounded border border-ctp-surface0 bg-ctp-crust/40 px-2 py-1 text-[11px] text-ctp-text outline-none placeholder:text-ctp-overlay0 focus:border-ctp-blue/50"
        :class="(g.options ?? []).length ? 'mt-0.5' : ''"
        :placeholder="(g.options ?? []).length ? '或自定义回答…' : (g.question || '输入你的回答…')"
        :disabled="disabled || answered.done || skipped[gid(g, i)]"
        data-test="choices-custom"
        @input="onCustom(gid(g, i))"
      >
    </div>

    <input
      v-model="extra.note"
      class="mt-0.5 w-full rounded border border-ctp-surface0 bg-ctp-crust/40 px-2 py-1 text-[11px] text-ctp-text outline-none placeholder:text-ctp-overlay0 focus:border-ctp-blue/50"
      placeholder="补充说明(可选)——也可忽略此卡直接在下方输入区自由回复"
      :disabled="disabled || answered.done"
      data-test="choices-extra"
    >

    <div class="mt-2 flex items-center gap-2">
      <button
        class="btn-mini bg-ctp-blue/20 text-ctp-blue hover:bg-ctp-blue/30 disabled:opacity-40"
        :disabled="disabled || answered.done || !replyText"
        data-test="choices-send"
        @click="sendReply"
      >发送回复</button>
      <span
        v-if="missingCount > 0 && !answered.done"
        class="text-[10px] text-ctp-overlay0"
      >{{ missingCount }} 个建议回答项未填（可跳过）</span>
      <span v-else-if="answered.done" class="text-[10px] text-ctp-overlay0">
        {{ replyText }}
      </span>
    </div>
  </div>
</template>
