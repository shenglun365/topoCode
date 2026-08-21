<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { XMarkIcon, CheckIcon } from '@heroicons/vue/24/outline'
import { useArchProjectStore } from '@/stores/project-store'

const { t } = useI18n()
const router = useRouter()
const project = useArchProjectStore()

const emit = defineEmits<{ close: [] }>()

const step = ref(0)
const busy = ref(false)
const form = ref({
  name: '',
  desc: '',
  language: 'Go',
  framework: 'gin',
  moduleLayout: 'mono' as string,
  productForm: 'io' as string,
  execRoot: '',
  kbRoot: '',
})

const STACK_OPTIONS = [
  { language: 'Go', frameworks: ['gin', 'echo', 'fiber'] },
  { language: 'TypeScript', frameworks: ['Vue', 'React', 'Express', 'Nest'] },
  { language: 'Python', frameworks: ['FastAPI', 'Django', 'Flask'] },
  { language: 'Java', frameworks: ['Spring Boot', 'Quarkus'] },
  { language: 'Rust', frameworks: ['axum', 'actix-web'] },
]

const FORM_OPTIONS = [
  { value: 'io', label: t('project.form.io'), desc: t('project.form.ioDesc') },
  { value: 'ui-ue', label: t('project.form.uiUe'), desc: t('project.form.uiUeDesc') },
  { value: 'hybrid', label: t('project.form.hybrid'), desc: t('project.form.hybridDesc') },
]

const LAYOUT_OPTIONS = [
  { value: 'mono', label: t('project.layout.mono') },
  { value: 'multi-service', label: t('project.layout.multiService') },
  { value: 'serverless', label: t('project.layout.serverless') },
  { value: 'custom', label: t('project.layout.custom') },
]

const steps = ['project.form.productForm', 'project.form.stack', 'project.form.details']
const canNext = computed(() => {
  if (step.value === 0) return !!form.value.productForm
  if (step.value === 1) return !!form.value.language && !!form.value.framework
  if (step.value === 2) return !!form.value.name && !!form.value.execRoot
  return false
})

const stack = computed(() => STACK_OPTIONS.find((s) => s.language === form.value.language))

function selectFramework(fw: string) {
  form.value.framework = fw
}

async function createProject() {
  busy.value = true
  await project.createGreenfield({
    name: form.value.name,
    desc: form.value.desc,
    language: form.value.language,
    framework: form.value.framework,
    moduleLayout: form.value.moduleLayout,
    productForm: form.value.productForm,
    execRoot: form.value.execRoot || `/home/dev/projects/${form.value.name || 'my-service'}`,
  })
  busy.value = false
  emit('close')
  router.push('/overview')
}

function back() {
  if (step.value > 0) step.value--
}

