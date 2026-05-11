/**
 * 渲染器模块
 * @module renderer
 */

export type { IRenderer } from './IRenderer';
export { SVGRenderer } from './svg/SVGRenderer';
export { CanvasRenderer } from './canvas/CanvasRenderer';

// 主题
export {
  themeManager,
  getTheme,
  setTheme,
  mergeTheme,
  defaultTheme,
  darkTheme,
  oceanTheme,
  forestTheme,
  sunsetTheme,
  monokaiTheme,
  themePresets,
} from './theme/defaultTheme';

export type { ThemeName } from './theme/defaultTheme';

// 布局
export {
  forceLayout,
  hierarchyLayout,
  gridLayout,
  circularLayout,
  applyLayout,
} from './layout';
