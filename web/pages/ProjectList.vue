<script setup lang="ts">
import { ref, computed, onMounted, nextTick } from 'vue'
import * as api from '@web/services/api'
import { t } from '@web/services/i18n'
import type { Project, Task } from '@web/types'
import StarLogoMark from '@web/components/StarLogoMark.vue'

const projects = ref<Project[]>([])
const tasksByProject = ref<Record<string, Task[]>>({})
const loading = ref(true)
const search = ref('')
const page = ref(1)
const pageSize = ref(50)
const expandedProjects = ref<Set<string>>(new Set())

const filteredProjects = computed(() => {
  const q = search.value.toLowerCase().trim()
  if (!q) return projects.value
  return projects.value.filter(p => p.name.toLowerCase().includes(q) || p.rootPath.toLowerCase().includes(q))
})

const allFlattened = computed(() => {
  const result: { project: Project; task: Task | null }[] = []
  for (const proj of filteredProjects.value) {
    const tasks = tasksByProject.value[proj.id]
    if (tasks && tasks.length > 0) {
      for (const t of tasks) {
        result.push({ project: proj, task: t })
      }
    } else {
      result.push({ project: proj, task: null })
    }
  }
  return result
})

const totalPages = computed(() => Math.max(1, Math.ceil(allFlattened.value.length / pageSize.value)))

const pageItems = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return allFlattened.value.slice(start, start + pageSize.value)
})

function projectHasDocs(projectId: string): boolean {
  const tasks = tasksByProject.value[projectId]
  return tasks?.some((t: any) => t.hasDoc) || false
}

function toggleProject(id: string) {
  if (expandedProjects.value.has(id)) {
    expandedProjects.value.delete(id)
  } else {
    expandedProjects.value.add(id)
  }
}

// Check for pending execute from viewer (cross-tab send to chat)
function checkPendingExecute() {
  try {
    const raw = localStorage.getItem('topo_exec_pending')
    if (raw) {
      const pending = JSON.parse(raw)
      localStorage.removeItem('topo_exec_pending')
      if (pending.taskId && pending.refs?.length) {
        window.open(`/chat?taskId=${pending.taskId}`, '_blank')
      }
    }
  } catch (_) {}
}

