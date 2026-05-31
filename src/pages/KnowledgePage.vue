<script setup lang="ts">
import { onMounted, ref, onActivated, onDeactivated } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  LightBulbIcon,
  FolderIcon,
  DocumentTextIcon,
  ArrowDownTrayIcon,
  ArrowUpTrayIcon,
  ChevronRightIcon,
  XMarkIcon,
  PlusIcon,
  PlayCircleIcon,
} from '@heroicons/vue/24/outline'
import { useKnowledgeStore } from '@/stores/knowledge'
import { useFuncGroupStore } from '@/stores/funcGroup'
import KnowledgeGraph from '@/components/knowledge/KnowledgeGraph.vue'
import CategoryManager from '@/components/knowledge/CategoryManager.vue'
import KnowledgeDocCard from '@/components/knowledge/KnowledgeDocCard.vue'
import KnowledgeDocEditor from '@/components/knowledge/KnowledgeDocEditor.vue'
import AnimationStage from '@/components/visualization/AnimationStage.vue'
import { knowledgeDimensions } from '@/utils/mock'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('PG-004')
const { t } = useI18n()
const knowledgeStore = useKnowledgeStore()
const funcGroup = useFuncGroupStore()
const showEditor = ref(false)
const animSource = ref(`#TOPOSCRIPT v1.0
# 微服务调用链演示

scene "微服务调用链" layout force-directed width 800 height 600 fps 20

node gateway at (100, 100) label "API Gateway" type service shape rect
  style { fill: "#4A90D9", stroke: "#2C5F8D", radius: 8 }

node auth at (300, 100) label "Auth Service" type service
  style { fill: "#50C878", stroke: "#2E8B57" }

node user_db at (500, 200) label "User DB" type database shape cylinder
  style { fill: "#FFB347", stroke: "#E08C00" }

node cache at (500, 50) label "Redis Cache" type queue
  style { fill: "#FF6B6B", stroke: "#C0392B" }

edge gateway -> auth label "authenticate"
  style { color: "#4A90D9" }
edge auth -> cache label "get token"
edge auth -> user_db label "query user"
  style { color: "#FFB347" }

group auth_group label "认证模块" [auth, cache, user_db]
  style { fill: "rgba(80,200,120,0.1)", stroke: "#50C878" }

animate "请求认证流程" {
  enter gateway effect fade-scale duration 500
  wait 300
  enter auth effect fade duration 500
  draw-edge gateway -> auth duration 300
  flow gateway -> auth duration 1500
  highlight auth duration 800
  enter cache, user_db effect fade-scale duration 500
  draw-edge auth -> cache duration 300
  draw-edge auth -> user_db duration 300
  flow auth -> cache duration 1000
  flow auth -> user_db duration 1000
  highlight auth, cache, user_db duration 1000
  wait 1500
  reset auth, cache, user_db
}
`)
const expandedFilters = ref<Record<string, boolean>>({
  lifecycle: false,
  techStack: false,
  abstraction: false,
  purpose: false,
})

onMounted(async () => {
  await knowledgeStore.loadDocs()
})

/* ===== 状态持久化 ===== */
function saveKnowledgeState() {
  funcGroup.saveExtraState('knowledge', {
    activeTab: knowledgeStore.activeTab,
    filter: knowledgeStore.filter,
  })
}

function restoreKnowledgeState() {
  const extra = funcGroup.getExtraState('knowledge');
  if (extra?.activeTab) {
    knowledgeStore.setActiveTab(extra.activeTab);
  }
  if (extra?.filter) {
    knowledgeStore.filter = extra.filter;
  }
}

onActivated(() => {
  restoreKnowledgeState();
})

onDeactivated(() => {
  saveKnowledgeState();
})

function toggleFilter(dim: string) {
  expandedFilters.value[dim] = !expandedFilters.value[dim]
}

function handleSelectDoc() {
  showEditor.value = true
}

function handleBack() {
  showEditor.value = false
}

function handleSave(docId: string, content: string) {
  const doc = knowledgeStore.docs.find(d => d.id === docId)
  if (doc) {
    doc.content = content
    doc.updatedAt = new Date().toISOString()
  }
}
</script>

