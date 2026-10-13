<template>
  <div
    class="fixed inset-0 z-50 flex items-center justify-center bg-ctp-crust/60 p-4 backdrop-blur-sm"
    @click.self="emit('close')"
  >
    <div class="panel flex max-h-[80vh] w-full max-w-md flex-col">
      <div class="panel-header shrink-0">
        <span class="flex items-center gap-1.5 text-ctp-teal">
          <ClipboardDocumentListIcon class="h-4 w-4" />
          {{ isEdit ? t('guard.editTitle') : t('guard.newTitle') }}
        </span>
        <button class="btn btn-xs btn-ghost" @click="emit('close')">✕</button>
      </div>
      <div class="min-h-0 flex-1 space-y-2.5 overflow-y-auto p-3 text-xs">
        <input
          v-model="title"
          class="input !py-1 !text-[11px]"
          :placeholder="t('guard.titlePh')"
        >
        <textarea
          v-model="content"
          rows="7"
          class="input !py-1.5 !text-[11px]"
          :placeholder="t('guard.contentPh')"
        />
        <!-- 技能库导入: promoted 提案 → 填入表单(source=skill) -->
        <div class="flex items-center gap-1.5">
          <button
            class="btn btn-ghost btn-xs !text-[10px]"
            :disabled="skillLoading"
            :title="t('guard.importHint')"
            @click="toggleSkills"
          >
            {{ skillLoading ? '…' : t('guard.importSkill') }}
          </button>
          <span
            v-if="skills.length"
            class="chip bg-ctp-mauve/15 text-ctp-mauve !text-[9px]"
          >{{ skills.length }}</span>
        </div>
        <div
          v-if="skillsOpen"
          class="max-h-40 space-y-0.5 overflow-y-auto rounded-lg border border-ctp-surface1 bg-ctp-mantle p-1"
        >
          <p
            v-if="!skills.length"
            class="px-2 py-2 text-center text-[11px] text-ctp-overlay0"
          >{{ t('guard.importEmpty') }}</p>
          <button
            v-for="(s, i) in skills"
            :key="i"
            class="w-full rounded px-2 py-1 text-left hover:bg-ctp-surface0"
            @click="pickSkill(s)"
          >
            <span class="block truncate text-[11px] text-ctp-text">{{ s.title }}</span>
            <span class="block truncate text-[10px] text-ctp-overlay0">{{ s.digest }}</span>
          </button>
        </div>
        <p
          v-if="err"
          class="text-[10px] text-ctp-red"
        >{{ err }}</p>
      </div>
      <div class="panel-footer flex shrink-0 items-center gap-1.5">
        <button
          v-if="isEdit"
          class="btn btn-xs btn-ghost !text-ctp-red"
          :disabled="busy"
          @click="remove"
        >{{ t('guard.delete') }}</button>
        <span class="flex-1" />
        <button class="btn btn-xs btn-ghost" :disabled="busy" @click="emit('close')">
          {{ t('common.cancel') }}
        </button>
        <button class="btn btn-xs btn-teal" :disabled="busy" @click="save">
          {{ busy ? '…' : t('common.save') }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 规约编辑弹窗(2610 重构): 新建/编辑规约库条目 + 技能库(promoted)导入。
 * 编辑态由父级传 rule(带 id); 保存 emit('saved') 由父级刷新。
 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ClipboardDocumentListIcon } from '@heroicons/vue/24/outline'
import { apiDelete, apiGet } from '@/services/api-client'
import { currentProjectParams } from '@/services/project-service'
import type { RuleDef } from '../useCoreRules'

const props = defineProps<{ rule?: RuleDef | null }>()
const emit = defineEmits<{ close: []; saved: [] }>()
const { t } = useI18n()

const isEdit = computed(() => !!props.rule?.id)
const title = ref(props.rule?.title || '')
const content = ref(props.rule?.content || '')
const busy = ref(false)
const err = ref('')

const skills = ref<Array<{ title: string; content: string; digest: string }>>([])
const skillsOpen = ref(false)
const skillLoading = ref(false)

function digestOf(md: string): string {
  const line = md.split('\n').map((l) => l.trim()).find((l) => l && !l.startsWith('#')) || ''
  return line.length > 64 ? line.slice(0, 64) + '…' : line
}

async function toggleSkills() {
  skillsOpen.value = !skillsOpen.value
  if (!skillsOpen.value || skills.value.length) return
  const p = currentProjectParams().project || ''
  if (!p) return
  skillLoading.value = true
  try {
    const d = await apiGet<{ proposals?: Array<{ title?: string; content?: string }> }>('/capabilities/global')
      .catch(() => null)
    skills.value = (d?.proposals ?? [])
      .filter((x) => (x.content || '').trim())
      .map((x) => ({ title: x.title || '—', content: (x.content || '').trim(), digest: digestOf(x.content || '') }))
  } finally {
    skillLoading.value = false
  }
}

function pickSkill(s: { title: string; content: string }) {
  if (!title.value.trim()) title.value = s.title
  content.value = s.content
  skillsOpen.value = false
}

async function save() {
  if (busy.value) return
  if (!title.value.trim() || !content.value.trim()) {
    err.value = t('guard.needBoth')
    return
  }
  err.value = ''
  busy.value = true
  try {
    const { useCoreRules } = await import('../useCoreRules')
    const api = useCoreRules()
    if (isEdit.value) {
      await api.updateRule(props.rule!.id, { title: title.value.trim(), content: content.value })
    } else {
      await api.createRule(title.value.trim(), content.value)
    }
    emit('saved')
    emit('close')
  } catch (e: any) {
    err.value = String(e?.message || e)
  } finally {
    busy.value = false
  }
}

async function remove() {
  if (busy.value || !props.rule?.id) return
  busy.value = true
  try {
    const p = currentProjectParams().project || ''
    await apiDelete(
      `/arch/rule-defs/${encodeURIComponent(props.rule.id)}?project=${encodeURIComponent(p)}`)
    emit('saved')
    emit('close')
  } catch (e: any) {
    err.value = String(e?.message || e)
  } finally {
    busy.value = false
  }
}
</script>
