/** Function Group Store — 功能组上下文管理

核心职责：
1. 维护当前激活的功能组 (home/analysis/knowledge/coder)
2. 按功能组独立管理 projectId + tabs + 自定义状态
3. 切换功能组时保存/恢复上下文
*/
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { HomeTab } from '@/stores/project'

export type FuncGroupId = 'home' | 'code' | 'analysis' | 'knowledge' | 'coder'

export interface FuncGroupContext {
    projectId?: string;
    tabs: HomeTab[];
    activeTabId?: string;
    // 各功能组自定义状态
    extraState?: { [key: string]: any };
}

interface FuncGroupContextMap {
    home: FuncGroupContext;
    code: FuncGroupContext;
    analysis: FuncGroupContext;
    knowledge: FuncGroupContext;
    coder: FuncGroupContext;
}

export const useFuncGroupStore = defineStore('funcGroup', () => {
    // State
    const activeFuncGroup = ref<FuncGroupId>('home');
    const context = ref<FuncGroupContextMap>({
        home: { tabs: [] },
        code: { tabs: [] },
        analysis: { tabs: [] },
        knowledge: { tabs: [] },
        coder: { tabs: [] },
    });

    // Getters
    const currentContext = computed(() => {
        return context.value[activeFuncGroup.value];
    });

    const currentProjectId = computed(() => {
        return context.value[activeFuncGroup.value].projectId;
    });

    const currentTabs = computed(() => {
        return context.value[activeFuncGroup.value].tabs;
    });

    const currentActiveTabId = computed(() => {
        return context.value[activeFuncGroup.value].activeTabId;
    });

    const currentActiveTab = computed(() => {
        const ctx = context.value[activeFuncGroup.value];
        return ctx.tabs.find(t => t.id === ctx.activeTabId) || null;
    });

    // Actions
    function switchFuncGroup(group: FuncGroupId) {
        if (activeFuncGroup.value === group) return;
        activeFuncGroup.value = group;
    }

    function selectProject(group: FuncGroupId, projectId: string) {
        context.value[group].projectId = projectId;
        // 如果当前激活的 tab 不属于新项目，切换到新项目的第一个 tab
        const ctx = context.value[group];
        if (ctx.activeTabId) {
            const activeTab = ctx.tabs.find(t => t.id === ctx.activeTabId);
            if (activeTab && activeTab.projectId !== projectId) {
                const firstTab = ctx.tabs.find(t => t.projectId === projectId);
                ctx.activeTabId = firstTab?.id || null;
            }
        }
    }

    function deselectProject(group: FuncGroupId) {
        context.value[group].projectId = undefined;
        context.value[group].tabs = [];
        context.value[group].activeTabId = undefined;
    }

    // Tab 操作
    function openTab(group: FuncGroupId, tab: HomeTab) {
        const ctx = context.value[group];
        // 检查是否已打开
        const existing = ctx.tabs.find(t => t.id === tab.id);
        if (existing) {
            ctx.activeTabId = existing.id;
            return existing.id;
        }
        ctx.tabs.push(tab);
        ctx.activeTabId = tab.id;
        return tab.id;
    }

    function closeTab(group: FuncGroupId, tabId: string): boolean {
        const ctx = context.value[group];
        const idx = ctx.tabs.findIndex(t => t.id === tabId);
        if (idx === -1) return false;

        ctx.tabs.splice(idx, 1);

        if (ctx.activeTabId === tabId) {
            if (ctx.tabs.length > 0) {
                const newIdx = Math.min(idx, ctx.tabs.length - 1);
                ctx.activeTabId = ctx.tabs[newIdx].id;
            } else {
                ctx.activeTabId = undefined;
            }
        }

        return true;
    }

    function setActiveTab(group: FuncGroupId, tabId: string | null) {
        context.value[group].activeTabId = tabId || undefined;
    }

    function moveTab(group: FuncGroupId, fromIdx: number, toIdx: number) {
        const ctx = context.value[group];
        if (fromIdx < 0 || fromIdx >= ctx.tabs.length) return;
        if (toIdx < 0 || toIdx >= ctx.tabs.length) return;
        if (fromIdx === toIdx) return;
        const [tab] = ctx.tabs.splice(fromIdx, 1);
        ctx.tabs.splice(toIdx, 0, tab);
    }

    function closeAllTabs(group: FuncGroupId) {
        context.value[group].tabs = [];
        context.value[group].activeTabId = undefined;
    }

    // 状态持久化
    function saveExtraState(group: FuncGroupId, state: { [key: string]: any }) {
        context.value[group].extraState = { ...context.value[group].extraState, ...state };
    }

    function getExtraState(group: FuncGroupId): { [key: string]: any } | undefined {
        return context.value[group].extraState;
    }

    return {
        activeFuncGroup,
        context,
        currentContext,
        currentProjectId,
        currentTabs,
        currentActiveTabId,
        currentActiveTab,
        switchFuncGroup,
        selectProject,
        deselectProject,
        openTab,
        closeTab,
        moveTab,
        setActiveTab,
        closeAllTabs,
        saveExtraState,
        getExtraState,
    };
});