function next() {
  if (step.value < steps.length - 1) step.value++
}
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/40" @click.self="emit('close')">
    <div class="bg-ctp-base rounded-xl shadow-2xl border border-ctp-surface0 w-full max-w-xl max-h-[85vh] flex flex-col">
      <!-- Header -->
      <div class="shrink-0 flex items-center justify-between px-5 py-4 border-b border-ctp-surface0">
        <div>
          <h2 class="text-base font-semibold text-ctp-text">{{ t('project.createGreenfield') }}</h2>
          <p class="text-xs text-ctp-subtext0 mt-0.5">{{ t('project.step', { n: step + 1, total: steps.length }) }}：{{ t(steps[step]) }}</p>
        </div>
        <button class="btn btn-ghost !p-1" @click="emit('close')">
          <XMarkIcon class="w-5 h-5" />
        </button>
      </div>

      <!-- Content -->
      <div class="flex-1 overflow-y-auto px-5 py-4">
        <!-- Step 0: Product Form -->
        <div v-if="step === 0" class="space-y-3">
          <div
            v-for="opt in FORM_OPTIONS"
            :key="opt.value"
            class="border rounded-lg px-4 py-3 cursor-pointer transition-colors"
            :class="form.productForm === opt.value ? 'border-ctp-blue bg-ctp-blue/5' : 'border-ctp-surface0 hover:border-ctp-surface2'"
            @click="form.productForm = opt.value"
          >
            <div class="flex items-center justify-between">
              <span class="text-sm font-medium text-ctp-text">{{ opt.label }}</span>
              <CheckIcon v-if="form.productForm === opt.value" class="w-4 h-4 text-ctp-blue" />
            </div>
            <p class="text-xs text-ctp-subtext0 mt-1">{{ opt.desc }}</p>
          </div>
        </div>

        <!-- Step 1: Stack -->
        <div v-if="step === 1" class="space-y-4">
          <div>
            <label class="text-xs text-ctp-overlay1 mb-1.5 block">{{ t('project.form.language') }}</label>
            <div class="flex flex-wrap gap-1.5">
              <button
                v-for="s in STACK_OPTIONS"
                :key="s.language"
                class="chip"
                :class="form.language === s.language ? 'ring-1 ring-ctp-sky/50 bg-ctp-sky/10 text-ctp-sky' : 'bg-ctp-surface0 text-ctp-subtext1'"
                @click="form.language = s.language; form.framework = s.frameworks[0]"
              >{{ s.language }}</button>
            </div>
          </div>
          <div v-if="stack">
            <label class="text-xs text-ctp-overlay1 mb-1.5 block">{{ t('project.form.framework') }}</label>
            <div class="flex flex-wrap gap-1.5">
              <button
                v-for="fw in stack.frameworks"
                :key="fw"
                class="chip"
                :class="form.framework === fw ? 'ring-1 ring-ctp-green/50 bg-ctp-green/10 text-ctp-green' : 'bg-ctp-surface0 text-ctp-subtext1'"
                @click="selectFramework(fw)"
              >{{ fw }}</button>
            </div>
          </div>
          <div>
            <label class="text-xs text-ctp-overlay1 mb-1.5 block">{{ t('project.form.moduleLayout') }}</label>
            <div class="flex flex-wrap gap-1.5">
              <button
                v-for="l in LAYOUT_OPTIONS"
                :key="l.value"
                class="chip"
                :class="form.moduleLayout === l.value ? 'ring-1 ring-ctp-mauve/50 bg-ctp-mauve/10 text-ctp-mauve' : 'bg-ctp-surface0 text-ctp-subtext1'"
                @click="form.moduleLayout = l.value"
              >{{ l.label }}</button>
            </div>
          </div>
        </div>

        <!-- Step 2: Details -->
        <div v-if="step === 2" class="space-y-3">
          <div>
            <label class="text-xs text-ctp-overlay1 mb-1 block">{{ t('project.name') }}</label>
            <input v-model="form.name" class="input" :placeholder="t('project.namePlaceholder')" />
          </div>
          <div>
            <label class="text-xs text-ctp-overlay1 mb-1 block">{{ t('project.desc') }}</label>
            <textarea v-model="form.desc" class="input" rows="2" :placeholder="t('project.descPlaceholder')" />
          </div>
          <div>
            <label class="text-xs text-ctp-overlay1 mb-1 block">{{ t('project.form.execRoot') }}</label>
            <input v-model="form.execRoot" class="input" :placeholder="`/home/dev/projects/${form.name || 'my-service'}`" />
          </div>
          <div>
            <label class="text-xs text-ctp-overlay1 mb-1 block">{{ t('project.form.kbRoot') }} <span class="text-ctp-overlay2">({{ t('optional') }})</span></label>
            <input v-model="form.kbRoot" class="input" :placeholder="t('project.form.kbRootPlaceholder')" />
          </div>
        </div>
      </div>

      <!-- Footer -->
      <div class="shrink-0 flex items-center justify-between px-5 py-3 border-t border-ctp-surface0">
        <button v-if="step > 0" class="btn btn-ghost text-sm" @click="back">
          {{ t('guide.back') }}
        </button>
        <div v-else />
        <div class="flex items-center gap-2">
          <button class="btn btn-ghost text-sm text-ctp-overlay1" @click="emit('close')">
            {{ t('guide.skip') }}
          </button>
          <button
            v-if="step < steps.length - 1"
            class="btn btn-blue text-sm"
            :disabled="!canNext"
            @click="next"
          >
            {{ t('guide.next') }}
          </button>
          <button
            v-else
            class="btn btn-green text-sm"
            :disabled="!canNext || busy"
            @click="createProject"
          >
            {{ busy ? t('common.loading') : t('project.create') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>