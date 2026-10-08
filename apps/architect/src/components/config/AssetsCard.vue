<script setup lang="ts">
/**
 * 技能管理卡（2610 技能管理面）——architect skills 能力配置，分类分组。
 *
 * 数据面：GET /arch/skills（内置 category 分组 ∪ 表技能同名覆盖，含禁用行
 * ——禁用即回退内置，D-1）。需求/任务等软件开发类资产不在此面。
 * skill 型 payload 三字段：route_hint（必填）/ instructions_md / child_registry。
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { PlusIcon, TrashIcon, CheckCircleIcon, XCircleIcon } from '@heroicons/vue/24/outline'
import { assetsService, type SkillEntry, type SkillGroup } from '@/services/assets-service'
import { useAppDialog } from '@/composables/useAppDialog'
import { currentProjectParams } from '@/services/project-service'

const { t } = useI18n()
const dialog = useAppDialog()

const groups = ref<SkillGroup[]>([])
const loading = ref(false)
const errorText = ref('')
const collapsed = ref<Record<string, boolean>>({})

const totalSkills = computed(() =>
  groups.value.reduce((n, g) => n + g.skills.length, 0))

const CATEGORY_LABELS: Record<string, string> = {
  'requirement-analysis': '需求分析',
  quality: '质量',
  custom: '自定义技能',
  builtin: '内置技能',
}
const labelOf = (c: string) => CATEGORY_LABELS[c] || c

const editing = ref(false)
const form = ref<{ assetId?: string; name: string; description: string; routeHint: string; instructionsMd: string; childRegistry: string }>({
  name: '', description: '', routeHint: '', instructionsMd: '', childRegistry: '',
})

async function refresh() {
  loading.value = true
  errorText.value = ''
  try {
    groups.value = await assetsService.skillsGroups(
      currentProjectParams().project || '')
  } catch (e) {
    errorText.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

function openCreate() {
  form.value = { name: '', description: '', routeHint: '', instructionsMd: '', childRegistry: '' }
  editing.value = true
}

function openEdit(s: SkillEntry) {
  form.value = {
    assetId: s.assetId, name: s.name, description: s.description,
    routeHint: s.route_hint,
    instructionsMd: '', childRegistry: s.child_registry.join(', '),
  }
  editing.value = true
}

async function save() {
  const f = form.value
  if (!f.name.trim()) { errorText.value = t('config.skills.nameRequired'); return }
  if (!f.routeHint.trim()) { errorText.value = t('config.skills.routeHintRequired'); return }
  const dup = groups.value.some((g) => g.skills.some(
    (s) => s.name === f.name.trim() && s.assetId && s.assetId !== f.assetId))
  if (dup && !(await dialog.confirm(t('config.skills.overrideConfirm', { name: f.name })))) return
  try {
    await assetsService.upsert({
      id: f.assetId, kind: 'skill', name: f.name.trim(),
      description: f.description,
      payload: {
        route_hint: f.routeHint.trim(),
        child_registry: f.childRegistry.split(',').map((x) => x.trim()).filter(Boolean),
      },
    })
    editing.value = false
    await refresh()
  } catch (e) {
    errorText.value = e instanceof Error ? e.message : String(e)
  }
}

async function toggle(s: SkillEntry) {
  if (!s.assetId) return
  try {
    await assetsService.upsert({
      id: s.assetId, kind: 'skill', name: s.name,
      description: s.description, payload: {
        route_hint: s.route_hint, child_registry: s.child_registry,
      }, enabled: !s.enabled,
    })
    await refresh()
  } catch (e) {
    errorText.value = e instanceof Error ? e.message : String(e)
  }
}

async function remove(s: SkillEntry) {
  if (!s.assetId) return
  if (!(await dialog.confirm(t('config.skills.deleteConfirm', { name: s.name }), { danger: true }))) return
  await assetsService.remove(s.assetId)
  await refresh()
}

onMounted(refresh)
</script>

<template>
  <div class="panel overflow-hidden">
    <div class="flex items-center gap-2 px-4 py-3 border-b border-ctp-surface0">
      <h3 class="text-sm font-medium">{{ t('config.skills.title') }}</h3>
      <span class="text-[11px] text-ctp-overlay1">{{ t('config.skills.hint') }}</span>
      <span class="chip bg-ctp-surface0 text-ctp-subtext0 ml-auto">{{ totalSkills }}</span>
      <button class="btn btn-sm btn-green" @click="openCreate">
        <PlusIcon class="w-3.5 h-3.5" />{{ t('common.create') }}
      </button>
    </div>

    <div v-if="errorText" class="px-4 py-2 text-xs text-ctp-red">{{ errorText }}</div>

    <div class="max-h-[32rem] overflow-auto">
      <div v-for="g in groups" :key="g.category" class="border-b border-ctp-surface0 last:border-0">
        <button
          class="w-full flex items-center gap-2 px-4 py-2 text-xs bg-ctp-mantle/50 hover:bg-ctp-surface0/50"
          @click="collapsed[g.category] = !collapsed[g.category]"
        >
          <span class="font-medium text-ctp-subtext1">{{ labelOf(g.category) }}</span>
          <span class="chip bg-ctp-surface0 text-ctp-overlay0">{{ g.skills.length }}</span>
        </button>
        <div v-show="!collapsed[g.category]" class="divide-y divide-ctp-surface0">
          <div v-for="s in g.skills" :key="g.category + s.name" class="flex items-start gap-2 px-4 py-2 text-xs">
            <code class="font-mono text-ctp-sapphire shrink-0">{{ s.name }}</code>
            <span
              class="chip shrink-0"
              :class="s.source === 'asset' ? 'bg-ctp-teal/15 text-ctp-teal' : 'bg-ctp-surface0 text-ctp-overlay0'"
            >{{ s.source === 'asset' ? t('config.skills.srcAsset') : t('config.skills.srcBuiltin') }}</span>
            <div class="flex-1 min-w-0">
              <div class="text-ctp-subtext1 truncate">{{ s.description }}</div>
              <div v-if="s.route_hint" class="text-[10px] text-ctp-overlay0 truncate" :title="s.route_hint">
                {{ t('config.skills.when') }}: {{ s.route_hint }}
              </div>
            </div>
            <template v-if="s.source === 'asset'">
              <button class="text-ctp-overlay1 hover:text-ctp-text shrink-0" @click="toggle(s)">
                <CheckCircleIcon v-if="s.enabled" class="w-4 h-4 text-ctp-green" />
                <XCircleIcon v-else class="w-4 h-4" />
              </button>
              <button class="btn btn-xs shrink-0" @click="openEdit(s)">{{ t('common.edit') }}</button>
              <button class="btn btn-xs btn-red shrink-0" @click="remove(s)">
                <TrashIcon class="w-3 h-3" />
              </button>
            </template>
            <span v-else class="text-[10px] text-ctp-overlay0 shrink-0">{{ t('config.skills.readonly') }}</span>
          </div>
        </div>
      </div>
      <div v-if="!groups.length && !loading" class="px-4 py-8 text-center text-xs text-ctp-overlay0">
        {{ t('common.empty') }}
      </div>
    </div>

    <!-- 编辑表单(行内, kind 固定 skill) -->
    <div v-if="editing" class="border-t border-ctp-surface0 p-4 space-y-2">
      <div class="grid grid-cols-2 gap-2">
        <input v-model="form.name" class="input text-xs" :placeholder="t('config.skills.nameRequired')">
        <input v-model="form.description" class="input text-xs" :placeholder="t('config.skills.colDesc')">
      </div>
      <input v-model="form.routeHint" class="input text-xs" :placeholder="t('config.skills.routeHintRequired')">
      <textarea v-model="form.instructionsMd" class="input text-xs font-mono" rows="3"
        :placeholder="t('config.skills.instructionsPh')" />
      <input v-model="form.childRegistry" class="input text-xs font-mono" :placeholder="t('config.skills.childRegistryPh')" />
      <div class="flex justify-end gap-2">
        <button class="btn btn-sm" @click="editing = false">{{ t('common.cancel') }}</button>
        <button class="btn btn-sm btn-green" @click="save">{{ t('common.save') }}</button>
      </div>
    </div>
  </div>
</template>
