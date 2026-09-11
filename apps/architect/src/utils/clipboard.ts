/**
 * 剪贴板工具：安全上下文用 navigator.clipboard，
 * HTTP+局域网 IP 等非安全上下文降级 execCommand(隐藏 textarea)。
 * 全应用统一入口——勿在页面内直连 navigator.clipboard(静默失败)。
 */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // fallthrough → execCommand 降级
  }
  try {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    return ok
  } catch {
    return false
  }
}
