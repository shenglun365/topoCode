<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { CheckIcon, ClipboardDocumentListIcon, PlusIcon, XMarkIcon } from '@heroicons/vue/24/outline'
import { useArchTagStore } from '@/stores/tag-store'
import { useTagTaxonomy } from '@/composables/useTagTaxonomy'

const props = defineProps<{ open: boolean; tags: string[] }>()
const emit = defineEmits<{ close: []; update: [tags: string[]] }>()

const { t } = useI18n()
const tagStore = useArchTagStore()
const { TAG_GROUPS, tagColorOf, defaultTagLabel, groupKeyOf } = useTagTaxonomy()

// ---- 弹窗维度(内置 + 自定义类别/标签) ----
interface TagOption { id: string; label: string; custom: boolean }
interface TagCategory { key: string; label: string; mode: 'single' | 'multi'; tags: TagOption[]; custom: boolean }

const formTags = ref<string[]>([])

watch(
  () => props.open,
  (v) => {
    if (v) formTags.value = [...props.tags]
  },
)

const categories = computed<TagCategory[]>(() => {
  const cats: TagCategory[] = []
  for (const g of TAG_GROUPS) {
    const defs: TagOption[] = g.tags.map((id) => ({ id, label: defaultTagLabel(id), custom: false }))
    const customs: TagOption[] = tagStore.activeTagsOf(g.key).map((ct) => ({ id: ct.id, label: ct.label, custom: true }))
    cats.push({ key: g.key, label: t(`requirement.form.tagGroup.${g.key}`), mode: g.mode, tags: [...defs, ...customs], custom: false })
  }
  for (const cg of tagStore.activeGroups) {
    const customs: TagOption[] = tagStore.activeTagsOf(cg.key).map((ct) => ({ id: ct.id, label: ct.label, custom: true }))
    cats.push({ key: cg.key, label: cg.label, mode: cg.mode, tags: customs, custom: true })
  }
  return cats
})

const customTagInput = reactive<Record<string, string>>({})
const addingTagGroup = ref('')
const customInputRef = ref<HTMLInputElement | null>(null)
function startAddCustomTag(groupKey: string) {
  addingTagGroup.value = groupKey
  customTagInput[groupKey] = ''
  nextTick(() => customInputRef.value?.focus())
}
function confirmAddCustomTag(groupKey: string) {
  if ((customTagInput[groupKey] ?? '').trim()) tagStore.addCustomTag(groupKey, customTagInput[groupKey])
  customTagInput[groupKey] = ''
  addingTagGroup.value = ''
}
function cancelAddCustomTag(groupKey: string) {
  if (addingTagGroup.value === groupKey) {
    customTagInput[groupKey] = ''
    addingTagGroup.value = ''
  }
}

const addingCategory = ref(false)
const newCategoryName = ref('')
const newCategoryMode = ref<'single' | 'multi'>('multi')
const categoryInputRef = ref<HTMLInputElement | null>(null)
function startAddCategory() {
  addingCategory.value = true
  newCategoryName.value = ''
  newCategoryMode.value = 'multi'
  nextTick(() => categoryInputRef.value?.focus())
}
function addCustomCategory() {
  tagStore.addCustomGroup(newCategoryName.value, newCategoryMode.value)
  newCategoryName.value = ''
  addingCategory.value = false
}
function offlineTag(tag: string) {
  tagStore.offlineTag(tag)
  emit('update', formTags.value.filter((t) => t !== tag))
}
function offlineGroup(key: string) {
  tagStore.offlineGroup(key)
  emit('update', formTags.value.filter((t) => groupKeyOf(t)?.key !== key))
}

/** 弹窗选择：单选维度互斥(含自定义标签)，多选维度可切换。 */
function toggleTag(tag: string) {
  const group = groupKeyOf(tag)
  const next = group?.mode === 'single'
    ? formTags.value.filter((t) => groupKeyOf(t)?.key !== group.key).concat(tag)
    : formTags.value.includes(tag)
      ? formTags.value.filter((t) => t !== tag)
      : [...formTags.value, tag]
  emit('update', next)
}

function close() {
  emit('close')
}
</script>

