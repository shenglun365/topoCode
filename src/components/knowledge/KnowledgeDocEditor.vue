<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  ArrowLeftIcon,
  PencilIcon,
  EyeIcon,
  ArrowDownTrayIcon,
  LinkIcon,
} from '@heroicons/vue/24/outline'
import type { KnowledgeDoc } from '@/types'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('KN-002')
const { t } = useI18n()

const props = defineProps<{
  doc: KnowledgeDoc
}>()

const emit = defineEmits<{
  back: []
  save: [docId: string, content: string]
}>()

const editMode = ref<'edit' | 'browse'>('edit')
const content = ref(props.doc.content)

const lineCount = computed(() => content.value.split('\n').length)

function handleSave() {
  emit('save', props.doc.id, content.value)
}
</script>

<template>
  <div class="kb-doc-editor">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <!-- 顶部栏 -->
    <div style="display:flex; justify-content:space-between; align-items:center; padding:8px 16px; border-bottom:1px solid var(--border); background:var(--bg-secondary); flex-shrink:0;">
      <div style="display:flex; align-items:center; gap:10px;">
        <button
          class="btn btn-ghost btn-sm"
          @click="emit('back')"
        >
          <ArrowLeftIcon class="w-4 h-4" />
          <span>{{ t('common.back') }}</span>
        </button>
        <span style="font-size:13px; font-weight:600;">{{ doc.title }}</span>
        <span
          class="badge badge-blue"
          style="font-size:8px;"
        >{{ t('knowledge.documents') }}</span>
        <span
          class="badge badge-green"
          style="font-size:8px;"
        >{{ t('common.saved') }}</span>
      </div>
      <div style="display:flex; gap:6px; align-items:center;">
        <!-- 模式切换 -->
        <div style="display:flex; border:1px solid var(--border); border-radius:4px; overflow:hidden;">
          <button
            class="btn btn-ghost"
            :class="{ active: editMode === 'edit' }"
            style="border:none; border-radius:0; font-size:11px; padding:4px 12px;"
            @click="editMode = 'edit'"
          >
            <PencilIcon class="w-3 h-3" />
            <span>{{ t('common.edit') }}</span>
          </button>
          <button
            class="btn btn-ghost"
            :class="{ active: editMode === 'browse' }"
            style="border:none; border-left:1px solid var(--border); border-radius:0; font-size:11px; padding:4px 12px;"
            @click="editMode = 'browse'"
          >
            <EyeIcon class="w-3 h-3" />
            <span>{{ t('common.preview') }}</span>
          </button>
        </div>
        <button
          class="btn btn-ghost btn-sm"
          @click="handleSave"
        >
          <ArrowDownTrayIcon class="w-4 h-4" />
          <span>{{ t('common.save') }}</span>
        </button>
        <button class="btn btn-ghost btn-sm">
          <LinkIcon class="w-4 h-4" />
          <span>{{ t('common.share') }}</span>
        </button>
      </div>
    </div>

    <!-- 编辑模式 -->
    <div
      v-if="editMode === 'edit'"
      style="flex:1; overflow:hidden; display:flex;"
    >
      <!-- 行号栏 -->
      <div
        style="width:40px; background:var(--bg-secondary); border-right:1px solid var(--border); padding:12px 0; text-align:right; font-family:var(--font-mono); font-size:12px; line-height:1.6; color:var(--text-muted); user-select:none; flex-shrink:0; overflow:hidden;"
      >
        <div
          v-for="i in lineCount"
          :key="i"
          style="padding: 0 8px;"
        >
          {{ i }}
        </div>
      </div>
      <!-- 代码编辑区 -->
      <textarea
        v-model="content"
        spellcheck="false"
        style="flex:1; padding:12px; border:none; outline:none; resize:none; font-family:var(--font-mono); font-size:12px; line-height:1.6; background:var(--bg-secondary); color:var(--text-primary); tab-size:2;"
      />
    </div>

    <!-- 浏览模式 -->
    <div
      v-else
      style="flex:1; overflow:auto; padding:20px 24px;"
    >
      <div style="max-width:800px; margin:0 auto;">
        <h1 style="font-size:24px; font-weight:700; margin-bottom:16px; padding-bottom:8px; border-bottom:2px solid var(--border);">
          {{ doc.title }}
        </h1>
        <div style="font-size:13px; line-height:1.7; color:var(--text-secondary);">
          <pre style="white-space:pre-wrap; font-family:var(--font-sans);">{{ doc.content }}</pre>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.kb-doc-editor {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
</style>
