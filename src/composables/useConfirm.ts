import { ref } from 'vue'

interface ConfirmState {
  visible: boolean
  message: string
  resolve: ((value: boolean) => void) | null
}

const _state = ref<ConfirmState>({ visible: false, message: '', resolve: null })

export function useConfirm() {
  function confirm(message: string): Promise<boolean> {
    return new Promise(resolve => {
      _state.value = { visible: true, message, resolve }
    })
  }

  function confirmResolve(value: boolean) {
    if (_state.value.resolve) {
      _state.value.resolve(value)
      _state.value = { visible: false, message: '', resolve: null }
    }
  }

  return { confirmState: _state, confirm, confirmResolve }
}
