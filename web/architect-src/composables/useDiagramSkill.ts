import { ref } from 'vue'

/** 绘图增强(IR→代码)开关 —— 会话级持久化(与 KB chat `topo_diagram_skill` 同构)。 */
const LS_KEY = 'arch_diagram_skill'

export function useDiagramSkill() {
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

  return { diagramSkill: enabled, toggleDiagramSkill: toggle }
}
