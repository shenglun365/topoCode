<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { CheckIcon } from '@heroicons/vue/24/solid'
import { ShieldCheckIcon, MapPinIcon, BeakerIcon, ClipboardDocumentCheckIcon } from '@heroicons/vue/24/outline'
import MarkdownView from '@/components/MarkdownView.vue'
import { useArchWorkflowStore } from '@/stores/workflow-store'
import { useArchSpecStore } from '@/stores/spec-store'
import { kbAssetService } from '@/services/kb-assets'

const { t } = useI18n()
const workflow = useArchWorkflowStore()
const spec = useArchSpecStore()
spec.load()

const tab = ref<'spec' | 'rules'>('spec')

const ruleLevelColor: Record<string, string> = {
  blocker: 'bg-ctp-red/15 text-ctp-red',
  major: 'bg-ctp-peach/15 text-ctp-peach',
  minor: 'bg-ctp-surface0 text-ctp-subtext1',
}
</script>

<template>
  <div class="space-y-4">
    <!-- 规约内 Tab：架构规约 / 编码规约 -->
    <div class="flex items-center gap-1 bg-ctp-crust/60 rounded-lg p-1 w-fit">
      <button
        class="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm transition-colors"
        :class="tab === 'spec' ? 'bg-ctp-surface1 text-ctp-text' : 'text-ctp-subtext0 hover:text-ctp-text'"
        @click="tab = 'spec'"
      >
        <ShieldCheckIcon class="w-4 h-4" />{{ t('architecture.tab.spec') }}
      </button>
      <button
        class="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm transition-colors"
        :class="tab === 'rules' ? 'bg-ctp-surface1 text-ctp-text' : 'text-ctp-subtext0 hover:text-ctp-text'"
        @click="tab = 'rules'"
      >
        <ClipboardDocumentCheckIcon class="w-4 h-4" />{{ t('architecture.tab.rules') }}
      </button>
    </div>

    <!-- 架构规约 -->
    <div
      v-if="tab === 'spec'"
      class="panel overflow-hidden"
    >
      <div class="panel-header">
        <div class="flex items-center gap-2">
          <ShieldCheckIcon class="w-4 h-4 text-ctp-peach" />{{ t('spec.title') }}
          <span class="chip bg-ctp-mauve/15 text-ctp-mauve">{{ spec.spec?.version ?? '' }}</span>
          <span
            v-if="workflow.specConfirmed"
            class="chip bg-ctp-green/15 text-ctp-green"
          >{{ t('spec.confirmed') }} ✓</span>
        </div>
        <button
          class="btn btn-green !py-1 text-xs"
          :disabled="workflow.specConfirmed"
          @click="spec.confirm()"
        >
          <CheckIcon class="w-3.5 h-3.5" />{{ t('spec.confirm') }}
        </button>
      </div>
      <div class="p-4">
        <p class="text-xs text-ctp-subtext0 mb-4">
          {{ t('spec.desc') }}
        </p>
        <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div class="panel overflow-hidden">
            <div class="panel-header">
              <MapPinIcon class="w-4 h-4 text-ctp-sky" />{{ t('spec.layers.override') }}
            </div>
            <div class="p-3 text-xs">
              <p class="text-[11px] text-ctp-overlay1 mb-2">
                {{ t('spec.layerDesc.override') }}
              </p>
              <div
                v-for="o in spec.spec?.overrides ?? []"
                :key="o.file"
                class="flex items-center gap-2 py-1.5 border-b border-ctp-surface0 last:border-0"
              >
                <span class="font-mono text-ctp-sapphire truncate flex-1">{{ o.file }}</span>
                <span class="chip bg-ctp-surface0 text-ctp-subtext1">{{ o.communityKey }}</span>
                <span
                  v-if="o.pinned"
                  class="chip bg-ctp-red/15 text-ctp-red"
                >{{ t('spec.pinned') }}</span>
              </div>
            </div>
          </div>

          <div class="panel overflow-hidden">
            <div class="panel-header">
              <ShieldCheckIcon class="w-4 h-4 text-ctp-lavender" />{{ t('spec.layers.explicit') }}
            </div>
            <div class="p-3 text-xs">
              <p class="text-[11px] text-ctp-overlay1 mb-2">
                {{ t('spec.layerDesc.explicit') }}
              </p>
              <div
                v-for="r in spec.spec?.explicitRules ?? []"
                :key="r.id"
                class="flex items-start gap-2 py-1.5 border-b border-ctp-surface0 last:border-0"
              >
                <span class="font-mono text-ctp-subtext0 shrink-0">{{ r.id }}</span>
                <span class="flex-1 text-ctp-subtext1">{{ r.text }}</span>
                <span
                  class="chip"
                  :class="ruleLevelColor[r.level]"
                >{{ t(`spec.ruleLevel.${r.level}`) }}</span>
              </div>
            </div>
          </div>

          <div class="panel overflow-hidden">
            <div class="panel-header">
              <BeakerIcon class="w-4 h-4 text-ctp-teal" />{{ t('spec.layers.derived') }}
            </div>
            <div class="p-3 text-xs">
              <p class="text-[11px] text-ctp-overlay1 mb-2">
                {{ t('spec.layerDesc.derived') }}
              </p>
              <div
                v-for="r in spec.spec?.derivedRules ?? []"
                :key="r.id"
                class="flex items-start gap-2 py-1.5 border-b border-ctp-surface0 last:border-0"
              >
                <span class="font-mono text-ctp-subtext0 shrink-0">{{ r.id }}</span>
                <span class="flex-1 text-ctp-subtext1">{{ r.text }}</span>
                <span
                  class="chip"
                  :class="ruleLevelColor[r.level]"
                >{{ t(`spec.ruleLevel.${r.level}`) }}</span>
              </div>
            </div>
          </div>
        </div>

        <div class="mt-4 panel overflow-hidden">
          <div class="panel-header">
            {{ t('spec.changelog') }}
          </div>
          <div class="p-3 text-xs space-y-1.5">
            <div
              v-for="e in spec.spec?.changelog ?? []"
              :key="e.version"
              class="flex items-center gap-2 text-ctp-subtext1"
            >
              <span class="chip bg-ctp-surface0 text-ctp-mauve font-mono">{{ e.version }}</span>
              <span class="flex-1">{{ e.note }}</span>
              <span class="text-[10px] text-ctp-overlay1">{{ e.confirmedBy }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 编码规约 -->
    <div
      v-else-if="tab === 'rules'"
      class="panel overflow-hidden"
    >
      <div class="panel-header">
        <div class="flex items-center gap-2">
          <ClipboardDocumentCheckIcon class="w-4 h-4 text-ctp-lavender" />{{ t('config.codingRules') }}
          <span class="chip bg-ctp-surface0 text-ctp-subtext1 font-mono">CODING_RULES</span>
        </div>
      </div>
      <div class="p-4 max-h-[560px] overflow-auto">
        <MarkdownView :content="kbAssetService.codingRules()" />
      </div>
    </div>
  </div>
</template>
