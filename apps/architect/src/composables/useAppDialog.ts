import { reactive } from 'vue'

/**
 * 全局 DOM 弹窗(替代 window.alert/confirm/prompt)。
 * Promise 化 API + 单例队列; AppDialogHost.vue 挂载于 App 根组件渲染。
 */

type Req =
  | { kind: 'alert'; message: string; resolve: (v: boolean) => void }
  | { kind: 'confirm'; message: string; danger: boolean; confirmText: string; resolve: (v: boolean) => void }
  | { kind: 'prompt'; message: string; value: string; resolve: (v: string | null) => void }

const queue: Req[] = []

const state = reactive({
  current: null as Req | null,
  draft: '',
})

function pump() {
  if (state.current) return
  state.current = queue.shift() ?? null
  state.draft = state.current?.kind === 'prompt' ? state.current.value : ''
}

function finish(v: boolean | string | null) {
  const cur = state.current
  state.current = null
  if (cur) (cur.resolve as (x: unknown) => void)(v)
  pump()
}

export function useAppDialog() {
  function alert(message: string): Promise<true> {
    return new Promise((resolve) => {
      queue.push({ kind: 'alert', message, resolve: () => resolve(true) })
      pump()
    })
  }
  function confirm(message: string, opts?: { danger?: boolean; confirmText?: string }): Promise<boolean> {
    return new Promise((resolve) => {
      queue.push({
        kind: 'confirm', message,
        danger: opts?.danger ?? false,
        confirmText: opts?.confirmText ?? '',
        resolve,
      })
      pump()
    })
  }
  function prompt(message: string, defaultValue = ''): Promise<string | null> {
    return new Promise((resolve) => {
      queue.push({ kind: 'prompt', message, value: defaultValue, resolve })
      pump()
    })
  }
  return { state, alert, confirm, prompt, finish }
}
