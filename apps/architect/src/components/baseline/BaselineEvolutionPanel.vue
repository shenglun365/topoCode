<script setup lang="ts">
/**
 * BaselineEvolutionPanel（批5，需求 7）：架构变更视图。
 * 从基线开始，按指定分支/head 序列作为 step 帧的架构演化播放——
 * 帧序列手动挑选（版本历史点选加入），TopoStory 统一内核播放。
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import TopoStory from '@topo/graph-kernel/vue/TopoStory.vue'
import { projectService } from '@/services/project-service'
import type { EvolutionFrames } from '@/types'

const { t } = useI18n()

const refsText = ref('')           // 逗号分隔 ref 序列（branch/sha/版本id）
const loading = ref(false)
const error = ref('')
const data = ref<EvolutionFrames | null>(null)
const layer = ref<'component' | 'file'>('component')

const refList = computed(() => refsText.value.split(',').map((r) => r.trim()).filter(Boolean))

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    data.value = await projectService.evolutionFrames('baseline', 'HEAD', layer.value,
      refList.value.length ? refList.value : undefined)
    if (!data.value) error.value = t('nav.tree.loadFailed')
  } catch (e: any) {
    error.value = e?.message || t('nav.tree.loadFailed')
  } finally {
    loading.value = false
  }
}

/** 版本历史点选 → 加入帧序列 */
const versions = ref<Array<{ id: string; label: string; head: string; createdAt: string }>>([])
async function loadVersions(): Promise<void> {
  try {
    versions.value = (await projectService.versions()) ?? []
  } catch { /* 无版本历史可忽略 */ }
}
function addVersionRef(v: { id: string; head: string }): void {
  const cur = refList.value
  if (!cur.includes(v.head) && !cur.includes(v.id)) cur.push(v.head)
  refsText.value = cur.join(', ')
}
function clearRefs(): void {
  refsText.value = ''
}

onMounted(() => { void load(); void loadVersions() })
</script>

<template>
  <div class="flex flex-col gap-2">
    <!-- 帧序列编辑 -->
    <div class="flex items-center gap-2 flex-wrap text-[12px]">
      <span class="text-ctp-subtext0">帧序列(基线 → … → HEAD，逗号分隔 branch/sha)：</span>
      <input
        v-model="refsText"
        class="flex-1 min-w-[280px] px-2 py-1 rounded bg-ctp-surface0 border border-ctp-surface1 text-ctp-text text-[12px]"
        placeholder="如: main, v1.2, HEAD"
        @keydown.enter="load"
      >
      <button class="btn btn-sm btn-blue" :disabled="loading" @click="load">
        {{ loading ? '推演中…' : '推演帧' }}
      </button>
      <button class="btn btn-sm btn-ghost" title="清空自定义序列(回到自动采样)" @click="clearRefs">清空</button>
      <select
        v-model="layer"
        class="px-1.5 py-1 rounded bg-ctp-surface0 border border-ctp-surface1 text-[12px] text-ctp-subtext0"
        @change="load"
      >
        <option value="component">组件层</option>
        <option value="file">文件层</option>
      </select>
    </div>

    <!-- 版本历史快捷加入 -->
    <div v-if="versions.length" class="flex items-center gap-1.5 flex-wrap text-[11px]">
      <span class="text-ctp-overlay1">版本历史点选加入：</span>
      <button
        v-for="v in versions.slice(0, 8)"
        :key="v.id"
        class="chip bg-ctp-surface0 text-ctp-subtext0 hover:bg-ctp-surface1"
        :title="v.head"
        @click="addVersionRef(v)"
      >
        + {{ v.label }}
      </button>
    </div>

    <div v-if="error" class="text-ctp-red text-[12px]">{{ error }}</div>
    <div v-if="data" class="text-[11px] text-ctp-overlay1">
      {{ data.frames.length }} 帧 · {{ data.canonical.nodes.length }} 组件/文件 · {{ data.canonical.edges.length }} 依赖边
    </div>

    <!-- 演化播放（统一内核：基线 → 指定帧序列 → HEAD） -->
    <TopoStory
      v-if="data"
      :key="refsText + layer"
      :graph="data"
      :auto-play="true"
      :step-ms="1600"
      height="min(58vh, 620px)"
    />
  </div>
</template>
