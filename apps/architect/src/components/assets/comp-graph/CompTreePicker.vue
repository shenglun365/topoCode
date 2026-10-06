<script setup lang="ts">
/**
 * 组件范围树状多选(catalog parentId 层级)——文件级图谱的范围圈定。
 * 父选中不级联子(组件扁平语义)；列表按名称排序, 搜索过滤。
 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { MagnifyingGlassIcon, FolderIcon } from '@heroicons/vue/24/outline'

const props = defineProps<{
  /** catalog 组件集(id/name/parentId/kind/fileCount/change)。 */
  nodes: {
    id: string; name: string; parentId: string; kind?: string
    fileCount?: number; change?: { added: number; modified: number; deleted: number }
  }[]
  /** 已选组件 id 集(v-model)。 */
  modelValue: string[]
}>()
const emit = defineEmits<{ 'update:modelValue': [ids: string[]] }>()

const { t } = useI18n()
const q = ref('')

interface TreeItem {
  id: string; name: string; depth: number
  fileCount: number; change?: { added: number; modified: number; deleted: number }
}

/** DFS 树序(父在前, 子缩进)；搜索命中平铺。 */
const tree = computed<TreeItem[]>(() => {
  const kw = q.value.trim().toLowerCase()
  const byParent = new Map<string, typeof props.nodes>()
  for (const n of props.nodes) {
    const p = n.parentId || ''
    if (!byParent.has(p)) byParent.set(p, [])
    byParent.get(p)!.push(n)
  }
  const out: TreeItem[] = []
  const walk = (parent: string, depth: number) => {
    const kids = (byParent.get(parent) || [])
      .filter((n) => !kw || n.name.toLowerCase().includes(kw))
      .sort((a, b) => a.name.localeCompare(b.name))
    for (const n of kids) {
      out.push({ id: n.id, name: n.name, depth, fileCount: n.fileCount || 0, change: n.change })
      walk(n.id, depth + 1)
    }
  }
  walk('', 0)
  // 搜索模式下父被滤掉时子树仍应出现——kw 非空且树空 → 平铺全匹配
  if (kw && !out.length) {
    for (const n of props.nodes) {
      if (n.name.toLowerCase().includes(kw)) {
        out.push({ id: n.id, name: n.name, depth: 0, fileCount: n.fileCount || 0, change: n.change })
      }
    }
  }
  return out
})

const selected = computed(() => new Set(props.modelValue))

function toggle(id: string) {
  const next = new Set(props.modelValue)
  if (next.has(id)) next.delete(id); else next.add(id)
  emit('update:modelValue', [...next])
}

function changeBadge(ch?: { added: number; modified: number; deleted: number }): string {
  if (!ch || (!ch.added && !ch.modified && !ch.deleted)) return ''
  return `+${ch.added} ~${ch.modified} -${ch.deleted}`
}
</script>

<template>
  <div class="flex flex-col min-h-0 h-full">
    <div class="shrink-0 px-2 pt-2 pb-1.5 space-y-1.5 border-b border-ctp-surface0">
      <div class="flex items-center gap-1.5 text-[10px] text-ctp-overlay1">
        <FolderIcon class="w-3.5 h-3.5 text-ctp-mauve" />
        <span>{{ t('compGraph.scopeTitle') }}</span>
        <span class="ml-auto text-ctp-overlay0">{{ modelValue.length }}/{{ nodes.length }}</span>
      </div>
      <input
        v-model="q"
        class="w-full text-[11px] bg-ctp-surface0 text-ctp-text rounded px-2 py-1 border border-ctp-surface1 outline-none focus:border-ctp-mauve placeholder:text-ctp-overlay0"
        :placeholder="t('compGraph.scopeSearch')"
      />
      <div class="flex items-center gap-2 text-[10px]">
        <button class="text-ctp-sky hover:underline" @click="emit('update:modelValue', tree.map((x) => x.id))">
          {{ t('compGraph.scopeAll') }}
        </button>
        <button class="text-ctp-overlay1 hover:text-ctp-text hover:underline" @click="emit('update:modelValue', [])">
          {{ t('compGraph.scopeNone') }}
        </button>
      </div>
    </div>
    <div class="flex-1 min-h-0 overflow-y-auto py-1">
      <button
        v-for="item in tree"
        :key="item.id"
        class="w-full flex items-center gap-1.5 px-2 py-1 text-left text-[11px] hover:bg-ctp-surface0"
        :class="selected.has(item.id) ? 'bg-ctp-mauve/10 text-ctp-text' : 'text-ctp-subtext0'"
        :style="{ paddingLeft: `${8 + item.depth * 12}px` }"
        @click="toggle(item.id)"
      >
        <span
          class="w-3.5 h-3.5 rounded border flex items-center justify-center shrink-0 text-[9px]"
          :class="selected.has(item.id) ? 'bg-ctp-mauve border-ctp-mauve text-ctp-crust' : 'border-ctp-overlay0'"
        >{{ selected.has(item.id) ? '✓' : '' }}</span>
        <span class="truncate flex-1" :title="item.name">{{ item.name }}</span>
        <span v-if="changeBadge(item.change)" class="text-[9px] text-ctp-peach shrink-0">{{ changeBadge(item.change) }}</span>
        <span class="text-[9px] text-ctp-overlay0 shrink-0">{{ item.fileCount }}</span>
      </button>
      <p v-if="!tree.length" class="px-2 py-3 text-[10px] text-ctp-overlay0 text-center">
        {{ t('compGraph.scopeEmpty') }}
      </p>
    </div>
  </div>
</template>
