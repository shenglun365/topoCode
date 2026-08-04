<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  ArrowRightIcon, BarsArrowDownIcon, ClipboardIcon, CodeBracketIcon, CommandLineIcon,
  CubeTransparentIcon, DocumentTextIcon, FolderIcon, PlusIcon, ShieldCheckIcon,
} from '@heroicons/vue/24/outline'
import { CheckIcon } from '@heroicons/vue/24/solid'
import { useArchProjectStore } from '@/stores/project-store'
import { useArchRequirementStore } from '@/stores/requirement-store'
import { useArchWorkflowStore } from '@/stores/workflow-store'
import ProjectSetupDialog from '@/components/project/ProjectSetupDialog.vue'

const router = useRouter()
const { t } = useI18n()
const project = useArchProjectStore()
const workflow = useArchWorkflowStore()
const requirement = useArchRequirementStore()

const copied = ref(false)
const showSetup = ref(false)

onMounted(() => {
  project.load()
  requirement.load()
})

const recentRequirements = computed(() =>
  requirement.items
    .filter((r) => r.status === 'planned' || r.status === 'executing' || r.status === 'done')
    .sort((a, b) => b.updatedAt - a.updatedAt)
    .slice(0, 4),
)
const todoRequirements = computed(() =>
  requirement.items
    .filter((r) => r.status === 'raw' || r.status === 'analyzing' || r.status === 'analyzed' || r.status === 'designed')
    .sort((a, b) => b.updatedAt - a.updatedAt),
)

const status = computed(() => project.status)
const short = (hash: string) => hash.slice(0, 7)

async function copyPath() {
  if (!project.project) return
  await navigator.clipboard.writeText(project.project.rootPath)
  copied.value = true
  setTimeout(() => (copied.value = false), 1500)
}

const stats = computed(() => {
  const s = status.value
  if (!s) return []
  return [
    {
      icon: ShieldCheckIcon,
      label: t('overview.baseline'),
      value: `${s.baseline.version}`,
      sub: `${s.baseline.id} · ${short(s.baseline.commit)}`,
    },
    {
      icon: CodeBracketIcon,
      label: t('overview.head'),
      value: `${short(s.head.commit)}`,
      sub: `${s.head.branch} · ${t('overview.commitsAhead', { n: s.head.ahead })}`,
    },
    {
      icon: DocumentTextIcon,
      label: t('overview.filesChanged'),
      value: `${s.diff.filesChanged}`,
      sub: `+${s.diff.added} / ~${s.diff.modified} / -${s.diff.deleted}`,
    },
    {
      icon: BarsArrowDownIcon,
      label: t('overview.commits'),
      value: `${s.head.ahead}`,
      sub: s.lastRebaseline
        ? `${t('overview.lastRebaseline')}: ${new Date(s.lastRebaseline).toLocaleDateString()}`
        : t('overview.aheadOfBaseline'),
    },
  ]
})
</script>

