<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ipc } from '@/services/ipc'

const activeSubTab = ref<'routes' | 'skills' | 'tools'>('routes')
const config = ref<{ routes: any[]; skills: any[]; tools: any[] }>({ routes: [], skills: [], tools: [] })
const loading = ref(true)
const error = ref('')

onMounted(async () => {
  try {
    config.value = await ipc.analysis.getAgentConfig()
  } catch (e: any) {
    error.value = e?.message || '加载失败'
  } finally {
    loading.value = false
  }
})

const tabs = [
  { key: 'routes' as const, label: '路由 (Routes)', count: () => config.value.routes.length },
  { key: 'skills' as const, label: '技能 (Skills)', count: () => config.value.skills.length },
  { key: 'tools' as const, label: '工具 (Tools)', count: () => config.value.tools.length },
]
</script>

<template>
  <div class="agcfg-container">
    <div class="agcfg-tabs">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        class="agcfg-tab"
        :class="{ active: activeSubTab === tab.key }"
        @click="activeSubTab = tab.key"
      >
        {{ tab.label }} ({{ tab.count() }})
      </button>
    </div>

    <div v-if="loading" class="agcfg-loading">加载中...</div>
    <div v-else-if="error" class="agcfg-error">{{ error }}</div>

    <template v-else>
      <!-- Routes -->
      <div v-if="activeSubTab === 'routes'" class="agcfg-list">
        <div v-for="r in config.routes" :key="r.action" class="agcfg-item">
          <div class="agcfg-item-name">{{ r.action }}</div>
          <div class="agcfg-item-workflow">{{ r.workflow }}</div>
          <div class="agcfg-item-desc">{{ r.description }}</div>
        </div>
      </div>

      <!-- Skills -->
      <div v-if="activeSubTab === 'skills'" class="agcfg-list">
        <div v-for="s in config.skills" :key="s.name" class="agcfg-item">
          <div class="agcfg-item-name">{{ s.name }}</div>
          <div class="agcfg-item-meta">{{ s.steps }} 步骤</div>
          <div class="agcfg-item-desc">{{ s.description }}</div>
        </div>
      </div>

      <!-- Tools -->
      <div v-if="activeSubTab === 'tools'" class="agcfg-list">
        <div v-for="t in config.tools" :key="t.name" class="agcfg-item">
          <div class="agcfg-item-name">{{ t.name }}</div>
          <div class="agcfg-item-meta">{{ t.category }} | {{ t.llm_visible ? 'LLM可见' : '内部' }}</div>
          <div class="agcfg-item-desc">{{ t.description }}</div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.agcfg-container { padding: 0.75rem; }
.agcfg-tabs { display: flex; gap: 0.25rem; margin-bottom: 0.75rem; border-bottom: 1px solid var(--border); padding-bottom: 0.5rem; }
.agcfg-tab { font-size: 0.7rem; padding: 0.2rem 0.6rem; border: 1px solid var(--border); border-radius: 4px; background: var(--bg-secondary); color: var(--text-muted); cursor: pointer; }
.agcfg-tab.active { background: var(--accent); color: #fff; border-color: var(--accent); }
.agcfg-loading, .agcfg-error { text-align: center; padding: 1rem; font-size: 0.75rem; color: var(--text-muted); }
.agcfg-error { color: var(--danger, #ef4444); }
.agcfg-list { display: flex; flex-direction: column; gap: 0.5rem; max-height: 60vh; overflow-y: auto; }
.agcfg-item { background: var(--bg-primary); border: 1px solid var(--border); border-radius: 6px; padding: 0.5rem 0.75rem; }
.agcfg-item-name { font-size: 0.8rem; font-weight: 600; color: var(--text-primary); font-family: var(--font-mono); }
.agcfg-item-workflow { font-size: 0.65rem; color: var(--accent); margin-top: 0.15rem; }
.agcfg-item-meta { font-size: 0.65rem; color: var(--text-muted); margin-top: 0.15rem; }
.agcfg-item-desc { font-size: 0.7rem; color: var(--text-secondary); margin-top: 0.25rem; }
</style>
