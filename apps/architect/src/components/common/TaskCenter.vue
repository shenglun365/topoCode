<script setup lang="ts">
/** 全局任务中心浮窗（批 1-5）：右下角可折叠面板，语义作业进度/取消/历史。 */
import { useTaskCenter } from './task-center'

const { visible, jobs, active, toggle, close, cancel, labelOf, stateOf, pctOf } = useTaskCenter()

function fmtTime(ts?: number): string {
  if (!ts) return ''
  const d = new Date(ts)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`
}
</script>

<template>
  <!-- 悬浮触发器：badge = 活跃作业数 -->
  <button
    class="tc-trigger"
    :class="{ on: active.length }"
    :title="active.length ? `任务中心：${active.length} 个进行中` : '任务中心'"
    @click="toggle"
  >
    <span class="tc-trigger-icon">⚙</span>
    <span v-if="active.length" class="tc-badge">{{ active.length }}</span>
  </button>

  <div v-if="visible" class="tc-panel">
    <div class="tc-head">
      <span class="tc-title">任务中心</span>
      <span class="tc-sub">运行 {{ active.length }} · 共 {{ jobs.length }}</span>
      <button class="tc-close" title="收起" @click="close">—</button>
    </div>
    <div class="tc-list">
      <div v-if="!jobs.length" class="tc-empty">暂无作业</div>
      <div v-for="j in jobs" :key="j.id" class="tc-card" :class="`s-${j.state}`">
        <div class="tc-row">
          <span class="tc-kind">{{ labelOf(j) }}</span>
          <span class="tc-state">{{ stateOf(j) }}</span>
          <span class="tc-time">{{ fmtTime(j.startedAt || j.createdAt) }}</span>
          <button
            v-if="j.state === 'queued' || j.state === 'running'"
            class="tc-cancel" title="取消" @click="cancel(j.id)"
          >×</button>
        </div>
        <div v-if="j.state === 'running' || j.state === 'queued'" class="tc-bar">
          <div class="tc-bar-fill" :style="{ width: pctOf(j) + '%' }" />
        </div>
        <div class="tc-meta">
          <span v-if="j.progress?.total">{{ j.progress?.done ?? 0 }}/{{ j.progress.total }}</span>
          <span v-if="j.progress?.saved !== undefined">已存 {{ j.progress.saved }}</span>
          <span v-if="j.progress?.current" class="tc-current" :title="j.progress.current">
            {{ j.progress.current }}
          </span>
          <span v-else-if="j.result?.summary" class="tc-summary">{{ j.result.summary }}</span>
          <span v-else-if="j.state === 'failed' && j.result?.summary" class="tc-err">{{ j.result.summary }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tc-trigger {
  position: fixed; right: 18px; bottom: 18px; z-index: 2200;
  width: 40px; height: 40px; border-radius: 50%;
  border: 1px solid var(--bd, #3a3f4b); background: var(--panel, #1e222b);
  color: var(--fg, #cfd6e4); cursor: pointer; font-size: 17px;
  display: flex; align-items: center; justify-content: center;
  box-shadow: 0 2px 10px rgb(0 0 0 / 35%);
}
.tc-trigger.on { border-color: #4a8fd4; }
.tc-badge {
  position: absolute; top: -5px; right: -5px; min-width: 17px; height: 17px;
  border-radius: 9px; background: #d46a4a; color: #fff; font-size: 11px;
  display: flex; align-items: center; justify-content: center; padding: 0 4px;
}
.tc-panel {
  position: fixed; right: 18px; bottom: 68px; z-index: 2200;
  width: 340px; max-height: 60vh; display: flex; flex-direction: column;
  background: var(--panel, #1e222b); border: 1px solid var(--bd, #3a3f4b);
  border-radius: 8px; box-shadow: 0 6px 24px rgb(0 0 0 / 45%);
}
.tc-head {
  display: flex; align-items: center; gap: 8px; padding: 8px 12px;
  border-bottom: 1px solid var(--bd, #333845);
}
.tc-title { font-weight: 600; font-size: 13px; }
.tc-sub { flex: 1; color: var(--dim, #8b93a5); font-size: 12px; }
.tc-close { background: none; border: none; color: var(--dim); cursor: pointer; font-size: 15px; }
.tc-list { overflow-y: auto; padding: 6px; }
.tc-empty { text-align: center; color: var(--dim, #8b93a5); padding: 20px 0; font-size: 12px; }
.tc-card {
  border: 1px solid var(--bd, #2c313d); border-radius: 6px;
  padding: 7px 9px; margin-bottom: 6px; font-size: 12px;
}
.tc-card.s-failed { border-color: #8a4436; }
.tc-card.s-lost { border-color: #6e5a35; }
.tc-row { display: flex; align-items: center; gap: 7px; }
.tc-kind { font-weight: 600; }
.tc-state { color: var(--dim, #8b93a5); }
.tc-card.s-running .tc-state { color: #5aa2dd; }
.tc-card.s-done .tc-state { color: #63b578; }
.tc-card.s-failed .tc-state, .tc-card.s-cancelled .tc-state { color: #d47a5a; }
.tc-time { flex: 1; color: var(--dim, #69707f); font-size: 11px; }
.tc-cancel {
  background: none; border: 1px solid var(--bd, #3a3f4b); border-radius: 4px;
  color: var(--dim); cursor: pointer; width: 20px; height: 20px; line-height: 1;
}
.tc-cancel:hover { color: #d47a5a; border-color: #8a4436; }
.tc-bar {
  height: 4px; border-radius: 2px; background: var(--bd, #2c313d);
  margin: 6px 0 4px; overflow: hidden;
}
.tc-bar-fill { height: 100%; background: #4a8fd4; transition: width .5s; }
.tc-meta { display: flex; gap: 9px; color: var(--dim, #8b93a5); font-size: 11px; }
.tc-current {
  max-width: 160px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  direction: rtl; text-align: left;
}
.tc-summary { color: #63b578; }
.tc-err { color: #d47a5a; }
</style>