onMounted(async () => {
  try {
    const projs = await api.listProjects()
    projects.value = projs
    for (const p of projs) {
      try {
        const tasks = await api.listTasks(p.id)
        if (tasks.length > 0) {
          tasksByProject.value[p.id] = tasks
        }
      } catch (_) { /* no tasks */ }
    }
    checkPendingExecute()
  } catch (e) {
    console.error('Failed to load projects:', e)
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="container">
    <div class="page-header">
      <StarLogoMark :size="40" />
      <h1>TopoCode 文档</h1>
    </div>
    <div class="toolbar">
      <form @submit.prevent="page = 1" style="display:flex;gap:8px;flex:1;align-items:center">
        <input v-model="search" type="text" placeholder="搜索项目/任务..." />
        <button type="submit">搜索</button>
      </form>
      <select v-model="pageSize">
        <option :value="50">50条/页</option>
        <option :value="100">100条/页</option>
        <option :value="200">200条/页</option>
      </select>
      <span class="info">共 {{ allFlattened.length }} 条</span>
      <a href="/chat" target="_blank" class="ai-link">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
        AI助手
      </a>
    </div>

    <div v-if="loading" class="empty">加载中...</div>
    <template v-else>
      <div v-for="(item, idx) in pageItems" :key="`${item.project.id}-${item.task?.id || 'no-task'}`">
        <div v-if="idx === 0 || pageItems[idx-1].project.id !== item.project.id" class="project">
          <div class="project-header" @click="toggleProject(item.project.id)">
            <span class="arrow" :class="{ open: expandedProjects.has(item.project.id) }">▶</span>
            <span class="status-dot" :class="projectHasDocs(item.project.id) ? 'done' : 'pending'"></span>
            {{ item.project.name }}
            <span v-if="item.project.isResource" class="badge badge-resource">资源中心导入</span>
          </div>
          <div class="project-tasks" :class="{ open: expandedProjects.has(item.project.id) }">
            <template v-if="item.task">
              <div class="task-item">
                <span class="status-dot" :class="(item.task as any).hasDoc ? 'done' : 'pending'"></span>
                <a v-if="(item.task as any).hasDoc" :href="`/doc?taskId=${item.task.id}&docId=overall-${item.task.id}`">{{ item.task.name }}</a>
                <span v-else class="task-name-pending">{{ item.task.name }}</span>
                <span class="status-label" :class="(item.task as any).hasDoc ? 'done' : 'pending'">
                  {{ (item.task as any).hasDoc ? '已生成' : '未生成' }}
                </span>
              </div>
            </template>
            <template v-else>
              <div class="task-item no-task">资源项目 — 无需分析任务</div>
            </template>
          </div>
        </div>
      </div>

      <div v-if="!allFlattened.length" class="empty">暂无匹配结果</div>

      <div v-if="totalPages > 1" class="pagination">
        <a v-if="page > 1" href="#" @click.prevent="page = page - 1">‹</a>
        <a v-for="pn in totalPages" :key="pn" :class="{ active: pn === page }" href="#" @click.prevent="page = pn">{{ pn }}</a>
        <a v-if="page < totalPages" href="#" @click.prevent="page = page + 1">›</a>
      </div>
    </template>
  </div>
</template>

<style>
:root {
  --bg:#ffffff; --bg-secondary:#f7f7f8; --bg-hover:#f0f0f2;
  --text:#1a1a1a; --text-secondary:#6b6b76; --text-muted:#8e8e98;
  --border:#e4e4e7; --accent:#4d6bfe; --accent-hover:#3a56d4;
  --radius-sm:6px; --radius-md:8px; --radius-lg:12px;
  --font:'Inter',-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
}
@media(prefers-color-scheme:dark){
  :root{--bg:#212121;--bg-secondary:#2d2d2d;--bg-hover:#3d3d3d;--text:#e8e8e8;--text-secondary:#a0a0a0;--text-muted:#6b6b6b;--border:#3d3d3d;--accent:#60a5fa;--accent-hover:#3b82f6}
}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:var(--font);background:var(--bg-secondary);color:var(--text);font-size:14px;line-height:1.6;padding:24px;-webkit-font-smoothing:antialiased}
.container{max-width:760px;margin:0 auto}
.page-header{display:flex;align-items:center;gap:12px;margin-bottom:16px}
h1{font-size:18px;font-weight:600;color:var(--text)}
.toolbar{display:flex;gap:8px;margin-bottom:16px;align-items:center;flex-wrap:wrap}
.toolbar input{padding:7px 12px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:13px;flex:1;min-width:160px;outline:none;background:var(--bg);color:var(--text)}
.toolbar input:focus{border-color:var(--accent)}
.toolbar button{padding:7px 16px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--bg);color:var(--text);cursor:pointer;font-size:12px}
.toolbar button:hover{border-color:var(--accent);color:var(--accent)}
.toolbar select{padding:6px 10px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:12px;background:var(--bg);color:var(--text);outline:none}
.toolbar .info{font-size:12px;color:var(--text-muted)}
.ai-link{font-size:12px;color:var(--accent);text-decoration:none;display:inline-flex;align-items:center;gap:3px;padding:4px 8px;border-radius:4px}
.ai-link:hover{background:var(--bg-hover)}
.project{background:var(--bg);border-radius:var(--radius-lg);border:1px solid var(--border);margin-bottom:10px;overflow:hidden}
.project-header{padding:10px 14px;font-weight:600;font-size:13px;background:var(--bg-secondary);border-bottom:1px solid var(--border);cursor:pointer;display:flex;align-items:center;gap:8px}
.project-header:hover{background:var(--bg-hover)}
.arrow{transition:transform .2s;font-size:10px;color:var(--text-muted)}
.arrow.open{transform:rotate(90deg)}
.project-tasks{overflow:hidden;max-height:0;transition:max-height 0.3s ease, opacity 0.2s ease;opacity:0}
.project-tasks.open{max-height:2000px;opacity:1}
.task-item{padding:8px 14px 8px 32px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:8px}
.task-item:last-child{border-bottom:none}
.task-item a{color:var(--accent);text-decoration:none;font-size:13px}
.task-item a:hover{text-decoration:underline}
.task-item.no-task{color:var(--text-muted);font-size:12px}
.task-name-pending{color:var(--text-muted);font-size:13px}
.status-dot{width:6px;height:6px;border-radius:50%;display:inline-block;flex-shrink:0}
.status-dot.done{background:#10b981}
.status-dot.pending{background:#f59e0b}
.status-label{font-size:11px;font-weight:500}
.status-label.done{color:#10b981}
.status-label.pending{color:#f59e0b}
.empty{padding:20px;color:var(--text-muted);font-size:13px;text-align:center}
.badge{display:inline-block;padding:1px 6px;font-size:10px;font-weight:600;border-radius:4px;vertical-align:middle}
.badge-resource{background:#e8f4fd;color:#2563eb;border:1px solid #93c5fd}
.pagination{display:flex;gap:6px;justify-content:center;margin-top:16px;flex-wrap:wrap}
.pagination a,.pagination span{padding:5px 12px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:12px;text-decoration:none;color:var(--text);background:var(--bg)}
.pagination a:hover{background:var(--bg-hover);border-color:var(--accent)}
.pagination .active{background:var(--accent);color:#fff;border-color:var(--accent)}
</style>
