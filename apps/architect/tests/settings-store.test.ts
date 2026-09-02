import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useArchSettingsStore } from '@/stores/settings-store'

describe('arch-settings store（共享键 topoone-locale / topoone-font-size）', () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
  })

  it('默认 locale/fontSize 来自 web-core 共享键（默认 16）', () => {
    const s = useArchSettingsStore()
    expect(['zh-CN', 'en-US']).toContain(s.locale)
    expect(s.fontSize).toBe(16)
  })

  it('setFontSize 持久化共享键并落 root font-size', () => {
    const s = useArchSettingsStore()
    s.setFontSize(22)
    expect(s.fontSize).toBe(22)
    expect(localStorage.getItem('topoone-font-size')).toBe('22')
    expect(document.documentElement.style.fontSize).toBe('22px')
    expect(document.documentElement.style.getPropertyValue('--ui-scale')).toBe(String(22 / 16))
  })

  it('migrateLegacy：旧 arch-settings {locale, fontScale} 迁入共享键并清除', () => {
    localStorage.setItem('arch-settings', JSON.stringify({ locale: 'en-US', fontScale: 1.375 }))
    localStorage.removeItem('topoone-locale')
    localStorage.removeItem('topoone-font-size')
    useArchSettingsStore()
    expect(localStorage.getItem('topoone-locale')).toBe('en-US')
    expect(localStorage.getItem('topoone-font-size')).toBe('22') // 1.375 * 16
    expect(localStorage.getItem('arch-settings')).toBeNull()
  })

  it('migrateLegacy：已有共享键时不覆盖', () => {
    localStorage.setItem('topoone-locale', 'zh-CN')
    localStorage.setItem('arch-settings', JSON.stringify({ locale: 'en-US', fontScale: 2 }))
    useArchSettingsStore()
    expect(localStorage.getItem('topoone-locale')).toBe('zh-CN')
  })
})
