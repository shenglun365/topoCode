<script setup lang="ts">
// cv-279 需求内容编辑浮窗: title/desc 文本编辑 → PUT /requirements/{id}/content
// (版本链 append+confirm, 旧版快照行不动); 保存成功后后端落新版 spec 卡(SSE 刷新)。
// 单组件双入口复用: 消息流需求卡编辑钮 + ReqDetailWindow 内编辑(cv-284)。
import { computed, ref, watch } from 'vue'
import { apiPut } from '@/services/api-client'

const props = defineProps<{
  requirementId: string
  title: string
  desc: string
  convId?: string
}>()

const emit = defineEmits<{ close: []; saved: [ver: number] }>()

const title = ref(props.title)
const desc = ref(props.desc)
const busy = ref(false)
const errMsg = ref('')

watch(() => props.requirementId, () => {
  title.value = props.title
  desc.value = props.desc
  errMsg.value = ''
})

const dirty = computed(() => title.value.trim() !== props.title.trim()
  || desc.value.trim() !== props.desc.trim())

async function save() {
  if (busy.value || !dirty.value) return
  busy.value = true
  errMsg.value = ''
  try {
    const res = await apiPut<{ ok: boolean; ver: number; error?: string }>(
      `/requirements/${encodeURIComponent(props.requirementId)}/content`,
      { title: title.value, desc: desc.value, convId: props.convId || '' })
    emit('saved', res.ver)
    emit('close')
  } catch (e) {
    errMsg.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <Teleport to="body">
    <div
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-6"
      @click.self="emit('close')"
    >
      <div class="flex w-[72vw] max-w-3xl max-h-[80vh] flex-col rounded-lg border border-ctp-surface1 bg-ctp-base shadow-2xl">
        <div class="flex shrink-0 items-center justify-between border-b border-ctp-surface1 px-3 py-2">
          <span class="text-xs font-medium text-ctp-subtext1">编辑需求 — 保存后生成新版(v+1)，旧版保留为历史快照</span>
          <button class="btn btn-xs btn-ghost" @click="emit('close')">✕ 关闭</button>
        </div>
        <div class="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto px-4 py-3">
          <label class="text-[11px] text-ctp-subtext0">标题</label>
          <input
            v-model="title"
            class="w-full rounded-md border border-ctp-surface1 bg-ctp-mantle px-2.5 py-1.5 text-sm text-ctp-text outline-none focus:border-ctp-blue"
            placeholder="需求标题"
          >
          <label class="text-[11px] text-ctp-subtext0">需求目标</label>
          <textarea
            v-model="desc"
            rows="14"
            class="w-full flex-1 resize-none rounded-md border border-ctp-surface1 bg-ctp-mantle px-2.5 py-2 font-mono text-[12px] leading-relaxed text-ctp-text outline-none focus:border-ctp-blue"
            placeholder="需求目标描述"
          />
          <span
            v-if="errMsg"
            class="text-[11px] text-ctp-red"
          >⚠ {{ errMsg }}</span>
        </div>
        <div class="flex shrink-0 items-center justify-end gap-2 border-t border-ctp-surface1 px-3 py-2">
          <button class="btn btn-xs btn-ghost" :disabled="busy" @click="emit('close')">取消</button>
          <button
            class="btn btn-xs btn-blue"
            :disabled="busy || !dirty || !title.trim() || !desc.trim()"
            :title="dirty ? '保存并生成新版需求' : '内容未变更'"
            @click="save"
          >{{ busy ? '保存中…' : '保存(生成新版)' }}</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
