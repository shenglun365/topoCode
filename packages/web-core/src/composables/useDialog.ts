import { ref } from 'vue'

export interface DialogState {
  show: boolean
  type: 'confirm' | 'prompt' | 'alert'
  title: string
  message: string
  value: string
  onOk?: (val?: string) => void
  onCancel?: () => void
}

const dialog = ref<DialogState>({ show: false, type: 'confirm', title: '', message: '', value: '' })

export function useDialog() {
  function confirm(msg: string, title = '确认'): Promise<boolean> {
    return new Promise(resolve => {
      dialog.value = { show: true, type: 'confirm', title, message: msg, value: '', onOk: () => { dialog.value.show = false; resolve(true) }, onCancel: () => { dialog.value.show = false; resolve(false) } }
    })
  }

  function prompt(msg: string, defaultValue = '', title = '输入'): Promise<string | null> {
    return new Promise(resolve => {
      dialog.value = { show: true, type: 'prompt', title, message: msg, value: defaultValue, onOk: (v) => { dialog.value.show = false; resolve(v || null) }, onCancel: () => { dialog.value.show = false; resolve(null) } }
    })
  }

  function alert(msg: string, title = '提示') {
    dialog.value = { show: true, type: 'alert', title, message: msg, value: '', onOk: () => { dialog.value.show = false }, onCancel: undefined }
  }

  function close() {
    dialog.value.show = false
  }

  return { dialog, confirm, prompt, alert, close }
}
