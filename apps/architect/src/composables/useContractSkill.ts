import { ref } from 'vue'

/** 期望固化(契约条目)开关 —— 会话级持久化(与 📐 绘图增强同构)。
 *  开启后方案对话 agent 主动把可验证期望固化为契约条目草稿(🧾)。 */
const LS_KEY = 'arch_contract_skill'

export function useContractSkill() {
  const enabled = ref(false)
  try {
    enabled.value = localStorage.getItem(LS_KEY) === '1'
  } catch {
    /* ignore */
  }

  function toggle(value?: boolean) {
    enabled.value = value ?? !enabled.value
    try {
      localStorage.setItem(LS_KEY, enabled.value ? '1' : '0')
    } catch {
      /* ignore */
    }
  }

  return { contractSkill: enabled, toggleContractSkill: toggle }
}
