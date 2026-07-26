<script setup lang="ts">
import type { DialogState } from '@web/composables/useDialog'

const props = defineProps<{ dialog: DialogState }>()
const emit = defineEmits<{ ok: [value?: string]; cancel: [] }>()
</script>

<template>
  <div v-if="dialog.show" class="dialog-overlay" @click.self="dialog.type !== 'alert' && emit('cancel')" @keydown.escape="emit('cancel')">
    <div class="dialog-box">
      <h3>{{ dialog.title }}</h3>
      <p>{{ dialog.message }}</p>
      <input v-if="dialog.type === 'prompt'" v-model="dialog.value" class="dialog-input" @keydown.enter="emit('ok', dialog.value)" ref="inputRef" />
      <div class="dialog-actions">
        <button v-if="dialog.type !== 'alert'" class="dialog-btn" @click="emit('cancel')">取消</button>
        <button class="dialog-btn primary" @click="emit('ok', dialog.value)">{{ dialog.type === 'alert' ? '确定' : '确认' }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.dialog-overlay{position:fixed;inset:0;background:rgba(0,0,0,0.5);display:flex;align-items:center;justify-content:center;z-index:9999;animation:fadeIn .15s ease}
.dialog-box{background:var(--bg, #fff);border:1px solid var(--border, #e4e4e7);border-radius:12px;padding:24px;width:360px;max-width:90vw;box-shadow:0 8px 32px rgba(0,0,0,0.25)}
.dialog-box h3{font-size:15px;font-weight:600;color:var(--text, #1a1a1a);margin-bottom:12px}
.dialog-box p{font-size:14px;color:var(--text-secondary, #6b6b76);margin-bottom:16px;line-height:1.5}
.dialog-input{width:100%;padding:8px 12px;border:1px solid var(--border, #e4e4e7);border-radius:8px;font-size:14px;background:var(--bg, #fff);color:var(--text, #1a1a1a);outline:none;margin-bottom:16px;box-sizing:border-box}
.dialog-input:focus{border-color:var(--accent, #4d6bfe)}
.dialog-actions{display:flex;gap:8px;justify-content:flex-end}
.dialog-btn{padding:7px 16px;border-radius:8px;font-size:13px;cursor:pointer;border:1px solid var(--border, #e4e4e7);background:var(--bg, #fff);color:var(--text, #1a1a1a)}
.dialog-btn:hover{border-color:var(--accent, #4d6bfe)}
.dialog-btn.primary{background:var(--accent, #4d6bfe);color:#fff;border-color:var(--accent, #4d6bfe)}
.dialog-btn.primary:hover{background:var(--accent-hover, #3a56d4)}
@keyframes fadeIn{from{opacity:0}to{opacity:1}}
</style>
