<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ArrowLeftIcon, DocumentTextIcon } from '@heroicons/vue/24/outline'
import MarkdownView from '@/components/MarkdownView.vue'
import { apiGet } from '@/services/api-client'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()

const content = ref('')
const title = ref('')
const loading = ref(true)
const error = ref('')

onMounted(async () => {
  const id = String(route.params.docId ?? '')
  if (!id) {
    error.value = 'doc not found'
    loading.value = false
    return
  }
  try {
    const data = await apiGet<{ id: string; title?: string; content: string }>(`/docs/${id}`)
    content.value = data?.content ?? ''
    title.value = data?.title ?? id
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
})

function goBack() {
  router.back()
}
</script>

<template>
  <div class="p-6 max-w-4xl mx-auto">
    <div class="flex items-center gap-3 mb-4">
      <button
        class="btn btn-ghost !px-2 !py-1 text-xs"
        :title="t('doc.back')"
        @click="goBack"
      >
        <ArrowLeftIcon class="w-4 h-4" />{{ t('doc.back') }}
      </button>
      <div class="flex items-center gap-2 text-sm text-ctp-text">
        <DocumentTextIcon class="w-4 h-4 text-ctp-mauve" />
        <span class="font-medium">{{ title || t('doc.title') }}</span>
      </div>
    </div>

    <div v-if="loading" class="text-xs text-ctp-subtext0">{{ t('app.loading') }}</div>
    <div
      v-else-if="error"
      class="text-xs text-ctp-red border border-ctp-red/30 bg-ctp-red/5 rounded-md px-3 py-2"
    >{{ error }}</div>

    <!-- md 只读预览渲染 -->
    <article
      v-else
      class="panel p-6 bg-ctp-mantle/40"
    >
      <MarkdownView :content="content" />
      <p class="mt-6 pt-3 border-t border-ctp-surface0 text-[10px] text-ctp-overlay1">
        {{ t('doc.readonly') }}
      </p>
    </article>
  </div>
</template>
