export interface DiagramViewState {
  zs: number
  dx: number
  dy: number
  h?: number
}

const DIAG_STATE_PREFIX = 'topoone_diag_state:'

class DiagramStateStore {
  /** composite key: `${contentId}::${diagId}` */
  private dirty = new Set<string>()

  private key(contentId: string): string {
    return DIAG_STATE_PREFIX + contentId
  }

  private dirtyKey(contentId: string, diagId: string): string {
    return contentId + '::' + diagId
  }

  /** 读某个 contentId（消息 ID）下所有图的状态 */
  loadAll(contentId: string): Record<string, DiagramViewState> {
    try {
      const raw = localStorage.getItem(this.key(contentId))
      return raw ? JSON.parse(raw) : {}
    } catch { return {} }
  }

  /** 读单个图的状态，返回初始状态或默认值 */
  load(diagId: string, contentId: string): DiagramViewState | null {
    const all = this.loadAll(contentId)
    return all[diagId] || null
  }

  /** 写单个图的状态到 LS */
  save(diagId: string, contentId: string, state: DiagramViewState): void {
    const all = this.loadAll(contentId)
    all[diagId] = state
    try { localStorage.setItem(this.key(contentId), JSON.stringify(all)) } catch {}
    this.dirty.add(this.dirtyKey(contentId, diagId))
  }

  /** 清除某个 contentId 下所有图的 LS 状态 */
  removeAll(contentId: string): void {
    try { localStorage.removeItem(this.key(contentId)) } catch {}
    for (const k of [...this.dirty]) {
      if (k.startsWith(contentId + '::')) this.dirty.delete(k)
    }
  }

  /** contentId 下是否有任何图未保存 */
  isDirty(contentId: string): boolean {
    for (const k of this.dirty) {
      if (k.startsWith(contentId + '::')) return true
    }
    return false
  }
  hasUnsaved(contentId: string): boolean {
    return this.isDirty(contentId)
  }

  /** 单个图是否未保存 */
  isDiagDirty(diagId: string, contentId: string): boolean {
    return this.dirty.has(this.dirtyKey(contentId, diagId))
  }

  /** 是否有任何消息有未保存状态 */
  hasAnyUnsaved(messages: { id?: string }[]): boolean {
    return messages.some(m => m.id && this.isDirty(m.id!))
  }

  /** 清除脏标记 */
  clearDirty(contentId?: string, diagId?: string): void {
    if (contentId && diagId) this.dirty.delete(this.dirtyKey(contentId, diagId))
    else if (contentId) {
      for (const k of [...this.dirty]) {
        if (k.startsWith(contentId + '::')) this.dirty.delete(k)
      }
    } else this.dirty.clear()
  }

  /** 将状态嵌入到消息内容中（<!-- diagram:... --> 头部） */
  embedInContent(content: string, contentId: string): string {
    const states = this.loadAll(contentId)
    if (!Object.keys(states).length) return content

    // 保留非脏图的已有头部
    const kept: string[] = []
    const headerRe = /<!--\s*diagram:(\S+)\s*(\{[^}]*\})\s*-->/g
    let m: RegExpExecArray | null
    while ((m = headerRe.exec(content)) !== null) {
      if (!(m[1] in states)) kept.push(m[0])
    }

    // 移除全部旧头部
    let s = content.replace(/<!--\s*diagram:\S+\s*\{[^}]*\}\s*-->\n?/g, '')

    // 写回：保留的非脏头部 + 当前脏图的新头部
    const lines: string[] = [...kept]
    for (const [diagId, state] of Object.entries(states)) {
      lines.push(`<!-- diagram:${diagId} ${JSON.stringify(state)} -->`)
    }
    s = lines.join('\n') + '\n' + s
    return s
  }

  /** 从内容头部解析 <!-- diagram:... --> 得到初始状态映射 */
  extractFromContent(content: string): Record<string, DiagramViewState> {
    const states: Record<string, DiagramViewState> = {}
    const re = /<!--\s*diagram:(\S+)\s*(\{[^}]*\})\s*-->/g
    let m: RegExpExecArray | null
    while ((m = re.exec(content)) !== null) {
      try {
        states[m[1]] = JSON.parse(m[2])
      } catch {}
    }
    return states
  }

  /** 清除内容中的 diagram 状态头部 */
  clearFromContent(content: string): string {
    return content.replace(/<!--\s*diagram:\S+\s*\{[^}]*\}\s*-->\n?/g, '')
  }
}

export const diagramStateStore = new DiagramStateStore()