<template>
  <div
    v-if="open"
    class="fixed inset-0 z-50 flex items-center justify-center bg-ctp-crust/60 backdrop-blur-sm p-4"
    @click.self="close"
  >
    <div class="panel w-full max-w-lg max-h-[80vh] overflow-hidden flex flex-col">
      <div class="panel-header shrink-0">
        <span class="flex items-center gap-2">
          <ClipboardDocumentListIcon class="w-4 h-4 text-ctp-peach" />{{ t('requirement.form.tagPickerTitle') }}
        </span>
        <button
          class="btn btn-xs btn-ghost"
          @click="close"
        >
          <XMarkIcon class="w-3.5 h-3.5" />
        </button>
      </div>
      <div class="flex-1 min-h-0 overflow-auto p-3 space-y-3">
        <div
          v-for="g in categories"
          :key="g.key"
          class="space-y-1.5"
        >
          <div class="flex items-center gap-2">
            <span class="text-[11px] font-medium text-ctp-subtext1">{{ g.label }}</span>
            <span
              class="chip bg-ctp-surface0 text-[10px]"
            >{{ g.mode === 'single' ? t('requirement.form.tagMode.single') : t('requirement.form.tagMode.multi') }}</span>
            <button
              v-if="g.custom"
              class="ml-auto btn btn-xs btn-ghost text-ctp-red/80 hover:text-ctp-red"
              :title="t('requirement.form.tagOfflineGroup')"
              @click="offlineGroup(g.key)"
            >
              <XMarkIcon class="w-3 h-3" />
            </button>
          </div>
          <div class="flex flex-wrap gap-1.5">
            <button
              v-for="tag in g.tags"
              :key="tag.id"
              class="chip cursor-pointer transition-colors"
              :class="formTags.includes(tag.id) ? tagColorOf(tag.id) + ' ring-1 ring-ctp-blue/40' : 'bg-ctp-surface0 text-ctp-subtext0 border border-ctp-surface1'"
              @click="toggleTag(tag.id)"
            >
              <span :title="tag.id">{{ tag.label }}</span>
              <span
                v-if="formTags.includes(tag.id)"
                class="ml-0.5"
              >✓</span>
              <span
                v-if="tag.custom"
                class="ml-1 text-ctp-overlay1 hover:text-ctp-red"
                role="button"
                tabindex="-1"
                :title="t('requirement.form.tagOffline')"
                @click.stop="offlineTag(tag.id)"
              >×</span>
            </button>
            <template v-if="addingTagGroup === g.key">
              <input
                ref="customInputRef"
                v-model="customTagInput[g.key]"
                class="input !py-0.5 !px-2 text-[11px] w-32"
                :placeholder="t('requirement.form.tagCustomPlaceholder')"
                @keydown.enter.prevent="confirmAddCustomTag(g.key)"
                @keydown.esc="cancelAddCustomTag(g.key)"
                @blur="confirmAddCustomTag(g.key)"
              >
            </template>
            <button
              v-else
              class="chip border border-dashed border-ctp-surface1 text-ctp-overlay1 hover:text-ctp-blue hover:border-ctp-blue/40 cursor-pointer transition-colors"
              :title="t('requirement.form.tagCustomPlaceholder')"
              @click="startAddCustomTag(g.key)"
            >
              <PlusIcon class="w-3 h-3" />
            </button>
          </div>
        </div>

        <!-- 自定义类别 -->
        <div class="border-t border-ctp-surface0 pt-3 space-y-2">
          <div class="flex items-center gap-2">
            <span class="text-[11px] font-medium text-ctp-subtext1">{{ t('requirement.form.tagCustomCategory') }}</span>
            <template v-if="addingCategory">
              <input
                ref="categoryInputRef"
                v-model="newCategoryName"
                class="input !py-0.5 !px-2 text-[11px] w-36"
                :placeholder="t('requirement.form.tagCustomCategoryPlaceholder')"
                @keydown.enter.prevent="addCustomCategory"
                @keydown.esc="addingCategory = false"
                @blur="addCustomCategory"
              >
              <div class="flex gap-0.5 shrink-0">
                <button
                  class="btn btn-xs"
                  :class="newCategoryMode === 'single' ? 'btn-blue' : 'btn-ghost'"
                  @mousedown.prevent
                  @click="newCategoryMode = 'single'"
                >
                  {{ t('requirement.form.tagMode.single') }}
                </button>
                <button
                  class="btn btn-xs"
                  :class="newCategoryMode === 'multi' ? 'btn-blue' : 'btn-ghost'"
                  @mousedown.prevent
                  @click="newCategoryMode = 'multi'"
                >
                  {{ t('requirement.form.tagMode.multi') }}
                </button>
              </div>
            </template>
            <button
              v-else
              class="chip border border-dashed border-ctp-surface1 text-ctp-overlay1 hover:text-ctp-blue hover:border-ctp-blue/40 cursor-pointer transition-colors"
              @click="startAddCategory"
            >
              <PlusIcon class="w-3 h-3" />{{ t('requirement.form.tagCustomCategoryAdd') }}
            </button>
          </div>
          <p class="text-[10px] text-ctp-overlay0">
            {{ t('requirement.form.tagCustomHint') }}
          </p>
        </div>
      </div>
      <div class="shrink-0 border-t border-ctp-surface0 p-2.5 flex justify-end">
        <button
          class="btn btn-sm btn-primary"
          @click="close"
        >
          <CheckIcon class="w-3.5 h-3.5" />{{ t('common.confirm') }}
        </button>
      </div>
    </div>
  </div>
</template>
