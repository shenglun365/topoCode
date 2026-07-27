export interface DiagramViewState {
  zs: number
  dx: number
  dy: number
  h?: number
}

const DIAG_STATE_PREFIX = 'topoone_diag_state:'

class DiagramStateStore {
  private dirty = new Set<string>()

  private key(contentId: string): string {
    return DIAG_STATE_PREFIX + contentId
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
    this.dirty.add(contentId)
  }

  /** 清除某个 contentId 的 LS 状态 */
  removeAll(contentId: string): void {
    try { localStorage.removeItem(this.key(contentId)) } catch {}
    this.dirty.delete(contentId)
  }

  /** 是否有未保存状态 */
  isDirty(contentId: string): boolean {
    return this.dirty.has(contentId)
  }
  hasUnsaved(contentId: string): boolean {
    return this.isDirty(contentId)
  }

  /** 是否有任何消息有未保存状态 */
  hasAnyUnsaved(messages: { id?: string }[]): boolean {
    return messages.some(m => m.id && this.dirty.has(m.id))
  }

  /** 清除脏标记 */
  clearDirty(contentId?: string): void {
    if (contentId) this.dirty.delete(contentId)
    else this.dirty.clear()
  }

  /** 将状态嵌入到消息内容中（<!-- diagram:... --> 头部） */
  embedInContent(content: string, contentId: string): string {
    const states = this.loadAll(contentId)
    if (!Object.keys(states).length) return content
    let s = content.replace(/<!--\s*diagram:\S+\s*\{[^}]*\}\s*-->\n?/g, '')
    const lines: string[] = []
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
