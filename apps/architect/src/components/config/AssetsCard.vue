<script setup lang="ts">
/**
 * L-2 资产/技能管理卡（2610-B1 deferred）——arch_assets 的列表/编辑/启停/删除。
 *
 * W6 REST 先行的补面（C1 先例）；内置技能（_ARCH_SKILLS）为代码注册只读，
 * 本卡只管理表资产（同名覆盖内置——D-1 表为真相源的运行语义）。
 * skill 型 payload 三字段：route_hint（必填，REST 校验对齐）/ instructions_md /
 * child_registry（逗号清单）。
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { PlusIcon, TrashIcon, CheckCircleIcon, XCircleIcon } from '@heroicons/vue/24/outline'
import { ASSET_KINDS, assetsService, type ArchAsset } from '@/services/assets-service'
import { useAppDialog } from '@/composables/useAppDialog'
import { useArchProjectStore } from '@/stores/project-store'

const { t } = useI18n()
const dialog = useAppDialog()
const project = useArchProjectStore()

const rows = ref<ArchAsset[]>([])
const loading = ref(false)
const errorText = ref('')
const kindFilter = ref('skill')

const filtered = computed(() =>
  rows.value.filter((r) => !kindFilter.value || r.kind === kindFilter.value))

const editing = ref(false)
const form = ref<{ id?: string; kind: string; name: string; description: string; routeHint: string; instructionsMd: string; childRegistry: string }>({
  kind: 'skill', name: '', description: '', routeHint: '', instructionsMd: '', childRegistry: '',
})

async function refresh() {
  loading.value = true
  errorText.value = ''
  try {
    rows.value = await assetsService.list()
  } catch (e) {
    errorText.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

function openCreate() {
  form.value = { kind: kindFilter.value || 'skill', name: '', description: '', routeHint: '', instructionsMd: '', childRegistry: '' }
  editing.value = true
}

function openEdit(a: ArchAsset) {
  const p = a.payload || {}
  form.value = {
    id: a.id, kind: a.kind, name: a.name, description: a.description,
    routeHint: String(p.route_hint || ''),
    instructionsMd: String(p.instructions_md || ''),
    childRegistry: (Array.isArray(p.child_registry) ? p.child_registry : []).join(', '),
  }
  editing.value = true
}

async function save() {
  const f = form.value
  if (!f.name.trim()) { errorText.value = t('config.assets.nameRequired'); return }
  if (f.kind === 'skill' && !f.routeHint.trim()) {
    errorText.value = t('config.assets.routeHintRequired'); return
  }
  const same = rows.value.find((r) => r.kind === f.kind && r.name === f.name && r.id !== f.id)
  if (same && !(await dialog.confirm(t('config.assets.overrideConfirm', { name: f.name })))) return
  try {
    await assetsService.upsert({
      id: f.id, kind: f.kind, name: f.name.trim(), description: f.description,
      payload: f.kind === 'skill'
        ? {
            route_hint: f.routeHint.trim(),
            instructions_md: f.instructionsMd,
            child_registry: f.childRegistry.split(',').map((s) => s.trim()).filter(Boolean),
          }
        : {},
    })
    editing.value = false
    await refresh()
  } catch (e) {
    errorText.value = e instanceof Error ? e.message : String(e)
  }
}

async function toggle(a: ArchAsset) {
  try {
    await assetsService.upsert({
      id: a.id, kind: a.kind, name: a.name, description: a.description,
      payload: a.payload, enabled: !a.enabled,
    })
    await refresh()
  } catch (e) {
    errorText.value = e instanceof Error ? e.message : String(e)
  }
}

async function remove(a: ArchAsset) {
  if (!(await dialog.confirm(t('config.assets.deleteConfirm', { name: a.name }), { danger: true }))) return
  await assetsService.remove(a.id)
  await refresh()
}

onMounted(refresh)
</script>

<template>
  <div class="panel overflow-hidden">
    <div class="flex items-center gap-2 px-4 py-3 border-b border-ctp-surface0">
      <h3 class="text-sm font-medium">{{ t('config.assets.title') }}</h3>
      <span class="text-[11px] text-ctp-overlay1">{{ t('config.assets.hint') }}</span>
      <select v-model="kindFilter" class="input !py-1 text-xs ml-auto w-32">
        <option value="">{{ t('config.assets.allKinds') }}</option>
        <option v-for="k in ASSET_KINDS" :key="k" :value="k">{{ k }}</option>
      </select>
      <button class="btn btn-sm btn-green" @click="openCreate">
        <PlusIcon class="w-3.5 h-3.5" />{{ t('common.create') }}
      </button>
    </div>

    <div v-if="errorText" class="px-4 py-2 text-xs text-ctp-red">{{ errorText }}</div>

    <div class="overflow-auto max-h-[26rem]">
      <table class="w-full text-left text-xs">
        <thead class="sticky top-0 bg-ctp-mantle text-ctp-overlay1">
          <tr>
            <th class="px-3 py-2 font-medium">{{ t('config.assets.colName') }}</th>
            <th class="px-3 py-2 font-medium">kind</th>
            <th class="px-3 py-2 font-medium">{{ t('config.assets.colDesc') }}</th>
            <th class="px-3 py-2 font-medium">{{ t('config.assets.colRoute') }}</th>
            <th class="px-3 py-2 font-medium">{{ t('config.assets.colEnabled') }}</th>
            <th class="px-3 py-2 font-medium text-right">{{ t('common.actions') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="a in filtered" :key="a.id" class="border-t border-ctp-surface0">
            <td class="px-3 py-2 font-mono">{{ a.name }}</td>
            <td class="px-3 py-2"><span class="chip bg-ctp-surface0 text-ctp-subtext0">{{ a.kind }}</span></td>
            <td class="px-3 py-2 text-ctp-subtext0 max-w-[16rem] truncate" :title="a.description">{{ a.description }}</td>
            <td class="px-3 py-2 text-ctp-subtext0 max-w-[14rem] truncate" :title="String(a.payload?.route_hint || '')">
              {{ a.payload?.route_hint || '—' }}
            </td>
            <td class="px-3 py-2">
              <button class="text-ctp-overlay1 hover:text-ctp-text" @click="toggle(a)">
                <CheckCircleIcon v-if="a.enabled" class="w-4 h-4 text-ctp-green" />
                <XCircleIcon v-else class="w-4 h-4" />
              </button>
            </td>
            <td class="px-3 py-2 text-right">
              <button class="btn btn-sm mr-1" @click="openEdit(a)">{{ t('common.edit') }}</button>
              <button class="btn btn-sm btn-red" @click="remove(a)">
                <TrashIcon class="w-3 h-3" />
              </button>
            </td>
          </tr>
          <tr v-if="!filtered.length && !loading">
            <td colspan="6" class="px-3 py-8 text-center text-ctp-overlay0">{{ t('common.empty') }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 编辑表单(行内面板) -->
    <div v-if="editing" class="border-t border-ctp-surface0 p-4 space-y-2">
      <div class="grid grid-cols-2 gap-2">
        <input v-model="form.name" class="input text-xs" :placeholder="t('config.assets.nameRequired')">
        <select v-model="form.kind" class="input text-xs">
          <option v-for="k in ASSET_KINDS" :key="k" :value="k">{{ k }}</option>
        </select>
      </div>
      <input v-model="form.description" class="input text-xs" :placeholder="t('config.assets.colDesc')">
      <template v-if="form.kind === 'skill'">
        <input v-model="form.routeHint" class="input text-xs" :placeholder="t('config.assets.routeHintRequired')">
        <textarea v-model="form.instructionsMd" class="input text-xs font-mono" rows="3"
          :placeholder="t('config.assets.instructionsPh')" />
        <input v-model="form.childRegistry" class="input text-xs font-mono" :placeholder="t('config.assets.childRegistryPh')" />
      </template>
      <div class="flex justify-end gap-2">
        <button class="btn btn-sm" @click="editing = false">{{ t('common.cancel') }}</button>
        <button class="btn btn-sm btn-green" @click="save">{{ t('common.save') }}</button>
      </div>
    </div>
  </div>
</template>
