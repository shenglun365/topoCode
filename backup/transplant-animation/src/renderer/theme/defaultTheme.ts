/**
 * 主题系统
 * @module renderer/theme/defaultTheme
 */

import type { RenderTheme } from '../../core/types';

export type ThemeName = 'default' | 'dark' | 'ocean' | 'forest' | 'sunset' | 'monokai';

/** 默认主题 */
export const defaultTheme: RenderTheme = {
  name: 'default',
  background: '#ffffff',
  node: {
    defaultFill: '#4A90D9',
    defaultStroke: '#2C5F8D',
    defaultFontSize: 12,
    defaultFontColor: '#ffffff',
    highlightFill: '#FFD43B',
    highlightStroke: '#F08C00',
    selectionStroke: '#FF6B6B',
  },
  edge: {
    defaultColor: '#999999',
    defaultWidth: 2,
    highlightColor: '#FF6B6B',
    highlightWidth: 3,
  },
  group: {
    defaultBorder: '#cccccc',
    defaultFill: '#f5f5f5',
    defaultFillOpacity: 0.3,
  },
  text: {
    primary: '#333333',
    secondary: '#666666',
  },
};

/** 深色主题 */
export const darkTheme: RenderTheme = {
  name: 'dark',
  background: '#1a1a2e',
  node: {
    defaultFill: '#16213e',
    defaultStroke: '#0f3460',
    defaultFontSize: 12,
    defaultFontColor: '#e2e2e2',
    highlightFill: '#e2b714',
    highlightStroke: '#f08c00',
    selectionStroke: '#ff6b6b',
  },
  edge: {
    defaultColor: '#4a4a6a',
    defaultWidth: 2,
    highlightColor: '#ff6b6b',
    highlightWidth: 3,
  },
  group: {
    defaultBorder: '#3a3a5a',
    defaultFill: '#2a2a4a',
    defaultFillOpacity: 0.3,
  },
  text: {
    primary: '#e2e2e2',
    secondary: '#a0a0a0',
  },
};

/** 海洋主题 */
export const oceanTheme: RenderTheme = {
  name: 'ocean',
  background: '#0a192f',
  node: {
    defaultFill: '#112240',
    defaultStroke: '#233554',
    defaultFontSize: 12,
    defaultFontColor: '#8892b0',
    highlightFill: '#64ffda',
    highlightStroke: '#52b788',
    selectionStroke: '#ff6b6b',
  },
  edge: {
    defaultColor: '#233554',
    defaultWidth: 2,
    highlightColor: '#64ffda',
    highlightWidth: 3,
  },
  group: {
    defaultBorder: '#233554',
    defaultFill: '#112240',
    defaultFillOpacity: 0.3,
  },
  text: {
    primary: '#8892b0',
    secondary: '#5a6785',
  },
};

/** 森林主题 */
export const forestTheme: RenderTheme = {
  name: 'forest',
  background: '#1b4332',
  node: {
    defaultFill: '#2d6a4f',
    defaultStroke: '#1b4332',
    defaultFontSize: 12,
    defaultFontColor: '#d8f3dc',
    highlightFill: '#f4a261',
    highlightStroke: '#e76f51',
    selectionStroke: '#ff6b6b',
  },
  edge: {
    defaultColor: '#40916c',
    defaultWidth: 2,
    highlightColor: '#f4a261',
    highlightWidth: 3,
  },
  group: {
    defaultBorder: '#2d6a4f',
    defaultFill: '#1b4332',
    defaultFillOpacity: 0.3,
  },
  text: {
    primary: '#d8f3dc',
    secondary: '#95d5b2',
  },
};

/** 日落主题 */
export const sunsetTheme: RenderTheme = {
  name: 'sunset',
  background: '#2d1b69',
  node: {
    defaultFill: '#7b2cbf',
    defaultStroke: '#5a189a',
    defaultFontSize: 12,
    defaultFontColor: '#e0aaff',
    highlightFill: '#ff9e00',
    highlightStroke: '#ff6d00',
    selectionStroke: '#ff6b6b',
  },
  edge: {
    defaultColor: '#9d4edd',
    defaultWidth: 2,
    highlightColor: '#ff9e00',
    highlightWidth: 3,
  },
  group: {
    defaultBorder: '#5a189a',
    defaultFill: '#7b2cbf',
    defaultFillOpacity: 0.2,
  },
  text: {
    primary: '#e0aaff',
    secondary: '#c77dff',
  },
};

/** Monokai 主题 */
export const monokaiTheme: RenderTheme = {
  name: 'monokai',
  background: '#272822',
  node: {
    defaultFill: '#66d9ef',
    defaultStroke: '#4db6bd',
    defaultFontSize: 12,
    defaultFontColor: '#f8f8f2',
    highlightFill: '#f92672',
    highlightStroke: '#f92672',
    selectionStroke: '#fd971f',
  },
  edge: {
    defaultColor: '#75715e',
    defaultWidth: 2,
    highlightColor: '#f92672',
    highlightWidth: 3,
  },
  group: {
    defaultBorder: '#75715e',
    defaultFill: '#3e3d32',
    defaultFillOpacity: 0.3,
  },
  text: {
    primary: '#f8f8f2',
    secondary: '#75715e',
  },
};

/** 所有主题预设 */
export const themePresets: Record<ThemeName, RenderTheme> = {
  default: defaultTheme,
  dark: darkTheme,
  ocean: oceanTheme,
  forest: forestTheme,
  sunset: sunsetTheme,
  monokai: monokaiTheme,
};

/** 主题管理器 */
export class ThemeManager {
  private currentTheme: RenderTheme = defaultTheme;
  private customThemes: Map<string, RenderTheme> = new Map();

  /** 获取当前主题 */
  getCurrent(): RenderTheme {
    return this.currentTheme;
  }

  /** 设置主题 */
  setTheme(name: ThemeName | string): void {
    const preset = themePresets[name as ThemeName];
    if (preset) {
      this.currentTheme = preset;
      return;
    }

    const custom = this.customThemes.get(name);
    if (custom) {
      this.currentTheme = custom;
    }
  }

  /** 注册自定义主题 */
  register(name: string, theme: RenderTheme): void {
    this.customThemes.set(name, theme);
  }

  /** 获取主题 */
  get(name: ThemeName | string): RenderTheme | undefined {
    return themePresets[name as ThemeName] || this.customThemes.get(name);
  }

  /** 合并主题 */
  merge(base: RenderTheme, overlay: Partial<RenderTheme>): RenderTheme {
    return {
      ...base,
      ...overlay,
      node: { ...base.node, ...overlay.node },
      edge: { ...base.edge, ...overlay.edge },
      group: { ...base.group, ...overlay.group },
      text: { ...base.text, ...overlay.text },
    };
  }
}

/** 全局主题管理器 */
export const themeManager = new ThemeManager();

/** 便捷函数 */
export function getTheme(name?: ThemeName | string): RenderTheme {
  if (!name) return themeManager.getCurrent();
  return themeManager.get(name) || defaultTheme;
}

export function setTheme(name: ThemeName | string): void {
  themeManager.setTheme(name);
}

export function mergeTheme(
  base: RenderTheme,
  overlay: Partial<RenderTheme>
): RenderTheme {
  return themeManager.merge(base, overlay);
}
