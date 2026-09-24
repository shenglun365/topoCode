import { ref } from 'vue'

export interface DialogChoice {
  label: string
  value: string
  variant?: 'primary' | 'danger' | 'warning' | 'ghost'
}

export interface DialogState {
  show: boolean
  type: 'confirm' | 'prompt' | 'alert' | 'choices'
  title: string
  message: string
  value: string
  /** type='choices' 时的多选项（MS3-U4 吸收 workbench useConfirm） */
  choices?: DialogChoice[]
  /** 按钮文案可注入（默认中文兜底；宿主可传自身 i18n 文案） */
  okLabel?: string
  cancelLabel?: string
  onOk?: (val?: string) => void
  onCancel?: () => void
}

const dialog = ref<DialogState>({ show: false, type: 'confirm', title: '', message: '', value: '' })

export function useDialog() {
  function confirm(msg: string, title = '确认', labels?: { okLabel?: string; cancelLabel?: string }): Promise<boolean> {
    return new Promise(resolve => {
      dialog.value = { show: true, type: 'confirm', title, message: msg, value: '', okLabel: labels?.okLabel, cancelLabel: labels?.cancelLabel, onOk: () => { dialog.value.show = false; resolve(true) }, onCancel: () => { dialog.value.show = false; resolve(false) } }
    })
  }

  /** 多选项确认（MS3-U4 吸收 workbench useConfirm.confirmChoice 语义）。 */
  function confirmChoice(msg: string, choices: DialogChoice[], title = '请选择'): Promise<string | null> {
    return new Promise(resolve => {
      dialog.value = { show: true, type: 'choices', title, message: msg, value: '', choices, onOk: (v) => { dialog.value.show = false; resolve(v ?? null) }, onCancel: () => { dialog.value.show = false; resolve(null) } }
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

  return { dialog, confirm, confirmChoice, prompt, alert, close }
}
