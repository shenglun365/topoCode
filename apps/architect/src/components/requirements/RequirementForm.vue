<script setup lang="ts">
import { computed, inject, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  ExclamationTriangleIcon, ClipboardDocumentListIcon, PlusIcon, ScaleIcon, XMarkIcon,
} from '@heroicons/vue/24/outline'
import type { AssetScopeItem, FormDraft } from '@/types'
import { validateForm, resolveAsset } from '@/services/asset-validator'
import { useTagTaxonomy } from '@/composables/useTagTaxonomy'
import TagPickerModal from './TagPickerModal.vue'
import AssetScopeEditor from './AssetScopeEditor.vue'
import ComponentPickerModal from './ComponentPickerModal.vue'
import AssetDetailModal from './AssetDetailModal.vue'

const { t } = useI18n()

/** 父级注入的共享表单对象(双向实时编辑，非一次性 prop)。 */
const form = inject<FormDraft>('requirement-form')!

const { tagColorOf, tagLabelOf } = useTagTaxonomy()

const validation = computed(() => validateForm(form))

// ---- 弹窗状态 ----
const tagPickerOpen = ref(false)
const pickerOpen = ref(false)
const detailOpen = ref(false)
const detailAsset = ref<AssetScopeItem | null>(null)

function removeTag(tag: string) {
  form.tags = form.tags.filter((t) => t !== tag)
}

function openAssetDetail(assetId: string) {
  detailAsset.value = form.assetScope.find((a) => a.assetId === assetId) ?? null
  detailOpen.value = true
}

function addComponent(assetId: string) {
  if (form.assetScope.some((a) => a.assetId === assetId)) return
  const hit = resolveAsset(assetId)
  form.assetScope.push({ assetId, assetType: 'component', role: 'core', source: 'manual', file: hit?.file })
}
</script>