<template>
  <div class="page-knowledge">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <!-- 文档编辑器模式 -->
    <KnowledgeDocEditor
      v-if="showEditor && knowledgeStore.selectedDoc"
      :doc="knowledgeStore.selectedDoc"
      @back="handleBack"
      @save="handleSave"
    />

    <!-- 默认模式 -->
    <template v-else>
      <!-- 顶部 Tab 切换 -->
      <div style="display:flex; border-bottom:1px solid var(--border); background:var(--bg-secondary); padding:0 16px;">
        <div
          class="kb-tab"
          :class="{ active: knowledgeStore.activeTab === 'graph' }"
          @click="knowledgeStore.setActiveTab('graph')"
        >
          <LightBulbIcon class="w-4 h-4" />
          <span>{{ t('knowledge.graph') }}</span>
        </div>
        <div
          class="kb-tab"
          :class="{ active: knowledgeStore.activeTab === 'categories' }"
          @click="knowledgeStore.setActiveTab('categories')"
        >
          <FolderIcon class="w-4 h-4" />
          <span>{{ t('knowledge.categories') }}</span>
        </div>
        <div
          class="kb-tab"
          :class="{ active: knowledgeStore.activeTab === 'documents' }"
          @click="knowledgeStore.setActiveTab('documents')"
        >
          <DocumentTextIcon class="w-4 h-4" />
          <span>{{ t('knowledge.documents') }}</span>
        </div>
        <div
          class="kb-tab"
          :class="{ active: knowledgeStore.activeTab === 'animation' }"
          @click="knowledgeStore.setActiveTab('animation')"
        >
          <PlayCircleIcon class="w-4 h-4" />
          <span>{{ t('knowledge.animation') }}</span>
        </div>
        <div style="flex:1;" />
        <div style="display:flex; gap:4px; align-items:center;">
          <button class="btn btn-ghost btn-sm">
            <ArrowDownTrayIcon class="w-4 h-4" />
            <span>{{ t('common.import') }}</span>
          </button>
          <button class="btn btn-ghost btn-sm">
            <ArrowUpTrayIcon class="w-4 h-4" />
            <span>{{ t('common.export') }}</span>
          </button>
        </div>
      </div>

      <!-- 内容区 -->
      <div style="flex:1; overflow:hidden; position:relative;">
        <!-- Tab 1: 知识图谱 -->
        <KnowledgeGraph v-if="knowledgeStore.activeTab === 'graph'" />

        <!-- Tab 2: 分类管理 -->
        <CategoryManager v-else-if="knowledgeStore.activeTab === 'categories'" />

        <!-- Tab 3: 知识点列表 -->
        <div
          v-else-if="knowledgeStore.activeTab === 'documents'"
          style="width:100%; height:100%; overflow:auto; padding:16px;"
        >
          <!-- 搜索 + 排序 -->
          <div style="margin-bottom:12px;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
              <div style="display:flex; gap:8px; align-items:center;">
                <input
                  type="text"
                  class="input input-sm"
                  :placeholder="t('knowledge.searchPlaceholder')"
                  style="width:220px;"
                  :value="knowledgeStore.filter.search"
                  @input="knowledgeStore.setSearch(($event.target as HTMLInputElement).value)"
                >
                <span style="font-size:11px; color:var(--text-muted);">
                  {{ t('knowledge.totalItems', { count: knowledgeStore.filteredDocs.length }) }}
                </span>
              </div>
              <div style="display:flex; gap:6px; align-items:center;">
                <select
                  class="select select-sm"
                  style="width:120px;"
                  :value="knowledgeStore.filter.sortBy"
                  @change="knowledgeStore.setSortBy(($event.target as HTMLSelectElement).value)"
                >
                  <option value="updated-desc">
                    {{ t('knowledge.sortUpdatedDesc') }}
                  </option>
                  <option value="updated-asc">
                    {{ t('knowledge.sortUpdatedAsc') }}
                  </option>
                  <option value="created-desc">
                    {{ t('knowledge.sortCreatedDesc') }}
                  </option>
                  <option value="created-asc">
                    {{ t('knowledge.sortCreatedAsc') }}
                  </option>
                  <option value="name-asc">
                    {{ t('knowledge.sortNameAsc') }}
                  </option>
                </select>
                <button class="btn btn-primary btn-sm">
                  <PlusIcon class="w-4 h-4" />
                  <span>{{ t('common.new') }}</span>
                </button>
                <button class="btn btn-ghost btn-sm">
                  <ArrowDownTrayIcon class="w-4 h-4" />
                  <span>{{ t('common.import') }}</span>
                </button>
              </div>
            </div>

            <!-- 四维折叠筛选 -->
            <div style="display:flex; gap:8px; align-items:flex-start; flex-wrap:wrap;">
              <!-- 维度1 -->
              <div class="kb-dim-filter-group">
                <div
                  class="kb-dim-filter-toggle"
                  @click="toggleFilter('lifecycle')"
                >
                  <ChevronRightIcon
                    class="w-3 h-3"
                    :class="{ 'transform rotate-90': expandedFilters.lifecycle }"
                  />
                  <span>{{ t('knowledge.lifecycle') }}</span>
                </div>
                <div
                  v-if="expandedFilters.lifecycle"
                  class="kb-dim-filter-options"
                >
                  <label
                    v-for="tag in knowledgeDimensions.lifecycle"
                    :key="tag"
                    class="kb-dim-chip"
                  >
                    <input
                      type="checkbox"
                      :value="tag"
                      :checked="knowledgeStore.filter.dimensions.lifecycle.includes(tag)"
                      @change="knowledgeStore.toggleDimension('lifecycle', tag)"
                    >
                    {{ tag }}
                  </label>
                </div>
              </div>

              <!-- 维度2 -->
              <div class="kb-dim-filter-group">
                <div
                  class="kb-dim-filter-toggle"
                  @click="toggleFilter('techStack')"
                >
                  <ChevronRightIcon
                    class="w-3 h-3"
                    :class="{ 'transform rotate-90': expandedFilters.techStack }"
                  />
                  <span>{{ t('knowledge.techStack') }}</span>
                </div>
                <div
                  v-if="expandedFilters.techStack"
                  class="kb-dim-filter-options"
                >
                  <label
                    v-for="tag in knowledgeDimensions.techStack"
                    :key="tag"
                    class="kb-dim-chip"
                  >
                    <input
                      type="checkbox"
                      :value="tag"
                      :checked="knowledgeStore.filter.dimensions.techStack.includes(tag)"
                      @change="knowledgeStore.toggleDimension('techStack', tag)"
                    >
                    {{ tag }}
                  </label>
                </div>
              </div>

              <!-- 维度3 -->
              <div class="kb-dim-filter-group">
                <div
                  class="kb-dim-filter-toggle"
                  @click="toggleFilter('abstraction')"
                >
                  <ChevronRightIcon
                    class="w-3 h-3"
                    :class="{ 'transform rotate-90': expandedFilters.abstraction }"
                  />
                  <span>{{ t('knowledge.abstractionLevel') }}</span>
                </div>
                <div
                  v-if="expandedFilters.abstraction"
                  class="kb-dim-filter-options"
                >
                  <label
                    v-for="tag in knowledgeDimensions.abstraction"
                    :key="tag"
                    class="kb-dim-chip"
                  >
                    <input
                      type="checkbox"
                      :value="tag"
                      :checked="knowledgeStore.filter.dimensions.abstraction.includes(tag)"
                      @change="knowledgeStore.toggleDimension('abstraction', tag)"
                    >
                    {{ tag }}
                  </label>
                </div>
              </div>

              <!-- 维度4 -->
              <div class="kb-dim-filter-group">
                <div
                  class="kb-dim-filter-toggle"
                  @click="toggleFilter('purpose')"
                >
                  <ChevronRightIcon
                    class="w-3 h-3"
                    :class="{ 'transform rotate-90': expandedFilters.purpose }"
                  />
                  <span>{{ t('knowledge.knowledgeAttribute') }}</span>
                </div>
                <div
                  v-if="expandedFilters.purpose"
                  class="kb-dim-filter-options"
                >
                  <label
                    v-for="tag in knowledgeDimensions.purpose"
                    :key="tag"
                    class="kb-dim-chip"
                  >
                    <input
                      type="checkbox"
                      :value="tag"
                      :checked="knowledgeStore.filter.dimensions.purpose.includes(tag)"
                      @change="knowledgeStore.toggleDimension('purpose', tag)"
                    >
                    {{ tag }}
                  </label>
                </div>
              </div>

              <!-- 清除筛选 -->
              <button
                v-if="knowledgeStore.filter.search || Object.values(knowledgeStore.filter.dimensions).some(d => d.length > 0)"
                class="btn btn-ghost btn-sm"
                style="align-self:flex-start; margin-top:2px;"
                @click="knowledgeStore.clearFilters()"
              >
                <XMarkIcon class="w-3 h-3" />
                <span>{{ t('knowledge.clearFilters') }}</span>
              </button>
            </div>
          </div>

          <!-- 文档卡片列表 -->
          <div style="display:flex; flex-direction:column; gap:8px;">
            <KnowledgeDocCard
              v-for="doc in knowledgeStore.filteredDocs"
              :key="doc.id"
              :doc="doc"
              @select="() => { knowledgeStore.selectDoc(doc.id); handleSelectDoc(); }"
              @toggle-favorite="knowledgeStore.toggleFavorite"
              @toggle-pin="knowledgeStore.togglePin"
            />
          </div>

          <!-- 空状态 -->
          <div
            v-if="knowledgeStore.filteredDocs.length === 0"
            class="empty-state"
          >
            <LightBulbIcon class="icon" />
            <div class="title">
              {{ t('knowledge.noDocuments') }}
            </div>
            <div class="desc">
              {{ t('knowledge.addDocumentHint') }}
            </div>
          </div>

          <!-- 分页 -->
          <div
            v-if="knowledgeStore.filteredDocs.length > 0"
            style="display:flex; justify-content:center; align-items:center; gap:8px; margin-top:16px; padding:12px; font-size:11px; color:var(--text-muted);"
          >
            <span>{{ t('knowledge.totalItems', { count: knowledgeStore.filteredDocs.length }) }}</span>
            <div class="divider-vertical" />
            <button
              class="btn btn-ghost btn-sm"
              disabled
            >
              ‹ {{ t('common.prev') }}
            </button>
            <button
              class="btn btn-ghost btn-sm"
              style="background:var(--bg-active);"
            >
              1
            </button>
            <button
              class="btn btn-ghost btn-sm"
              disabled
            >
              {{ t('common.next') }} ›
            </button>
          </div>
        </div>

        <!-- Tab 4: 动画脚本编辑器 + 预览 -->
        <div
          v-else
          style="display:flex; width:100%; height:100%;"
        >
          <!-- 左侧: 编辑器 -->
          <div style="flex:1; display:flex; flex-direction:column; border-right:1px solid var(--border);">
            <div style="display:flex; align-items:center; gap:6px; padding:8px 12px; background:var(--bg-tertiary); border-bottom:1px solid var(--border);">
              <PlayCircleIcon class="w-4 h-4" />
              <span style="font-size:12px; font-weight:600; color:var(--text-primary);">{{ t('knowledge.animation') }}</span>
              <span style="font-size:11px; color:var(--text-muted); margin-left:8px;">TopoScript</span>
            </div>
            <textarea
              v-model="animSource"
              style="flex:1; padding:12px; font-size:12px; font-family:'Fira Code', 'Cascadia Code', 'JetBrains Mono', monospace; line-height:1.6; resize:none; border:none; outline:none; background:var(--bg-primary); color:var(--text-secondary);"
              spellcheck="false"
            />
          </div>
          <!-- 右侧: 预览 -->
          <div style="flex:1; display:flex; flex-direction:column;">
            <AnimationStage
              :source="animSource"
              :show-toolbar="true"
              renderer="d3"
              :width="600"
              :height="500"
            />
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.page-knowledge {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.kb-tab {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  font-size: 12px;
  color: var(--text-muted);
  cursor: pointer;
  border-bottom: 2px solid transparent;
  transition: all 0.15s;
}

.kb-tab:hover {
  color: var(--text-primary);
  background: var(--bg-hover);
}

.kb-tab.active {
  color: var(--accent);
  border-bottom-color: var(--accent);
}

.kb-dim-filter-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.kb-dim-filter-toggle {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  font-size: 11px;
  color: var(--text-muted);
  cursor: pointer;
  border-radius: var(--radius-sm);
  transition: all 0.15s;
}

.kb-dim-filter-toggle:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.kb-dim-filter-options {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  padding: 4px 8px;
  background: var(--bg-secondary);
  border-radius: var(--radius-sm);
}

.kb-dim-chip {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 2px 6px;
  font-size: 10px;
  color: var(--text-muted);
  cursor: pointer;
  border-radius: var(--radius-sm);
  transition: all 0.15s;
}

.kb-dim-chip:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.kb-dim-chip input[type="checkbox"] {
  accent-color: var(--accent);
}
</style>
