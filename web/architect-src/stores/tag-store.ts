import { defineStore } from 'pinia'

/** 自定义类型标签(分类维度下的标签)。 */
export interface TagCustomItem {
  id: string
  groupKey: string
  label: string
  offline: boolean
}

/** 自定义类型类别(维度)。 */
export interface TagCustomGroup {
  key: string
  label: string
  mode: 'single' | 'multi'
  offline: boolean
}

const STORAGE_KEY = 'topocode.tag-taxonomy.v1'

/**
 * 类型标签分类法(自定义部分)。
 * 默认类别/标签由内置分类法 + i18n 提供，不可删除；
 * 自定义类别/标签可「下线」(软删除，不物理删除，保证已使用的标签仍可显示)。
 * 当前为前端持久化(mock 后端存储)。
 */
export const useArchTagStore = defineStore('arch-tag', {
  state: () => ({
    groups: [] as TagCustomGroup[],
    tags: [] as TagCustomItem[],
    seq: 1,
  }),
  getters: {
    /** 未下线(仍可选)的自定义类别。 */
    activeGroups(s): TagCustomGroup[] {
      return s.groups.filter((g) => !g.offline)
    },
    /** 未下线(仍可选)的自定义标签(按类别)。 */
    activeTagsOf: (s) => (groupKey: string): TagCustomItem[] =>
      s.tags.filter((t) => t.groupKey === groupKey && !t.offline),
    /** 按 id 查标签(含已下线，保证已使用的标签仍能显示)。 */
    byId: (s) => (id: string): TagCustomItem | undefined => s.tags.find((t) => t.id === id),
  },
  actions: {
    load() {
      try {
        const raw = localStorage.getItem(STORAGE_KEY)
        if (!raw) return
        const d = JSON.parse(raw) as { groups: TagCustomGroup[]; tags: TagCustomItem[]; seq: number }
        this.groups = d.groups ?? []
        this.tags = d.tags ?? []
        this.seq = d.seq ?? 1
      } catch {
        /* 损坏数据忽略，回退为空 */
      }
    },
    persist() {
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify({ groups: this.groups, tags: this.tags, seq: this.seq }))
      } catch {
        /* 存储失败忽略 */
      }
    },
    addCustomTag(groupKey: string, label: string): TagCustomItem | null {
      const text = label.trim()
      if (!text) return null
      const item: TagCustomItem = { id: `cus:${groupKey}:${this.seq++}`, groupKey, label: text, offline: false }
      this.tags.push(item)
      this.persist()
      return item
    },
    addCustomGroup(label: string, mode: 'single' | 'multi'): TagCustomGroup | null {
      const text = label.trim()
      if (!text) return null
      const g: TagCustomGroup = { key: `cgroup:${this.seq++}`, label: text, mode, offline: false }
      this.groups.push(g)
      this.persist()
      return g
    },
    offlineTag(id: string) {
      const t = this.tags.find((x) => x.id === id)
      if (!t) return
      t.offline = true
      this.persist()
    },
    offlineGroup(key: string) {
      const g = this.groups.find((x) => x.key === key)
      if (g) g.offline = true
      this.tags.forEach((t) => {
        if (t.groupKey === key) t.offline = true
      })
      this.persist()
    },
  },
})