<template>
  <div class="flex flex-col h-full min-h-0">
    <div
      v-if="validation.issues.length"
      class="shrink-0 border border-ctp-peach/40 bg-ctp-peach/10 rounded-lg p-2 mb-2"
    >
      <div class="flex items-center gap-1.5 text-[11px] font-medium text-ctp-peach">
        <ExclamationTriangleIcon class="w-3.5 h-3.5" />{{ t('requirement.form.validateTitle') }}
      </div>
      <ul class="mt-1 space-y-0.5">
        <li
          v-for="(iss, i) in validation.issues"
          :key="i"
          class="flex items-start gap-1.5 text-[10px]"
          :class="iss.level === 'error' ? 'text-ctp-red' : 'text-ctp-subtext1'"
        >
          <span
            class="mt-0.5 w-1 h-1 rounded-full shrink-0"
            :class="iss.level === 'error' ? 'bg-ctp-red' : 'bg-ctp-peach'"
          />
          {{ iss.message }}
        </li>
      </ul>
    </div>

    <div class="flex-1 min-h-0 overflow-auto space-y-3 pr-1">
      <!-- 基本信息(MD) -->
      <div class="panel overflow-hidden">
        <div class="panel-header">
          <span class="flex items-center gap-2">
            <ClipboardDocumentListIcon class="w-4 h-4 text-ctp-peach" />{{ t('requirement.form.basic') }}
          </span>
        </div>
        <div class="p-3 space-y-2.5">
          <div class="flex items-center gap-3">
            <div class="flex-1 min-w-0 flex items-center gap-1.5">
              <label class="text-[11px] text-ctp-overlay1 shrink-0">{{ t('requirement.title') }}</label>
              <input
                v-model="form.title"
                class="input flex-1 min-w-0"
              >
            </div>
            <div class="shrink-0 flex items-center gap-1.5">
              <label class="text-[11px] text-ctp-overlay1 whitespace-nowrap">{{ t('requirement.priority') }}</label>
              <div class="flex gap-1">
                <button
                  v-for="p in (['P0', 'P1', 'P2'] as const)"
                  :key="p"
                  class="btn btn-xs"
                  :class="form.priority === p ? 'btn-blue' : 'btn-ghost'"
                  @click="form.priority = p"
                >
                  {{ p }}
                </button>
              </div>
            </div>
          </div>

          <!-- 类型(多维度标签；弹窗多选) -->
          <div>
            <label class="text-[11px] text-ctp-overlay1">{{ t('requirement.kindLabel') }}</label>
            <div class="mt-1 flex flex-wrap items-center gap-1 rounded-md bg-ctp-crust border border-ctp-surface1 px-2 py-1.5 focus-within:border-ctp-blue focus-within:ring-1 focus-within:ring-ctp-blue">
              <span
                v-for="tag in form.tags"
                :key="tag"
                class="chip"
                :class="tagColorOf(tag)"
              >
                <span :title="tag">{{ tagLabelOf(tag) }}</span>
                <button
                  class="ml-0.5 text-ctp-overlay1 hover:text-ctp-red transition-colors"
                  @click="removeTag(tag)"
                >
                  <XMarkIcon class="w-3 h-3" />
                </button>
              </span>
              <span
                v-if="!form.tags.length"
                class="text-[10px] text-ctp-overlay0"
              >{{ t('requirement.form.tagEmpty') }}</span>
              <button
                class="ml-auto shrink-0 btn btn-xs btn-blue"
                @click="tagPickerOpen = true"
              >
                <PlusIcon class="w-3 h-3" />{{ t('requirement.form.tagPick') }}
              </button>
            </div>
          </div>
          <div>
            <label class="text-[11px] text-ctp-overlay1">{{ t('requirement.form.basicBody') }}</label>
            <textarea
              v-model="form.basicMd"
              rows="8"
              class="input mt-1"
              :placeholder="t('requirement.form.basicMdPlaceholder')"
            />
          </div>
        </div>
      </div>

      <!-- 资源与逻辑的约束(数据资产 + 实现路径 + 规约约束) -->
      <AssetScopeEditor
        @open-detail="openAssetDetail"
        @open-picker="pickerOpen = true"
      />

      <!-- 质量评估(综合结论) -->
      <div class="panel overflow-hidden">
        <div class="panel-header">
          <span class="flex items-center gap-2">
            <ScaleIcon class="w-4 h-4 text-ctp-mauve" />{{ t('requirement.assessment.title') }}
          </span>
        </div>
        <div class="p-3 space-y-2">
          <p class="text-[10px] text-ctp-subtext0">
            {{ t('requirement.assessment.summaryHint') }}
          </p>
          <div class="border border-ctp-surface0 rounded-lg p-2">
            <div class="flex items-center gap-2">
              <span class="text-xs font-medium text-ctp-text">{{ t('requirement.assessment.summary') }}</span>
              <label class="flex items-center gap-1 text-[10px] text-ctp-overlay1 ml-auto">
                {{ t('requirement.estMin') }}
                <input
                  v-model.number="form.estMin"
                  type="number"
                  min="0"
                  step="5"
                  class="input !w-16 !py-0.5 !text-[10px]"
                >
              </label>
            </div>
            <textarea
              v-model="form.assessmentSummary"
              rows="3"
              class="input mt-1.5 text-[11px]"
              :placeholder="t('requirement.assessment.summaryPlaceholder')"
            />
          </div>
        </div>
      </div>
    </div>

    <!-- 类型标签多选弹窗(多维度) -->
    <TagPickerModal
      :open="tagPickerOpen"
      :tags="form.tags"
      @close="tagPickerOpen = false"
      @update="(tags) => (form.tags = tags)"
    />

    <!-- 组件选择弹窗(知识库 API 搜索) -->
    <ComponentPickerModal
      :open="pickerOpen"
      :scoped-ids="form.assetScope.map((a) => a.assetId)"
      @close="pickerOpen = false"
      @add="addComponent"
    />

    <!-- 数据资产详情弹窗(经知识库 API) -->
    <AssetDetailModal
      :open="detailOpen"
      :asset="detailAsset"
      @close="detailOpen = false"
    />
  </div>
</template>
