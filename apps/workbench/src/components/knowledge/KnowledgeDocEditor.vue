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
import { useComponentId } from '@topo/web-core/composables/useComponentId'

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
    <div style="display:flex; justify-content:space-between; align-items:center; padding:calc(8px * var(--ui-scale, 1)) calc(16px * var(--ui-scale, 1)); border-bottom:1px solid var(--border); background:var(--bg-secondary); flex-shrink:0;">
      <div style="display:flex; align-items:center; gap:calc(10px * var(--ui-scale, 1));">
        <button
          class="btn btn-ghost btn-sm"
          @click="emit('back')"
        >
          <ArrowLeftIcon class="w-4 h-4" />
          <span>{{ t('common.back') }}</span>
        </button>
        <span style="font-size:calc(13px * var(--ui-scale, 1)); font-weight:600;">{{ doc.title }}</span>
        <span
          class="badge badge-blue"
          style="font-size:calc(8px * var(--ui-scale, 1));"
        >{{ t('knowledge.documents') }}</span>
        <span
          class="badge badge-green"
          style="font-size:calc(8px * var(--ui-scale, 1));"
        >{{ t('common.saved') }}</span>
      </div>
      <div style="display:flex; gap:calc(6px * var(--ui-scale, 1)); align-items:center;">
        <!-- 模式切换 -->
        <div style="display:flex; border:1px solid var(--border); border-radius:calc(4px * var(--ui-scale, 1)); overflow:hidden;">
          <button
            class="btn btn-ghost"
            :class="{ active: editMode === 'edit' }"
            style="border:none; border-radius:0; font-size:calc(11px * var(--ui-scale, 1)); padding:calc(4px * var(--ui-scale, 1)) calc(12px * var(--ui-scale, 1));"
            @click="editMode = 'edit'"
          >
            <PencilIcon class="w-3 h-3" />
            <span>{{ t('common.edit') }}</span>
          </button>
          <button
            class="btn btn-ghost"
            :class="{ active: editMode === 'browse' }"
            style="border:none; border-left:1px solid var(--border); border-radius:0; font-size:calc(11px * var(--ui-scale, 1)); padding:calc(4px * var(--ui-scale, 1)) calc(12px * var(--ui-scale, 1));"
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
        style="width:calc(40px * var(--ui-scale, 1)); background:var(--bg-secondary); border-right:1px solid var(--border); padding:calc(12px * var(--ui-scale, 1)) 0; text-align:right; font-family:var(--font-mono); font-size:calc(12px * var(--ui-scale, 1)); line-height:1.6; color:var(--text-muted); user-select:none; flex-shrink:0; overflow:hidden;"
      >
        <div
          v-for="i in lineCount"
          :key="i"
          style="padding: 0 calc(8px * var(--ui-scale, 1));"
        >
          {{ i }}
        </div>
      </div>
      <!-- 代码编辑区 -->
      <textarea
        v-model="content"
        spellcheck="false"
        style="flex:1; padding:calc(12px * var(--ui-scale, 1)); border:none; outline:none; resize:none; font-family:var(--font-mono); font-size:calc(12px * var(--ui-scale, 1)); line-height:1.6; background:var(--bg-secondary); color:var(--text-primary); tab-size:2;"
      />
    </div>

    <!-- 浏览模式 -->
    <div
      v-else
      style="flex:1; overflow:auto; padding:calc(20px * var(--ui-scale, 1)) calc(24px * var(--ui-scale, 1));"
    >
      <div style="max-width:calc(800px * var(--ui-scale, 1)); margin:0 auto;">
        <h1 style="font-size:calc(24px * var(--ui-scale, 1)); font-weight:700; margin-bottom:calc(16px * var(--ui-scale, 1)); padding-bottom:calc(8px * var(--ui-scale, 1)); border-bottom:2px solid var(--border);">
          {{ doc.title }}
        </h1>
        <div style="font-size:calc(13px * var(--ui-scale, 1)); line-height:1.7; color:var(--text-secondary);">
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