<template>
  <div class="p-6 max-w-6xl mx-auto space-y-6">
    <header class="flex items-center gap-3">
      <CubeTransparentIcon class="w-9 h-9 text-ctp-blue" />
      <div>
        <h1 class="text-xl font-semibold">
          {{ t('overview.title') }}
        </h1>
        <p class="text-xs text-ctp-subtext0 mt-0.5">
          {{ t('app.tagline') }}
        </p>
      </div>
    </header>

    <section
      v-if="!project.project || project.isGreenfield"
      class="panel border-dashed border-ctp-surface1 bg-ctp-mantle/60 p-6 text-center"
    >
      <CubeTransparentIcon class="w-12 h-12 mx-auto text-ctp-mauve mb-3" />
      <h2 class="text-base font-medium text-ctp-text mb-1">{{ t('overview.createProject') }}</h2>
      <p class="text-xs text-ctp-subtext0 mb-4 max-w-md mx-auto">
        {{ t('overview.createProjectDesc') }}
      </p>
      <div class="flex items-center justify-center gap-3">
        <button
          class="btn btn-green"
          @click="showSetup = true"
        >
          <PlusIcon class="w-4 h-4" />{{ t('overview.createGreenfield') }}
        </button>
        <button
          class="btn btn-ghost"
          @click=";project.load(); showSetup = false"
        >
          {{ t('overview.haveProject') }}
        </button>
      </div>
    </section>

    <ProjectSetupDialog
      v-if="showSetup"
      @close="showSetup = false"
    />

    <section
      v-if="project.project"
      class="panel p-5"
    >
      <div class="flex flex-wrap items-center gap-4">
        <div class="w-12 h-12 rounded-xl bg-ctp-surface0 flex items-center justify-center">
          <FolderIcon class="w-6 h-6 text-ctp-mauve" />
        </div>
        <div class="flex-1 min-w-0">
          <div class="flex items-center gap-2">
            <span class="text-lg font-medium text-ctp-text">{{ project.project.name }}</span>
            <span class="chip bg-ctp-green/15 text-ctp-green">
              <CheckIcon class="w-3 h-3" />{{ t('overview.bound') }}
            </span>
            <span class="chip bg-ctp-surface0 text-ctp-subtext1">{{ t('overview.branch') }}: {{ project.project.branch }}</span>
            <span
              class="chip bg-ctp-mauve/15 text-ctp-mauve"
              :title="t('overview.kbBaselineHint')"
            >{{ project.project.baselineId }} · {{ short(project.project.baselineCommit) }}</span>
          </div>
          <p class="text-xs text-ctp-subtext0 mt-0.5">
            {{ project.project.desc }}
          </p>
          <div class="mt-2 flex items-center gap-2 bg-ctp-crust border border-ctp-surface0 rounded-md px-3 py-1.5 w-fit max-w-full">
            <CommandLineIcon class="w-4 h-4 shrink-0 text-ctp-teal" />
            <code class="font-mono text-xs text-ctp-sapphire truncate">{{ project.project.rootPath }}</code>
            <button
              class="shrink-0 text-ctp-overlay1 hover:text-ctp-text"
              :title="t('overview.copyPath')"
              @click="copyPath"
            >
              <ClipboardIcon
                v-if="!copied"
                class="w-4 h-4"
              />
              <CheckIcon
                v-else
                class="w-4 h-4 text-ctp-green"
              />
            </button>
          </div>
          <p class="text-[11px] text-ctp-overlay1 mt-1.5">
            {{ t('project.created') }}: {{ new Date(project.project.createdAt).toLocaleString() }}
          </p>
        </div>
        <button
          class="btn btn-green"
          @click="router.push('/workbench/requirements')"
        >
          {{ t('overview.enterWorkbench') }}<ArrowRightIcon class="w-4 h-4" />
        </button>
      </div>
    </section>

    <section class="grid grid-cols-2 lg:grid-cols-4 gap-3">
      <div
        v-for="s in stats"
        :key="s.label"
        class="panel p-4"
      >
        <div class="flex items-center gap-1.5 text-xs text-ctp-overlay1">
          <component
            :is="s.icon"
            class="w-4 h-4 text-ctp-blue"
          />
          {{ s.label }}
        </div>
        <div class="text-2xl font-semibold text-ctp-text mt-1 font-mono">
          {{ s.value }}
        </div>
        <div class="text-[11px] text-ctp-subtext0 mt-0.5 truncate">
          {{ s.sub }}
        </div>
      </div>
    </section>

    <section class="grid grid-cols-1 xl:grid-cols-2 gap-4">
      <div class="panel overflow-hidden">
        <div class="panel-header">
          <span class="flex items-center gap-2">
            <ShieldCheckIcon class="w-4 h-4 text-ctp-mauve" />{{ t('overview.baselineDetail') }}
          </span>
        </div>
        <div
          v-if="status"
          class="p-4 space-y-2 text-xs"
        >
          <p class="flex items-start gap-1.5 text-[11px] text-ctp-overlay1 border border-ctp-surface0 rounded-md px-2.5 py-2">
            <ShieldCheckIcon class="w-3.5 h-3.5 mt-0.5 shrink-0 text-ctp-mauve" />
            <span>{{ t('overview.kbBaselineHint') }}</span>
          </p>
          <div class="flex items-center justify-between">
            <span class="text-ctp-overlay1">{{ t('overview.baselineId') }}</span>
            <code class="font-mono text-ctp-sapphire">{{ status.baseline.id }}</code>
          </div>
          <div class="flex items-center justify-between">
            <span class="text-ctp-overlay1">{{ t('overview.baselineVersion') }}</span>
            <code class="font-mono text-ctp-mauve">{{ status.baseline.version }}</code>
          </div>
          <div class="flex items-center justify-between">
            <span class="text-ctp-overlay1">{{ t('overview.commit') }}</span>
            <code class="font-mono text-ctp-teal">{{ status.baseline.commit }}</code>
          </div>
          <div class="flex items-center justify-between">
            <span class="text-ctp-overlay1">{{ t('overview.kbHash') }}</span>
            <code class="font-mono text-ctp-subtext1">{{ status.baseline.manifestHash }}</code>
          </div>
          <div class="flex items-center justify-between">
            <span class="text-ctp-overlay1">{{ t('project.created') }}</span>
            <span class="text-ctp-subtext1">{{ new Date(status.baseline.createdAt).toLocaleString() }}</span>
          </div>
        </div>
      </div>

      <div class="panel overflow-hidden">
        <div class="panel-header">
          <span class="flex items-center gap-2">
            <DocumentTextIcon class="w-4 h-4 text-ctp-peach" />{{ t('overview.changedFiles') }}
          </span>
          <span
            v-if="status"
            class="text-[11px] text-ctp-overlay1"
          >+{{ status.diff.added }} / ~{{ status.diff.modified }} / -{{ status.diff.deleted }}</span>
        </div>
        <div
          v-if="status"
          class="p-3 space-y-1"
        >
          <div
            v-for="f in status.diff.files"
            :key="f"
            class="flex items-center gap-2 font-mono text-xs text-ctp-subtext1 bg-ctp-crust rounded px-2.5 py-1.5"
          >
            <span class="text-ctp-green shrink-0">+</span>
            <span class="truncate">{{ f }}</span>
          </div>
        </div>
      </div>
    </section>

    <section class="grid grid-cols-1 xl:grid-cols-2 gap-4">
      <div class="panel overflow-hidden">
        <div class="panel-header">
          <span class="flex items-center gap-2">
            <CheckIcon class="w-3.5 h-3.5 text-ctp-green" />{{ t('overview.recentRequirements') }}
          </span>
          <button
            class="btn btn-ghost !py-1 text-xs"
            @click="router.push('/workbench/requirements')"
          >
            {{ t('nav.requirements') }}<ArrowRightIcon class="w-3 h-3" />
          </button>
        </div>
        <div class="p-3 space-y-2">
          <div
            v-for="r in recentRequirements"
            :key="r.id"
            class="flex items-center gap-2 border border-ctp-surface0 rounded-lg px-3 py-2 cursor-pointer hover:border-ctp-surface2 transition-colors"
            @click="router.push('/workbench/requirements')"
          >
            <span class="chip bg-ctp-green/15 text-ctp-green shrink-0">{{ r.id }}</span>
            <span class="flex-1 min-w-0 text-sm text-ctp-text truncate">{{ r.title }}</span>
            <span class="chip bg-ctp-surface0 text-ctp-subtext1 shrink-0">{{ r.priority }}</span>
            <span class="text-[10px] text-ctp-overlay1 shrink-0">{{ new Date(r.updatedAt).toLocaleDateString() }}</span>
          </div>
        </div>
      </div>

      <div class="panel overflow-hidden">
        <div class="panel-header">
          <span class="flex items-center gap-2">
            <ClipboardIcon class="w-3.5 h-3.5 text-ctp-peach" />{{ t('overview.todo') }}
          </span>
          <span class="text-[11px] text-ctp-overlay1">{{ todoRequirements.length }}</span>
        </div>
        <div class="p-3 space-y-2">
          <div
            v-for="r in todoRequirements"
            :key="r.id"
            class="flex items-center gap-2 border border-ctp-surface0 rounded-lg px-3 py-2 cursor-pointer hover:border-ctp-surface2 transition-colors"
            @click="router.push('/workbench/requirements')"
          >
            <span class="chip bg-ctp-peach/15 text-ctp-peach shrink-0">{{ r.id }}</span>
            <span class="flex-1 min-w-0 text-sm text-ctp-text truncate">{{ r.title }}</span>
            <span class="chip bg-ctp-surface0 text-ctp-subtext1 shrink-0">{{ r.priority }}</span>
            <span class="chip bg-ctp-yellow/15 text-ctp-yellow shrink-0">{{ t(`requirement.status.${r.status}`) }}</span>
          </div>
          <p
            v-if="!todoRequirements.length"
            class="text-xs text-ctp-overlay1 py-4 text-center"
          >
            {{ t('overview.todoEmpty') }}
          </p>
        </div>
      </div>
    </section>

    <section class="panel p-5 bg-ctp-mantle/60 border-dashed">
      <h2 class="text-sm font-medium text-ctp-subtext1 mb-1">
        {{ t('workflow.title') }}
      </h2>
      <p class="text-xs text-ctp-subtext0 mb-3">
        {{ t('workflow.pipeline') }}
      </p>
      <div class="flex items-center gap-1.5 flex-wrap">
        <template
          v-for="(step, i) in workflow.stages"
          :key="step.key"
        >
          <span
            class="px-2 py-1 rounded text-[11px]"
            :class="{
              'bg-ctp-blue/15 text-ctp-blue ring-1 ring-ctp-blue/30': step.status === 'active',
              'bg-ctp-green/15 text-ctp-green': step.status === 'done',
              'bg-ctp-surface0 text-ctp-overlay1': step.status === 'locked',
            }"
          >{{ t(`workflow.steps.${step.labelKey}`) }}</span>
          <span
            v-if="i < workflow.stages.length - 1"
            class="text-ctp-overlay0 text-[10px]"
          >→</span>
        </template>
      </div>
    </section>

    <section class="panel p-4 bg-ctp-crust/50 text-xs text-ctp-overlay1">
      <div class="flex items-start gap-2">
        <CommandLineIcon class="w-4 h-4 mt-0.5 shrink-0 text-ctp-teal" />
        <div>
          <div class="text-ctp-subtext1 font-medium mb-1">
            {{ t('overview.launchTitle') }}
          </div>
          <p>{{ t('overview.launchNote') }}</p>
        </div>
      </div>
    </section>
  </div>
</template>
