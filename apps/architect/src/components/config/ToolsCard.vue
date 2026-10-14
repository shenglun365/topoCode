<script setup lang="ts">
/**
 * 工具能力卡（2610）——architect 原生工具注册表快照（只读）。
 * 与技能(skills=执行路线目录)分工：工具是能力执行面，按名称前缀分组展示
 * brief/参数形状。数据面 GET /arch/tools。
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { WrenchIcon, MagnifyingGlassIcon } from '@heroicons/vue/24/outline'
import { apiGet } from '@/services/api-client'

const { t } = useI18n()

interface ToolEntry { name: string; description: string; brief: string; params_doc: string }
interface ToolGroup { group: string; tools: ToolEntry[] }

const groups = ref<ToolGroup[]>([])
const loading = ref(false)
const errorText = ref('')
const q = ref('')
const collapsed = ref<Record<string, boolean>>({})

const filtered = computed(() => {
  const kw = q.value.trim().toLowerCase()
  if (!kw) return groups.value
  return groups.value
    .map((g) => ({
      group: g.group,
      tools: g.tools.filter((x) =>
        `${x.name} ${x.description} ${x.brief}`.toLowerCase().includes(kw)),
    }))
    .filter((g) => g.tools.length)
})

const total = computed(() =>
  filtered.value.reduce((n, g) => n + g.tools.length, 0))

onMounted(async () => {
  loading.value = true
  try {
    groups.value = await apiGet<ToolGroup[]>('/arch/tools')
  } catch (e) {
    errorText.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="panel overflow-hidden">
    <div class="flex items-center gap-2 px-4 py-3 border-b border-ctp-surface0">
      <WrenchIcon class="w-4 h-4 text-ctp-peach" />
      <h3 class="text-sm font-medium">{{ t('config.tools.title') }}</h3>
      <span class="text-[11px] text-ctp-overlay1">{{ t('config.tools.hint') }}</span>
      <div class="relative ml-auto">
        <MagnifyingGlassIcon class="w-3.5 h-3.5 absolute left-2 top-1.5 text-ctp-overlay0" />
        <input v-model="q" class="input !py-1 !pl-7 text-xs w-44" :placeholder="t('config.tools.search')">
      </div>
      <span class="chip bg-ctp-surface0 text-ctp-subtext0">{{ total }}</span>
    </div>

    <div v-if="errorText" class="px-4 py-2 text-xs text-ctp-red">{{ errorText }}</div>

    <div class="max-h-[32rem] overflow-auto">
      <div v-for="g in filtered" :key="g.group" class="border-b border-ctp-surface0 last:border-0">
        <button
          class="w-full flex items-center gap-2 px-4 py-2 text-xs bg-ctp-mantle/50 hover:bg-ctp-surface0/50"
          @click="collapsed[g.group] = !collapsed[g.group]"
        >
          <span class="font-mono font-medium text-ctp-subtext1">{{ g.group }}.*</span>
          <span class="chip bg-ctp-surface0 text-ctp-overlay0">{{ g.tools.length }}</span>
        </button>
        <div v-show="!collapsed[g.group]" class="divide-y divide-ctp-surface0">
          <details v-for="x in g.tools" :key="x.name" class="group">
            <summary class="flex items-start gap-2 px-4 py-2 text-xs cursor-pointer hover:bg-ctp-surface0/30">
              <code class="font-mono text-ctp-sapphire shrink-0">{{ x.name }}</code>
              <span class="text-ctp-subtext1 flex-1 min-w-0">{{ x.brief || x.description }}</span>
            </summary>
            <div class="px-4 pb-2 pl-[4.5rem] space-y-1">
              <div class="text-[11px] text-ctp-subtext0">{{ x.description }}</div>
              <div v-if="x.params_doc" class="text-[11px] font-mono text-ctp-overlay0 whitespace-pre-wrap">{{ x.params_doc }}</div>
            </div>
          </details>
        </div>
      </div>
      <div v-if="!filtered.length && !loading" class="px-4 py-8 text-center text-xs text-ctp-overlay0">
        {{ t('common.empty') }}
      </div>
    </div>
  </div>
</template>
