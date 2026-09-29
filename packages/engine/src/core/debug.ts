/** 编排诊断日志（dev 排查连线/移动动画）：harness 设 window.__TA_DEBUG__=true 或调 setAnimDebug */
let on = false;

export function setAnimDebug(v: boolean): void { on = v; }

export function animDebugOn(): boolean {
  return on || (globalThis as Record<string, unknown>).__TA_DEBUG__ === true;
}

export function animDebug(...args: unknown[]): void {
  if (animDebugOn()) console.log('[ta-anim]', ...args);
}

/** key 尾段简写（ta:mermaid:name:V5 → V5） */
export function shortKey(key: string): string {
  const i = key.lastIndexOf(':');
  return i >= 0 ? key.slice(i + 1) : key;
}
