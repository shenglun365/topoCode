import { ref } from 'vue'

export interface ChoiceOption {
  label: string
  value: string
  variant?: 'primary' | 'danger' | 'warning' | 'ghost'
}

interface ConfirmState {
  visible: boolean
  message: string
  resolve: ((value: boolean) => void) | null
  choices: ChoiceOption[] | null
  choiceResolve: ((value: string | null) => void) | null
}

const _state = ref<ConfirmState>({ visible: false, message: '', resolve: null, choices: null, choiceResolve: null })

export function useConfirm() {
  function confirm(message: string): Promise<boolean> {
    return new Promise(resolve => {
      _state.value = { visible: true, message, resolve, choices: null, choiceResolve: null }
    })
  }

  function confirmChoice(message: string, choices: ChoiceOption[]): Promise<string | null> {
    return new Promise(resolve => {
      _state.value = { visible: true, message, resolve: null, choices, choiceResolve: resolve }
    })
  }

  function confirmResolve(value: boolean | string | null) {
    const s = _state.value
    if (s.choices && s.choiceResolve) {
      s.choiceResolve(value as string | null)
      _state.value = { visible: false, message: '', resolve: null, choices: null, choiceResolve: null }
    } else if (s.resolve) {
      s.resolve(value as boolean)
      _state.value = { visible: false, message: '', resolve: null, choices: null, choiceResolve: null }
    }
  }

  return { confirmState: _state, confirm, confirmChoice, confirmResolve }
}
