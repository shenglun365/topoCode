export const STYLE_ID = 'ta-anim-style';

/** CSS 契约（docs/engine-design.md §9.1）：全部视觉 = 约定类 + transition，!important 压过引擎内联样式 */
export const CSS_TEXT = [
  '.ta-el { transition: opacity 0.25s ease, transform 0.25s ease; }',
  '.ta-hidden { opacity: 0 !important; pointer-events: none !important; }',
  '.ta-active { filter: drop-shadow(0 0 6px var(--ta-accent, #2196f3)); }',
  '.ta-fx-drawin { stroke-dasharray: var(--ta-len, 1000) !important;',
  '  stroke-dashoffset: var(--ta-len, 1000); animation: ta-draw var(--ta-dur, 0.5s) ease forwards; }',
  '@keyframes ta-draw { to { stroke-dashoffset: 0; } }',
  // Ambient（叙事引擎 §19.4：信号流动/脉冲，生命周期跨 Plan 的持续通道）
  '@keyframes ta-flow { to { stroke-dashoffset: -24; } }',
  '.ta-fx-flow path, .ta-fx-flow line, .ta-fx-flow polyline, .ta-fx-flow polygon {',
  '  stroke-dasharray: 10 6 !important; animation: ta-flow 0.9s linear infinite; }',
  '@keyframes ta-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }',
  '.ta-fx-pulse { animation: ta-pulse 1.4s ease-in-out infinite; }',
  '/* pause: 冻结 ambient/drawin 等 CSS 动画（Scheduler.pause 由宿主加类） */',
  '.ta-paused * { animation-play-state: paused !important; }',
  '.ta-fx-pulse path, .ta-fx-pulse rect, .ta-fx-pulse circle, .ta-fx-pulse ellipse { animation: ta-pulse 1.4s ease-in-out infinite; }',
].join('\n');

export function injectStyle(doc: Document): void {
  if (doc.getElementById(STYLE_ID)) return;
  const style = doc.createElement('style');
  style.id = STYLE_ID;
  style.textContent = CSS_TEXT;
  doc.head.appendChild(style);
}

export function removeStyle(doc: Document): void {
  const el = doc.getElementById(STYLE_ID);
  if (el && el.parentNode) el.parentNode.removeChild(el);
}
